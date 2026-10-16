import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from salvage.core import isolate, pipeline, report, validate
from salvage.core.jsonschema_lite import load_schema
from salvage.core.model import DecodeResult, Field, Record, Status
from salvage.core.plugin import Decoder
from salvage.formats.stub import MAGIC, StubDecoder

PKG = "tests.fixtures.pipeline_formats"
CLEAN = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)
SHA = "ab" * 32


def report_with(*entries):
    rep = report.new_report()
    for e in entries:
        rep["files"].append(dict(e, output=e.get("output") or "x.json"))
    report.summarize(rep)
    return rep


class SchemaFileTests(unittest.TestCase):
    def test_provisional_schemas_load(self):
        for kind in validate.KINDS:
            with self.subTest(kind=kind):
                rel = validate.SCHEMA_FILES[kind]["provisional"]
                schema = load_schema(os.path.join(validate.SCHEMA_DIR, rel))
                self.assertEqual(schema.name, rel)
                a = validate.active(kind)
                self.assertEqual((a.origin, a.version, a.problems),
                                 ("provisional", "provisional-1", ()))
                self.assertIsNotNone(a.schema)
        self.assertEqual(validate.load_problems(), [])

    def test_official_folder_ships_with_readme_only(self):
        folder = os.path.join(validate.SCHEMA_DIR, "official")
        self.assertEqual(sorted(os.listdir(folder)), ["README.txt"])

    def test_strict_additional_properties(self):
        out = isolate.failed_payload("a", 1, "x")["output"]
        out["extra"] = 1
        self.assertEqual(validate.errors("output", out),
                         ["$.extra: additional property not allowed"])


class OfficialSchemaTests(unittest.TestCase):
    """A schema in official/ replaces the provisional one; a bad one falls back."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="salvage-schemas-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for rel in ("output.provisional.json", "report.provisional.json"):
            shutil.copy(os.path.join(validate.SCHEMA_DIR, rel), tmp)
        os.mkdir(os.path.join(tmp, "official"))
        self.dir = tmp
        patcher = mock.patch.object(validate, "SCHEMA_DIR", tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        validate.active.cache_clear()
        self.addCleanup(validate.active.cache_clear)

    def official(self, kind, doc):
        with open(os.path.join(self.dir, "official", f"{kind}.schema.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(doc, fh)

    def test_official_used_when_present(self):
        self.official("output", {"type": "object", "required": ["records"]})
        a = validate.active("output")
        self.assertEqual((a.origin, a.file, a.version),
                         ("official", "official/output.schema.json", "official"))
        self.assertEqual(validate.version("report"), "provisional-1")
        self.assertEqual(validate.errors("output", {}), ['$: required property "records" is missing'])
        self.assertEqual(validate.load_problems(), [])

    def test_unsupported_official_falls_back_and_is_reported(self):
        self.official("report", {"type": "object", "if": {}, "then": {}})
        a = validate.active("report")
        self.assertEqual((a.origin, a.version), ("provisional", "provisional-1"))
        problems = validate.load_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("official report schema official/report.schema.json not used", problems[0])
        self.assertIn("#/if: if", problems[0])
        self.assertIn("#/then: then", problems[0])


class FailedPayloadTests(unittest.TestCase):
    """Every failed_payload variant validates (output and report entry)."""

    def variants(self):
        info_cands = {"ranked": [{"format": "STUB", "score": 0.75, "error": None},
                                 {"format": "X", "score": 0.0, "error": "probe raised E: e"}],
                      "candidates": ["STUB"], "warnings": ["ambiguous: STUB, Y"]}
        info_none = {"ranked": [{"format": "STUB", "score": 0.1, "error": None}],
                     "candidates": [], "warnings": []}
        yield "no info, unknown size", isolate.failed_payload("a/b.bin", None, "cannot read file: x")
        yield "size, no info", isolate.failed_payload("a", 7, "too large (7 bytes > 1)")
        yield "identified", isolate.failed_payload("a", 7, "timeout after 2s (during decode)",
                                                   info_cands)
        yield "no candidate", isolate.failed_payload("a", 0, "crash", info_none)

    def test_all_variants_validate(self):
        for name, payload in self.variants():
            for sha in (None, SHA):
                with self.subTest(variant=name, sha=sha):
                    out, entry = payload["output"], payload["entry"]
                    out["source"]["sha256"], entry["sha256"] = sha, sha
                    self.assertEqual(validate.errors("output", out), [])
                    self.assertEqual(validate.errors("report", report_with(entry)), [])
                    self.assertIsNone(entry["coverage"])
                    self.assertIsNone(entry["variant"])
                    self.assertEqual(entry["probe_score"], entry["confidence"])

    def test_identified_failure_keeps_probe_score(self):
        payload = dict(self.variants())["identified"]
        self.assertEqual((payload["entry"]["format"], payload["entry"]["probe_score"],
                          payload["output"]["confidence"]), ("STUB", 0.75, 0.75))


class CheckedOutputTests(unittest.TestCase):
    def payload(self):
        p = isolate.process_data("a.stub", CLEAN, [StubDecoder()])
        p["output"]["source"]["sha256"] = p["entry"]["sha256"] = SHA
        return p

    def test_valid_output_untouched(self):
        p = self.payload()
        out, bug = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertIs(out, p["output"])
        self.assertIsNone(bug)

    def test_invalid_output_replaced(self):
        p = self.payload()
        p["output"]["records"][1]["kind"] = 5
        p["output"]["damage"].append({"start": 0, "end": 1, "kind": "melted", "reason": "x"})
        out, bug = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertIsNone(bug)
        self.assertEqual(validate.errors("output", out), [])
        self.assertEqual((out["status"], out["format"], out["variant"], out["confidence"]),
                         ("failed", "STUB", None, 1.0))
        self.assertEqual((out["records"], out["members"], out["damage"], out["meta"]),
                         ([], [], [], {}))
        self.assertEqual(out["source"], {"path": "a.stub", "size": len(CLEAN), "sha256": SHA})
        self.assertTrue(out["errors"][0].startswith("decoder output failed schema validation (2 "))
        self.assertEqual(out["errors"][1:], [
            "$.records[1].kind: expected string, got integer",
            '$.damage[0].kind: "melted" is not one of ["truncated", "checksum", "bounds", '
            '"unparsed", "other"]'])
        entry = p["entry"]
        self.assertEqual((entry["status"], entry["coverage"], entry["damage"], entry["members"]),
                         ("failed", None, [], 0))
        self.assertEqual(entry["errors"], out["errors"])
        self.assertEqual(validate.errors("report", report_with(entry)), [])

    def test_at_most_10_errors_listed(self):
        p = self.payload()
        for rec in p["output"]["records"]:     # 4 records, 5 fields: 13 errors
            rec["kind"] = 1
            rec["status"] = "great"
            for fld in rec["fields"]:
                fld["status"] = "fine"
        out, _ = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertTrue(out["errors"][0].startswith(
            "decoder output failed schema validation (13 errors)"), out["errors"][0])
        self.assertEqual(len(out["errors"]), 11)

    def test_invalid_replacement_is_a_run_error(self):
        p = self.payload()
        p["output"]["records"] = "nope"
        with mock.patch.object(pipeline.emit, "to_output",
                               lambda **kw: {"bogus": True}):
            out, bug = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertEqual(out, {"bogus": True})
        self.assertIn("is itself invalid", bug)


class PipelineValidationTests(unittest.TestCase):
    """B3 in a real run: invalid output replaced, invalid report still written."""

    def run_with(self, mutate_output=None, mutate_entry=None):
        real = pipeline._collect

        def fake(item, worker, sha):
            output, entry, errs = real(item, worker, sha)
            if item.rel == "bad.stub":
                if mutate_output:
                    mutate_output(output)
                if mutate_entry:
                    mutate_entry(entry)
            return output, entry, errs

        tmp = tempfile.mkdtemp(prefix="salvage-val-")
        self.addCleanup(shutil.rmtree, tmp, True)
        inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
        os.makedirs(inp)
        for name in ("bad.stub", "good.stub"):
            with open(os.path.join(inp, name), "wb") as fh:
                fh.write(CLEAN)
        stderr = io.StringIO()
        with mock.patch.object(pipeline, "_collect", fake), \
                mock.patch.object(pipeline.sys, "stderr", stderr):
            rep = pipeline.run(inp, out, decoder_package=PKG, timeout=20, jobs=1)
        files = {}
        for name in ("bad.stub.json", "good.stub.json", "report.json"):
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                files[name] = json.load(fh)
        return rep, files, stderr.getvalue()

    def test_shape_violating_output_replaced(self):
        def mutate(output):
            output["records"][0]["fields"][0]["evidence"] = None
            output["surprise"] = 1

        rep, files, err = self.run_with(mutate_output=mutate)
        bad, good = files["bad.stub.json"], files["good.stub.json"]
        self.assertEqual(bad["status"], "failed")
        self.assertEqual(bad["records"], [])
        self.assertEqual(bad["errors"][1:], [
            "$.records[0].fields[0].evidence: expected string, got null",
            "$.surprise: additional property not allowed"])
        self.assertEqual(validate.errors("output", bad), [])
        self.assertEqual(good["status"], "decoded")
        self.assertEqual(len(good["records"]), 4)
        entries = {e["input"]: e for e in rep["files"]}
        self.assertEqual(entries["bad.stub"]["status"], "failed")
        self.assertEqual(rep["summary"]["failed"], 1)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(validate.errors("report", files["report.json"]), [])
        self.assertEqual(err, "")

    def test_invalid_report_still_written_with_error(self):
        rep, files, err = self.run_with(mutate_entry=lambda e: e.update(extra=1))
        on_disk = files["report.json"]
        self.assertEqual(len(on_disk["errors"]), 1)
        self.assertTrue(on_disk["errors"][0].startswith(
            "report.json fails schema validation (1 errors); first: "
            "$.files[0].extra: additional property not allowed"), on_disk["errors"])
        self.assertIn("report.json fails schema validation", err)
        self.assertEqual(rep, on_disk)


class _VariantDecoder(Decoder):
    """Decodes anything starting with b"V" with a sub-version and its own confidence."""

    name = "T-VARIANT"

    def __init__(self, fmt="T-VARIANT 2.1", confidence=0.4):
        self.fmt, self.conf = fmt, confidence

    def probe(self, data):
        return 0.9 if data[:1] == b"V" else 0.0

    def decode(self, reader):
        reader.bytes(1, "tag")
        return DecodeResult(format=self.fmt, confidence=self.conf, records=[
            Record(0, Status.UNVERIFIED, fields=[Field("tag", "V", 0, 1, Status.UNVERIFIED)])])


class PhaseTwoDecisionTests(unittest.TestCase):
    """Part A: format / variant / confidence / probe_score."""

    def run_one(self, dec, data=b"V123"):
        p = isolate.process_data("x.v", data, [dec])
        return p["output"], p["entry"]

    def test_variant_and_decoder_confidence(self):
        out, entry = self.run_one(_VariantDecoder())
        self.assertEqual((out["format"], out["variant"], out["confidence"]),
                         ("T-VARIANT", "T-VARIANT 2.1", 0.4))
        self.assertEqual((entry["format"], entry["variant"], entry["confidence"],
                          entry["probe_score"]), ("T-VARIANT", "T-VARIANT 2.1", 0.4, 0.9))
        self.assertEqual(entry["coverage"]["bytes_explained"], 1)
        self.assertEqual(validate.errors("output", out), [])

    def test_same_format_gives_null_variant(self):
        out, entry = self.run_one(_VariantDecoder("T-VARIANT", 1.0))
        self.assertIsNone(out["variant"])
        self.assertEqual((entry["confidence"], entry["probe_score"]), (1.0, 0.9))

    def test_odd_decoder_values_are_sanitised(self):
        for fmt, conf, variant, want in ((None, 1, None, 1.0), ("", 0.0, None, 0.0),
                                         (7, 0.5, None, 0.5)):
            with self.subTest(fmt=fmt):
                out, _ = self.run_one(_VariantDecoder(fmt, conf))
                self.assertEqual((out["variant"], out["confidence"]), (variant, want))
                self.assertIsInstance(out["confidence"], float)

    def test_unknown_uses_probe_score_and_has_coverage(self):
        out, entry = self.run_one(_VariantDecoder(), b"abc")
        self.assertEqual((out["format"], out["variant"], out["confidence"]),
                         ("unknown", None, 0.0))
        self.assertEqual(entry["probe_score"], 0.0)
        self.assertEqual(entry["coverage"]["bytes_explained"], 0)
        self.assertEqual(entry["coverage"]["unexplained"], [[0, 3]])

    def test_failed_uses_probe_score(self):
        class Raising(_VariantDecoder):
            def decode(self, reader):
                raise ValueError("no")

        out, entry = self.run_one(Raising())
        self.assertEqual((out["status"], out["format"], out["confidence"], entry["probe_score"]),
                         ("failed", "T-VARIANT", 0.9, 0.9))
        self.assertIsNone(entry["coverage"])


if __name__ == "__main__":
    unittest.main()
