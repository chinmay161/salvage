import json
import os
import random
import shutil
import struct
import tempfile
import unittest

from salvage.core import pipeline
from salvage.formats.stub import MAGIC

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

EXPECTED_OUTPUT = {rel: rel + ".json" for rel in INPUTS}
EXPECTED_OUTPUT["report"] = "report~2.json"

EXPECTED_STATUS = {
    "clean.stub": "decoded", "truncated.stub": "partial", "empty.bin": "unknown",
    "random.bin": "unknown", "sub/nested.stub": "decoded", "report": "decoded",
    "hang.t": "failed", "raise.t": "failed", "crash.t": "failed", "bad.t": "failed",
    "big.t": "decoded",
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
        cls.report = pipeline.run(cls.inp, cls.out1, decoder_package=PKG, timeout=TIMEOUT)
        pipeline.run(cls.inp, cls.out2, decoder_package=PKG, timeout=TIMEOUT)
        cls.tree1 = _read_tree(cls.out1)
        cls.tree2 = _read_tree(cls.out2)
        cls.entries = {e["input"]: e for e in cls.report["files"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def output(self, rel):
        return json.loads(self.tree1[EXPECTED_OUTPUT[rel]].decode("utf-8"))

    def test_one_output_per_input(self):
        expected = set(EXPECTED_OUTPUT.values()) | {"report.json"}
        self.assertEqual(set(self.tree1), expected)
        for rel, out_rel in EXPECTED_OUTPUT.items():
            self.assertEqual(self.entries[rel]["output"], out_rel)
            self.assertEqual(self.output(rel)["source"]["path"], rel)

    def test_statuses(self):
        got = {rel: e["status"] for rel, e in self.entries.items()}
        self.assertEqual(got, EXPECTED_STATUS)
        for rel, status in EXPECTED_STATUS.items():
            self.assertEqual(self.output(rel)["status"], status, rel)

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
                self.assertEqual((out["format"], out["status"], out["confidence"]),
                                 (fmt, "failed", 1.0))
                self.assertEqual(entry["candidates"][0], {"format": fmt, "score": 1.0})
                self.assertEqual(len(entry["candidates"]), 6)  # every fixture decoder
        self.assertEqual(self.report["summary"]["by_format"]["T-HANG"], 1)

    def test_unknown_still_means_no_candidate(self):
        for rel in ("empty.bin", "random.bin"):
            self.assertEqual(self.entries[rel]["format"], "unknown")
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

    def test_unknown_fallback_meta(self):
        meta = self.output("random.bin")["meta"]
        self.assertEqual(meta["size"], 64 * 1024)
        self.assertGreater(meta["entropy"], 7.9)
        self.assertEqual(len(meta["top_candidates"]), 3)
        self.assertIs(meta["entropy_sampled"], False)
        self.assertEqual(self.output("empty.bin")["meta"]["entropy"], 0.0)

    def test_clean_output_unaffected_by_hostile_files(self):
        inp = os.path.join(self.tmp, "clean-in")
        out = os.path.join(self.tmp, "clean-out")
        _make_tree(inp, {"clean.stub": CLEAN})
        pipeline.run(inp, out, decoder_package=PKG, timeout=TIMEOUT)
        with open(os.path.join(out, "clean.stub.json"), "rb") as fh:
            self.assertEqual(fh.read(), self.tree1["clean.stub.json"])

    def test_summary_matches_files(self):
        s = self.report["summary"]
        self.assertEqual(s["files"], len(INPUTS))
        for status in ("decoded", "partial", "unknown", "failed"):
            self.assertEqual(s[status], list(EXPECTED_STATUS.values()).count(status), status)
        self.assertEqual(s["skipped"], 0)
        self.assertEqual(sum(s["by_format"].values()), len(INPUTS))
        on_disk = json.loads(self.tree1["report.json"].decode("utf-8"))
        self.assertEqual(on_disk, self.report)

    def test_deterministic(self):
        self.assertEqual(self.tree1, self.tree2)

    def test_lf_and_forward_slashes(self):
        for rel, data in self.tree1.items():
            self.assertNotIn(b"\r", data, rel)
            self.assertTrue(data.endswith(b"\n"), rel)
        for e in self.report["files"]:
            self.assertNotIn("\\", e["input"])
            self.assertNotIn("\\", e["output"])
        self.assertEqual(self.entries["sub/nested.stub"]["output"], "sub/nested.stub.json")

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
            rep = pipeline.run(inp, out, decoder_package="tests.fixtures.slowprobe_formats",
                               timeout=TIMEOUT)
            entry = rep["files"][0]
            self.assertEqual((entry["format"], entry["status"], entry["confidence"]),
                             ("unknown", "failed", 0.0))
            self.assertEqual(entry["errors"], [f"timeout after {TIMEOUT}s (during probe)"])
            self.assertEqual(entry["candidates"], [])


class RunErrorTests(unittest.TestCase):
    def test_missing_input_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            rep = pipeline.run(os.path.join(tmp, "nope"), out, decoder_package=PKG)
            self.assertEqual(rep["summary"]["files"], 0)
            self.assertEqual(len(rep["errors"]), 1)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), rep)

    def test_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_tree(tmp, {"a": CLEAN, "a.json": b"precious"})
            rep = pipeline.run(tmp, tmp, decoder_package=PKG, timeout=TIMEOUT)
            with open(os.path.join(tmp, "a.json"), "rb") as fh:
                self.assertEqual(fh.read(), b"precious")
            entry = next(e for e in rep["files"] if e["input"] == "a")
            self.assertIsNone(entry["output"])
            self.assertTrue(entry["errors"])

    def test_too_large_is_failed_without_reading(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            _make_tree(inp, {"big.stub": CLEAN})
            with mock.patch.object(pipeline, "MAX_FILE_BYTES", 10), \
                    mock.patch.object(pipeline.isolate, "run_isolated") as spawn:
                rep = pipeline.run(inp, out, decoder_package=PKG)
            spawn.assert_not_called()
            entry = rep["files"][0]
            self.assertEqual(entry["status"], "failed")
            self.assertIn("too large", entry["errors"][0])
            self.assertEqual(len(entry["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
