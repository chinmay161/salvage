import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from salvagekit.core import isolate, pipeline, report, validate
from salvagekit.core.model import DecodeResult, Field, Record, Status
from salvagekit.core.plugin import Decoder
from salvagekit.formats.stub import MAGIC, StubDecoder

PKG = "tests.fixtures.pipeline_formats"
CLEAN = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)
SHA = "ab" * 32


def report_with(*payloads):
    """A report holding the given payloads' outputs (rows) and entries (diagnostics)."""
    rep = report.new_report()
    for p in payloads:
        rep["files"].append(report.file_row(p["output"]))
        rep["diagnostics"]["files"].append(dict(p["entry"],
                                                output=p["entry"].get("output") or "x.json"))
    report.summarize(rep)
    return rep


class SchemaFileTests(unittest.TestCase):
    def test_official_schemas_are_the_only_schemas(self):
        self.assertEqual(sorted(os.listdir(os.path.join(validate.SCHEMA_DIR, "official"))),
                         ["output.schema.json", "report.schema.json"])
        self.assertEqual(sorted(n for n in os.listdir(validate.SCHEMA_DIR)
                                if n.endswith(".json")), [])   # no provisional fallback
        for kind in validate.KINDS:
            a = validate.active(kind)
            self.assertEqual((a.origin, a.file, a.problems),
                             ("official", f"official/{kind}.schema.json", ()))
            self.assertIsNotNone(a.schema)
        self.assertEqual(validate.load_problems(), [])

    def test_status_enums_match_the_code(self):
        for rel in validate.SCHEMA_FILES.values():
            with open(os.path.join(validate.SCHEMA_DIR, *rel.split("/")),
                      encoding="utf-8") as fh:
                schema = json.load(fh)
            status = schema["properties"].get("status") or schema["$defs"]["status"]
            self.assertEqual(status["enum"], list(report.FILE_STATUSES), rel)

    def output(self, **changes):
        out = {"source_file": "a", "format": "STUB", "status": "partial", "metadata": {},
               "records": [{"value": 1, "verified": False, "issues": ["truncated"]}],
               "damage": [{"kind": "truncated", "offset": 0, "detail": "x", "lossy": True}]}
        out.update(changes)
        return out

    def test_output_contract(self):
        self.assertEqual(validate.errors("output", self.output()), [])
        self.assertEqual(validate.errors("output", self.output(extra=1)),
                         ["$.extra: additional property not allowed"])
        missing = self.output()
        del missing["metadata"]
        self.assertEqual(validate.errors("output", missing),
                         ['$: required property "metadata" is missing'])
        self.assertTrue(validate.errors("output", self.output(status="decoded")))
        self.assertTrue(validate.errors("output", self.output(damage=[
            {"kind": "checksum", "offset": 0, "detail": "x", "lossy": True}])))
        self.assertTrue(validate.errors("output", self.output(damage=[
            {"kind": "truncated", "offset": 0, "detail": "x"}])))   # lossy required
        self.assertTrue(validate.errors("output", self.output(records=[{"issues": ["x"]}])))

    def test_status_rules_in_the_schema(self):
        # unrecognized: format UNKNOWN, nothing decoded.
        self.assertTrue(validate.errors("output", self.output(status="unrecognized")))
        self.assertEqual(validate.errors("output", self.output(
            status="unrecognized", format="UNKNOWN", records=[], damage=[])), [])
        # ok: no damage, no record marked verified false.
        self.assertTrue(validate.errors("output", self.output(status="ok")))
        self.assertTrue(validate.errors("output", self.output(status="ok", damage=[])))
        self.assertEqual(validate.errors("output", self.output(
            status="ok", damage=[], records=[{"value": 1}])), [])


class SchemaLoadTests(unittest.TestCase):
    """A schema that cannot be loaded is a run-level problem; nothing falls back."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="salvage-schemas-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(validate.SCHEMA_DIR, "official"),
                        os.path.join(tmp, "official"))
        self.dir = tmp
        patcher = mock.patch.object(validate, "SCHEMA_DIR", tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        validate.active.cache_clear()
        self.addCleanup(validate.active.cache_clear)

    def test_unsupported_keyword_is_reported(self):
        with open(os.path.join(self.dir, "official", "report.schema.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"type": "object", "if": {}, "then": {}}, fh)
        a = validate.active("report")
        self.assertIsNone(a.schema)
        problems = validate.load_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("official report schema official/report.schema.json not usable",
                      problems[0])
        self.assertIn("#/if: if", problems[0])
        self.assertEqual(validate.errors("report", {"anything": 1}), [])
        self.assertIsNotNone(validate.active("output").schema)


class FailedPayloadTests(unittest.TestCase):
    """Every failed_payload variant validates (output and report)."""

    def variants(self):
        info_cands = {"ranked": [{"format": "STUB", "score": 0.75, "error": None},
                                 {"format": "X", "score": 0.0, "error": "probe raised E: e"}],
                      "candidates": ["STUB"], "warnings": ["ambiguous: STUB, Y"]}
        info_none = {"ranked": [{"format": "STUB", "score": 0.1, "error": None}],
                     "candidates": [], "warnings": []}
        yield "no info, unknown size", isolate.failed_payload("b.bin", None, "cannot read file: x")
        yield "size, no info", isolate.failed_payload("a", 7, "too large (7 bytes > 1)")
        yield "identified", isolate.failed_payload("a", 7, "timeout after 2s (during decode)",
                                                   info_cands)
        yield "no candidate", isolate.failed_payload("a", 0, "crash", info_none)

    def test_all_variants_validate(self):
        for name, payload in self.variants():
            for sha in (None, SHA):
                with self.subTest(variant=name, sha=sha):
                    out, entry = payload["output"], payload["entry"]
                    entry["sha256"] = sha
                    self.assertEqual(validate.errors("output", out), [])
                    self.assertEqual(validate.errors("report", report_with(payload)), [])
                    self.assertEqual((out["status"], out["metadata"], out["records"],
                                      out["damage"]), ("failed", {}, [], []))
                    self.assertIsNone(entry["coverage"])
                    self.assertIsNone(entry["variant"])
                    self.assertEqual(entry["probe_score"], entry["confidence"])

    def test_identified_failure_keeps_format_and_probe_score(self):
        payload = dict(self.variants())["identified"]
        self.assertEqual((payload["output"]["format"], payload["entry"]["format"],
                          payload["entry"]["probe_score"]), ("STUB", "STUB", 0.75))
        self.assertEqual(dict(self.variants())["no candidate"]["output"]["format"], "UNKNOWN")


class CheckedOutputTests(unittest.TestCase):
    def payload(self):
        p = isolate.process_data("a.stub", CLEAN, [StubDecoder()])
        p["entry"]["sha256"] = SHA
        return p

    def test_valid_output_untouched(self):
        p = self.payload()
        out, bug = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertIs(out, p["output"])
        self.assertIsNone(bug)

    def test_invalid_output_replaced(self):
        p = self.payload()
        p["output"]["records"][1]["issues"] = ["melted"]
        p["output"]["damage"].append({"start": 0, "end": 1, "kind": "melted", "reason": "x"})
        out, bug = pipeline.checked_output("a.stub", p["output"], p["entry"])
        self.assertIsNone(bug)
        self.assertEqual(validate.errors("output", out), [])
        self.assertEqual(out, {"source_file": "a.stub", "format": "STUB", "status": "failed",
                               "metadata": {}, "records": [], "damage": []})
        entry = p["entry"]
        self.assertEqual((entry["status"], entry["coverage"], entry["damage"], entry["members"]),
                         ("failed", None, [], 0))
        self.assertTrue(entry["errors"][0].startswith(
            "decoder output failed schema validation ("), entry["errors"])
        self.assertTrue(entry["errors"][1].startswith(
            '$.records[1].issues[0]: "melted" is not one of ["truncated", "crc_mismatch", '),
            entry["errors"])
        self.assertIn('$.damage[0]: required property "offset" is missing', entry["errors"])
        self.assertEqual(validate.errors("report", report_with({"output": out, "entry": entry})),
                         [])

    def test_at_most_10_errors_listed(self):
        p = self.payload()
        # 4 x (3 missing + 1 enum) = 16 errors, + "ok" with damage (the anyOf rule)
        p["output"]["damage"] = [{"kind": "x"}] * 4
        pipeline.checked_output("a.stub", p["output"], p["entry"])
        errors = p["entry"]["errors"]
        self.assertTrue(errors[0].startswith(
            "decoder output failed schema validation (17 errors)"), errors[0])
        self.assertEqual(len(errors), 11)

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
            output["damage"].append({"kind": "truncated", "offset": -1, "detail": "x",
                                     "lossy": True})
            output["surprise"] = 1

        rep, files, err = self.run_with(mutate_output=mutate)
        bad, good = files["bad.stub.json"], files["good.stub.json"]
        self.assertEqual((bad["status"], bad["records"]), ("failed", []))
        self.assertEqual(validate.errors("output", bad), [])
        self.assertEqual((good["status"], len(good["records"])), ("ok", 4))
        entries = {e["input"]: e for e in rep["diagnostics"]["files"]}
        self.assertEqual(entries["bad.stub"]["status"], "failed")
        self.assertEqual(entries["bad.stub"]["errors"][1:3], [
            "$.damage[0].offset: -1 is less than minimum 0",
            "$.surprise: additional property not allowed"])
        # and "ok" with damage breaks the status rule
        self.assertIn("does not match any schema in anyOf", entries["bad.stub"]["errors"][3])
        self.assertEqual(rep["files"][0], {"file": "bad.stub", "format": "STUB",
                                           "status": "failed", "records": 0, "damage": 0})
        self.assertEqual(rep["totals"]["failed"], 1)
        self.assertEqual(rep["diagnostics"]["errors"], [])
        self.assertEqual(validate.errors("report", files["report.json"]), [])
        self.assertEqual(err, "")

    def test_invalid_report_still_written_with_error(self):
        rep, files, err = self.run_with(mutate_entry=lambda e: e.update(extra=1))
        on_disk = files["report.json"]
        errors = on_disk["diagnostics"]["errors"]
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith(
            "report.json fails schema validation (1 errors); first: "
            "$.diagnostics.files[0].extra: additional property not allowed"), errors)
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


class IdentificationTests(unittest.TestCase):
    """format (output), variant / confidence / probe_score (diagnostics)."""

    def run_one(self, dec, data=b"V123"):
        p = isolate.process_data("x.v", data, [dec])
        return p["output"], p["entry"]

    def test_variant_and_decoder_confidence(self):
        out, entry = self.run_one(_VariantDecoder())
        self.assertEqual(out["format"], "T-VARIANT")
        self.assertEqual((entry["format"], entry["variant"], entry["confidence"],
                          entry["probe_score"]), ("T-VARIANT", "T-VARIANT 2.1", 0.4, 0.9))
        self.assertEqual(entry["coverage"]["bytes_explained"], 1)
        self.assertEqual(validate.errors("output", out), [])

    def test_same_format_gives_null_variant(self):
        _, entry = self.run_one(_VariantDecoder("T-VARIANT", 1.0))
        self.assertIsNone(entry["variant"])
        self.assertEqual((entry["confidence"], entry["probe_score"]), (1.0, 0.9))

    def test_odd_decoder_values_are_sanitised(self):
        for fmt, conf, want in ((None, 1, 1.0), ("", 0.0, 0.0), (7, 0.5, 0.5)):
            with self.subTest(fmt=fmt):
                _, entry = self.run_one(_VariantDecoder(fmt, conf))
                self.assertEqual((entry["variant"], entry["confidence"]), (None, want))
                self.assertIsInstance(entry["confidence"], float)

    def test_unrecognized_uses_probe_score_and_has_coverage(self):
        out, entry = self.run_one(_VariantDecoder(), b"abc")
        self.assertEqual((out["format"], out["status"]), ("UNKNOWN", "unrecognized"))
        self.assertEqual((entry["variant"], entry["confidence"], entry["probe_score"]),
                         (None, 0.0, 0.0))
        self.assertEqual(entry["coverage"]["bytes_explained"], 0)
        self.assertEqual(entry["coverage"]["unexplained"], [[0, 3]])

    def test_failed_uses_probe_score(self):
        class Raising(_VariantDecoder):
            def decode(self, reader):
                raise ValueError("no")

        out, entry = self.run_one(Raising())
        self.assertEqual((out["status"], out["format"], entry["confidence"],
                          entry["probe_score"]), ("failed", "T-VARIANT", 0.9, 0.9))
        self.assertIsNone(entry["coverage"])


if __name__ == "__main__":
    unittest.main()
