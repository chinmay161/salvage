import hashlib
import json
import os
import random
import shutil
import struct
import tempfile
import unittest

from salvagekit.core import pipeline, report, validate
from tests.pipeline_helpers import run_checked
from salvagekit.formats.stub import MAGIC

PKG = "tests.fixtures.pipeline_formats"
TIMEOUT = 2

CLEAN = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)
TRUNCATED = MAGIC + struct.pack("<H2I", 5, 1, 2)

INPUTS = {
    "clean.stub": CLEAN,
    "truncated.stub": TRUNCATED,
    "empty.bin": b"",
    "random.bin": random.Random(1234).randbytes(64 * 1024),
    "sub/nested.stub": CLEAN,
    "report": CLEAN,
    "hang.t": b"T-HANG payload",
    "raise.t": b"T-RAISE payload",
    "crash.t": b"T-CRASH payload",
    "bad.t": b"T-BAD payload",
    "big.t": b"T-BIG payload",
}

# Non-recursive (C1): "sub/" is skipped, so "sub/nested.stub" gets no output.
EXPECTED_OUTPUT = {rel: rel + ".json" for rel in INPUTS if "/" not in rel}
EXPECTED_OUTPUT["report"] = "report~2.json"

EXPECTED_STATUS = {
    "clean.stub": "ok", "truncated.stub": "partial", "empty.bin": "unrecognized",
    "random.bin": "unrecognized", "report": "ok",
    "hang.t": "failed", "raise.t": "failed", "crash.t": "failed", "bad.t": "failed",
    "big.t": "partial",   # 40,000 UNVERIFIED records
}


def _make_tree(root, files):
    for rel, data in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def _read_tree(root):
    out = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, "rb") as fh:
                out[rel] = fh.read()
    return out


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="salvage-pipe-")
        cls.inp = os.path.join(cls.tmp, "in")
        _make_tree(cls.inp, INPUTS)
        cls.out1 = os.path.join(cls.tmp, "out1")
        cls.out2 = os.path.join(cls.tmp, "out2")
        # out1 sequential, out2 with 4 workers: test_deterministic proves they are
        # byte-identical (B7), hang/crash/raise fixtures included.
        cls.report = run_checked(cls.inp, cls.out1, decoder_package=PKG, timeout=TIMEOUT, jobs=1)
        run_checked(cls.inp, cls.out2, decoder_package=PKG, timeout=TIMEOUT, jobs=4)
        cls.tree1 = _read_tree(cls.out1)
        cls.tree2 = _read_tree(cls.out2)
        cls.entries = {e["input"]: e for e in cls.report["diagnostics"]["files"]}
        cls.rows = {r["file"]: r for r in cls.report["files"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def output(self, rel):
        return json.loads(self.tree1[EXPECTED_OUTPUT[rel]].decode("utf-8"))

    def test_one_output_per_top_level_input(self):
        expected = set(EXPECTED_OUTPUT.values()) | {"report.json"}
        self.assertEqual(set(self.tree1), expected)
        for rel, out_rel in EXPECTED_OUTPUT.items():
            self.assertEqual(self.entries[rel]["output"], out_rel)
            self.assertEqual(self.output(rel)["source_file"], rel)

    def test_subfolder_skipped_not_entered(self):
        self.assertNotIn("sub/nested.stub", self.entries)
        self.assertEqual(self.report["diagnostics"]["skipped"],
                         [{"input": "sub",
                           "reason": "directory (not entered: the walk is non-recursive)"}])
        self.assertEqual(self.report["diagnostics"]["summary"]["skipped"], 1)

    def test_statuses(self):
        got = {rel: e["status"] for rel, e in self.entries.items()}
        self.assertEqual(got, EXPECTED_STATUS)
        for rel, status in EXPECTED_STATUS.items():
            self.assertEqual(self.output(rel)["status"], status, rel)
            self.assertEqual(self.rows[rel]["status"], status, rel)

    def test_output_keys_exactly_the_contract(self):
        for rel in EXPECTED_OUTPUT:
            self.assertEqual(list(self.output(rel)), ["source_file", "format", "status",
                                                      "metadata", "records", "damage"], rel)

    def test_contract_records_and_damage(self):
        clean = self.output("clean.stub")
        self.assertEqual(clean["records"], [
            {"magic": MAGIC.hex(), "count": 3}, {"value": 10}, {"value": 20}, {"value": 30}])
        self.assertEqual(clean["damage"], [])
        trunc = self.output("truncated.stub")
        self.assertEqual(trunc["records"][0]["issues"], ["truncated"])
        self.assertEqual(trunc["records"][1], {"value": 1, "verified": False})
        self.assertEqual(trunc["damage"], [{"kind": "truncated", "offset": 23,
                                            "detail": "expected 5 values, file ends after 2",
                                            "lossy": True}])
        for rel in ("empty.bin", "random.bin", "hang.t", "bad.t"):
            out = self.output(rel)
            self.assertEqual((out["metadata"], out["records"], out["damage"]), ({}, [], []), rel)

    def test_report_rows_match_outputs(self):
        self.assertEqual(list(self.report), ["tool_version", "files", "totals", "diagnostics"])
        self.assertEqual([r["file"] for r in self.report["files"]], sorted(EXPECTED_OUTPUT))
        for rel in EXPECTED_OUTPUT:
            out, row = self.output(rel), self.rows[rel]
            self.assertEqual(row, {"file": rel, "format": out["format"],
                                   "status": out["status"], "records": len(out["records"]),
                                   "damage": len(out["damage"])})

    def test_hang_times_out(self):
        self.assertEqual(self.entries["hang.t"]["errors"],
                         [f"timeout after {TIMEOUT}s (during decode)"])

    def test_crash_reported(self):
        errors = self.entries["crash.t"]["errors"]
        self.assertEqual(errors, ["worker crashed with exit code 3 (during decode)"])

    def test_failed_files_keep_identification(self):
        # A2: format = identification, status = decoding outcome.
        for rel, fmt in (("hang.t", "T-HANG"), ("crash.t", "T-CRASH"),
                         ("raise.t", "T-RAISE"), ("bad.t", "T-BAD")):
            with self.subTest(rel=rel):
                entry, out = self.entries[rel], self.output(rel)
                self.assertEqual((entry["format"], entry["status"], entry["confidence"]),
                                 (fmt, "failed", 1.0))
                self.assertEqual((out["format"], out["status"]), (fmt, "failed"))
                self.assertEqual(entry["candidates"][0], {"format": fmt, "score": 1.0})
                self.assertEqual(len(entry["candidates"]), 6)  # every fixture decoder
        self.assertEqual(self.report["diagnostics"]["summary"]["by_format"]["T-HANG"], 1)

    def test_unrecognized_means_no_candidate(self):
        for rel in ("empty.bin", "random.bin"):
            self.assertEqual(self.entries[rel]["format"], "UNKNOWN")
            self.assertEqual(self.output(rel)["format"], "UNKNOWN")
            self.assertEqual(self.entries[rel]["confidence"], 0.0)

    def test_raise_and_badres_attempts_recorded(self):
        raised = self.entries["raise.t"]["attempts"]
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0]["format"], "T-RAISE")
        self.assertTrue(raised[0]["outcome"].startswith("error: ValueError"), raised)
        bad = self.entries["bad.t"]["attempts"]
        self.assertEqual(bad[0]["format"], "T-BAD")
        self.assertTrue(bad[0]["outcome"].startswith("invalid: "), bad)
        self.assertEqual(self.output("bad.t")["records"], [])  # invalid is never emitted

    def test_bigout_completes(self):
        out = self.output("big.t")
        self.assertEqual(len(out["records"]), 40_000)
        self.assertEqual(self.entries["big.t"]["records_by_status"]["unverified"], 40_000)

    def test_unrecognized_byte_facts_go_to_diagnostics(self):
        facts = self.entries["random.bin"]["bytes"]
        self.assertEqual(facts["size"], 64 * 1024)
        self.assertGreater(facts["entropy"], 7.9)
        self.assertEqual(len(facts["top_candidates"]), 3)
        self.assertIs(facts["entropy_sampled"], False)
        self.assertEqual(self.entries["empty.bin"]["bytes"]["entropy"], 0.0)
        self.assertEqual(self.output("random.bin")["metadata"], {})
        self.assertIsNone(self.entries["clean.stub"]["bytes"])

    def test_clean_output_unaffected_by_hostile_files(self):
        inp = os.path.join(self.tmp, "clean-in")
        out = os.path.join(self.tmp, "clean-out")
        _make_tree(inp, {"clean.stub": CLEAN})
        run_checked(inp, out, decoder_package=PKG, timeout=TIMEOUT, jobs=2)
        with open(os.path.join(out, "clean.stub.json"), "rb") as fh:
            self.assertEqual(fh.read(), self.tree1["clean.stub.json"])

    def test_totals_match_files(self):
        totals = self.report["totals"]
        self.assertEqual(list(totals), list(report.FILE_STATUSES))   # zeros included
        for status in report.FILE_STATUSES:
            self.assertEqual(totals[status], list(EXPECTED_STATUS.values()).count(status), status)
        self.assertEqual(totals["unsupported"], 0)
        s = self.report["diagnostics"]["summary"]
        self.assertEqual(s["files"], len(EXPECTED_STATUS))
        self.assertEqual(sum(s["by_format"].values()), len(EXPECTED_STATUS))
        on_disk = json.loads(self.tree1["report.json"].decode("utf-8"))
        self.assertEqual(on_disk, self.report)

    def test_every_output_validates(self):
        for rel, data in sorted(self.tree1.items()):
            with self.subTest(output=rel):
                kind = "report" if rel == "report.json" else "output"
                doc = json.loads(data.decode("utf-8"))
                self.assertEqual(validate.errors(kind, doc), [])

    def test_identification_fields(self):
        # Part A: variant null (STUB reports its own name), confidence from the
        # decoder for decoded/partial, probe score otherwise.
        for rel, e in self.entries.items():
            with self.subTest(rel=rel):
                self.assertIsNone(e["variant"])
        self.assertEqual((self.entries["clean.stub"]["confidence"],
                          self.entries["clean.stub"]["probe_score"]), (1.0, 1.0))
        self.assertEqual(self.entries["random.bin"]["probe_score"], 0.0)
        self.assertEqual(self.entries["hang.t"]["probe_score"], 1.0)

    def test_coverage(self):
        clean = self.entries["clean.stub"]["coverage"]
        self.assertEqual((clean["bytes_total"], clean["explained_pct"], clean["unexplained"]),
                         (len(CLEAN), 100.0, []))
        trunc = self.entries["truncated.stub"]["coverage"]
        self.assertEqual(trunc["unexplained"], [])         # 2 values read completely
        self.assertEqual(self.entries["random.bin"]["coverage"]["unexplained"],
                         [[0, 64 * 1024]])
        self.assertIsNone(self.entries["empty.bin"]["coverage"]["explained_pct"])
        for rel in ("hang.t", "crash.t", "raise.t", "bad.t"):
            self.assertIsNone(self.entries[rel]["coverage"], rel)
        self.assertEqual(self.entries["big.t"]["coverage"]["bytes_explained"], 0)

    def test_deterministic_and_jobs_1_vs_4_byte_identical(self):
        self.assertEqual(sorted(self.tree1), sorted(self.tree2))
        for rel in self.tree1:
            self.assertEqual(self.tree1[rel], self.tree2[rel], rel)

    def test_lf_and_forward_slashes(self):
        for rel, data in self.tree1.items():
            self.assertNotIn(b"\r", data, rel)
            self.assertTrue(data.endswith(b"\n"), rel)
        for e in self.entries.values():
            self.assertNotIn("\\", e["input"])
            self.assertNotIn("\\", e["output"])

    def test_no_absolute_paths(self):
        needles = {os.path.basename(self.tmp).encode()}
        for base in (self.tmp, os.path.realpath(self.tmp)):
            needles.add(base.encode())
            needles.add(base.replace("\\", "/").encode())
            needles.add(json.dumps(base).strip('"').encode())
        for rel, data in self.tree1.items():
            for needle in needles:
                self.assertNotIn(needle, data, rel)


class SlowProbeTests(unittest.TestCase):
    def test_timeout_during_probe_is_unknown_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            _make_tree(inp, {"x.bin": b"anything"})
            rep = run_checked(inp, out, decoder_package="tests.fixtures.slowprobe_formats", jobs=1,
                               timeout=TIMEOUT)
            entry = rep["diagnostics"]["files"][0]
            self.assertEqual((entry["format"], entry["status"], entry["confidence"]),
                             ("UNKNOWN", "failed", 0.0))
            self.assertEqual(rep["files"][0]["format"], "UNKNOWN")
            self.assertEqual(entry["errors"], [f"timeout after {TIMEOUT}s (during probe)"])
            self.assertEqual(entry["candidates"], [])


class RunErrorTests(unittest.TestCase):
    def test_missing_input_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            rep = run_checked(os.path.join(tmp, "nope"), out, decoder_package=PKG, jobs=1)
            self.assertEqual(rep["files"], [])
            self.assertEqual(rep["totals"], dict.fromkeys(report.FILE_STATUSES, 0))
            self.assertEqual(len(rep["diagnostics"]["errors"]), 1)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), rep)

    def test_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_tree(tmp, {"a": CLEAN, "a.json": b"precious"})
            rep = run_checked(tmp, tmp, decoder_package=PKG, timeout=TIMEOUT, jobs=1)
            with open(os.path.join(tmp, "a.json"), "rb") as fh:
                self.assertEqual(fh.read(), b"precious")
            entry = next(e for e in rep["diagnostics"]["files"] if e["input"] == "a")
            self.assertIsNone(entry["output"])
            self.assertTrue(entry["errors"])

    def test_report_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_tree(tmp, {"report.json": b"precious", "a": CLEAN})
            rep = run_checked(tmp, tmp, decoder_package=PKG, timeout=TIMEOUT, jobs=1)
            with open(os.path.join(tmp, "report.json"), "rb") as fh:
                self.assertEqual(fh.read(), b"precious")
            self.assertIn("cannot write report: refusing to overwrite an input file",
                          rep["diagnostics"]["errors"])
            self.assertTrue(os.path.isfile(os.path.join(tmp, "report.json.json")))

    def test_too_large_is_hashed_but_never_decoded(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            _make_tree(inp, {"big.stub": CLEAN})
            with mock.patch.object(pipeline, "MAX_FILE_BYTES", 10), \
                    mock.patch.object(pipeline.isolate, "Worker") as spawn, \
                    mock.patch.object(pipeline, "sha256_file",
                                      wraps=pipeline.sha256_file) as sha:
                rep = run_checked(inp, out, decoder_package=PKG, jobs=1)
            spawn.assert_not_called()  # never decoded
            sha.assert_called_once()   # but hashed (streamed)
            entry = rep["diagnostics"]["files"][0]
            self.assertEqual(entry["status"], "failed")
            self.assertIn("too large", entry["errors"][0])
            self.assertEqual(entry["sha256"], hashlib.sha256(CLEAN).hexdigest())
            with open(os.path.join(out, "big.stub.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {
                    "source_file": "big.stub", "format": "UNKNOWN", "status": "failed",
                    "metadata": {}, "records": [], "damage": []})

    def test_sha256_file_streams_in_1_mib_chunks(self):
        from unittest import mock
        data = bytes(range(256)) * (3 * 4096 + 1)   # 3 MiB + 256 bytes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.bin")
            with open(path, "wb") as fh:
                fh.write(data)
            sizes: list[int] = []
            real_read = os.read

            def spy(fd, n):
                sizes.append(n)
                return real_read(fd, n)

            with mock.patch.object(pipeline.os, "read", spy):
                digest = pipeline.sha256_file(path)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertEqual(set(sizes), {1 << 20})
        self.assertEqual(len(sizes), 5)   # 4 chunks, then the empty read at EOF


class OverwriteGuardTests(unittest.TestCase):
    def test_folders_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "ab")
            inner = os.path.join(a, "x", "y")
            for d in (b, inner):
                os.makedirs(d)
            self.assertTrue(pipeline.folders_overlap(a, a))
            self.assertTrue(pipeline.folders_overlap(a, os.path.join(a, "x", "..")))
            self.assertTrue(pipeline.folders_overlap(a, inner))
            self.assertTrue(pipeline.folders_overlap(inner, a))
            self.assertFalse(pipeline.folders_overlap(a, b))   # "ab" is not inside "a"
            self.assertFalse(pipeline.folders_overlap(b, a))
            self.assertFalse(pipeline.folders_overlap(os.path.join(tmp, "missing"), a))

    def test_input_inside_output_is_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Output root <tmp>, input <tmp>/in: the folders overlap, so every
            # target is checked; the nested input folder itself is skipped.
            inp = os.path.join(tmp, "in")
            _make_tree(inp, {"a": CLEAN, "a.json": b"precious", "in/b": CLEAN})
            rep = run_checked(inp, tmp, decoder_package=PKG, timeout=TIMEOUT, jobs=1)
            with open(os.path.join(inp, "a.json"), "rb") as fh:
                self.assertEqual(fh.read(), b"precious")
            self.assertEqual([r["file"] for r in rep["files"]], ["a", "a.json"])
            self.assertEqual(rep["diagnostics"]["skipped"][0]["input"], "in")
            self.assertTrue(os.path.isfile(os.path.join(tmp, "a.json")))

    def test_disjoint_folders_skip_the_per_file_check(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            _make_tree(inp, {f"f{i}.stub": CLEAN for i in range(5)})
            with mock.patch.object(pipeline, "_key", wraps=pipeline._key) as key:
                rep = run_checked(inp, out, decoder_package=PKG, timeout=TIMEOUT, jobs=1)
            self.assertEqual(key.call_count, 2)   # the two folders, resolved once
            self.assertEqual([r["status"] for r in rep["files"]], ["ok"] * 5)
            self.assertTrue(all(e["output"] for e in rep["diagnostics"]["files"]))


if __name__ == "__main__":
    unittest.main()
