"""Phase 5 hardening: limit overrides, memory cap, stubborn workers, interrupts,
console encoding and file-system edge cases (docs/phase-reports/phase-5.md, B1-B6).

POSIX-only behaviour (memory cap, SIGTERM) is skipped on Windows with a
reason; ``python tools/task.py docker-test`` runs it on Linux.
"""

import hashlib
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from salvage.core import isolate, pipeline, validate, walk
from salvage.formats.stub import MAGIC
from tests.pipeline_helpers import run_checked

ROOT = Path(__file__).resolve().parents[2]
HOSTILE = "tests.fixtures.hostile_formats"
POSIX = os.name == "posix"
HAS_RESOURCE = sys.platform != "win32"

CLEAN = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)


def make_tree(root, files):
    for rel, data in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def env(**extra):
    e = dict(os.environ)
    e["PYTHONPATH"] = str(ROOT) + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e.pop("SALVAGE_LIMITS", None)
    e.update(extra)
    return e


def load_report(out):
    with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
        return json.load(fh)


def json_outputs(out):
    found = set()
    for dirpath, _, names in os.walk(out):
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), out).replace(os.sep, "/")
            if rel != "report.json":
                found.add(rel)
    return found


# -- B1 ------------------------------------------------------------------------

class LimitOverrideTests(unittest.TestCase):
    def limits(self, value, code="print(l.MAX_FILE_BYTES, l.MAX_RECORDS)"):
        return subprocess.run(
            [sys.executable, "-c", f"import salvage.core.limits as l; {code}"],
            cwd=ROOT, env=env(SALVAGE_LIMITS=value), capture_output=True, text=True,
            timeout=60)

    def test_override_applies(self):
        proc = self.limits('{"MAX_FILE_BYTES": 1048576, "MAX_RECORDS": 7}')
        self.assertEqual((proc.stdout.split(), proc.stderr), (["1048576", "7"], ""))

    def test_bad_json_and_unknown_keys_are_ignored_with_one_line(self):
        for raw, why in (("{bad", "not valid JSON"), ("[1]", "not a JSON object"),
                         ('{"NOPE": 1, "MAX_RECORDS": "x", "MAX_FILE_BYTES": 5}',
                          "bad value for MAX_RECORDS; unknown key NOPE")):
            with self.subTest(raw=raw):
                proc = self.limits(raw)
                self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
                self.assertIn(why, proc.stderr)
                self.assertIn("SALVAGE_LIMITS", proc.stderr)
        self.assertEqual(proc.stdout.split()[0], "5")  # the good key still applies

    def test_isolated_workers_see_the_override(self):
        # MAX_RECORDS is enforced inside the worker (caps.enforce), so the
        # warning proves the worker read the same limits as the parent.
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            make_tree(inp, {"a.stub": MAGIC + struct.pack("<H5I", 5, 1, 2, 3, 4, 5)})
            proc = subprocess.run([sys.executable, "-m", "salvage.cli", "--jobs", "1", inp, out],
                                  cwd=ROOT, env=env(SALVAGE_LIMITS='{"MAX_RECORDS": 2}'),
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0)
            entry = load_report(out)["files"][0]
            self.assertEqual(entry["status"], "partial")
            self.assertIn("output capped at 2 records", entry["warnings"])


# -- B2 ------------------------------------------------------------------------

class MemoryCapTests(unittest.TestCase):
    @unittest.skipUnless(HAS_RESOURCE, "no memory cap on Windows (no resource module)")
    def test_memory_hog_fails_and_next_file_decodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            make_tree(inp, {"a.t": b"T-MEMHOG payload", "b.stub": CLEAN})
            rep = run_checked(inp, out, decoder_package=HOSTILE, timeout=60, jobs=1)
            hog, after = rep["files"]
            self.assertEqual((hog["status"], hog["format"]), ("failed", "T-MEMHOG"))
            self.assertEqual(hog["errors"], ["memory limit (2048 MiB)"])
            self.assertEqual(hog["attempts"], [{"format": "T-MEMHOG",
                                                "outcome": "error: memory limit"}])
            self.assertEqual(after["status"], "decoded")

    def test_memory_error_outcome_in_process(self):
        # Any OS: a MemoryError from decode is "error: memory limit", and with
        # no cap in this process the file reason says so honestly.
        from tests.fixtures.hostile_formats.memhog import MemHogDecoder

        class Small(MemHogDecoder):
            def decode(self, reader):
                raise MemoryError()

        payload = isolate.process_data("a.t", b"T-MEMHOG x", [Small()])
        self.assertEqual(payload["entry"]["attempts"][0]["outcome"], "error: memory limit")
        self.assertEqual(payload["entry"]["errors"],
                         ["out of memory (no memory cap in this process)"])

    def test_cap_memory_is_a_no_op_without_resource(self):
        with mock.patch.dict(sys.modules, {"resource": None}):
            self.assertIsNone(isolate.cap_memory())


# -- B3 ------------------------------------------------------------------------

class StubbornWorkerTests(unittest.TestCase):
    def test_sigterm_ignoring_worker_is_killed_and_reported_as_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            make_tree(inp, {"a.t": b"T-STUBBORN payload", "b.stub": CLEAN})
            start = time.monotonic()
            rep = run_checked(inp, out, decoder_package=HOSTILE, timeout=1, jobs=2)
            took = time.monotonic() - start
            stubborn, other = rep["files"]
            self.assertEqual(stubborn["errors"], ["timeout after 1s (during decode)"])
            self.assertEqual(stubborn["status"], "failed")
            self.assertEqual(other["status"], "decoded")
            # deadline 1 s + SIGTERM grace 2 s, then SIGKILL; never a hang
            self.assertLess(took, 30)


# -- B4 ------------------------------------------------------------------------

@unittest.skipUnless(POSIX, "SIGTERM delivery to a running CLI is tested on POSIX only")
class InterruptTests(unittest.TestCase):
    def test_sigterm_mid_run_writes_report_and_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            total = 12
            make_tree(inp, {f"f{i:02d}.t": b"T-SLOW payload" for i in range(total)})
            proc = subprocess.Popen(
                [sys.executable, "-m", "tests.fixtures.cli_with_package", HOSTILE,
                 "--jobs", "2", inp, out],
                cwd=ROOT, env=env(PYTHONUNBUFFERED="1"), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            try:
                first = proc.stderr.readline()       # one file finished: partway through
                self.assertTrue(first.startswith(b"decoded T-SLOW"), first)
                proc.send_signal(signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=30)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            self.assertEqual(proc.returncode, 0, stderr)
            rep = load_report(out)
            self.assertEqual(validate.errors("report", rep), [])
            done = len(rep["files"])
            self.assertTrue(1 <= done < total, done)
            self.assertEqual(rep["errors"], [f"interrupted: {total - done} files not processed"])
            # Only finished files have an output; nothing is invented for the rest.
            self.assertEqual(json_outputs(out), {e["output"] for e in rep["files"]})
            self.assertTrue(all(e["status"] == "decoded" for e in rep["files"]))
            self.assertIn(b"salvage: ", stdout)


class InProcessInterruptTests(unittest.TestCase):
    """Any OS: the stop logic itself, with SIGTERM raised inside the run."""

    def test_signal_after_first_file_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            make_tree(inp, {f"f{i}.t": b"T-SLOW payload" for i in range(6)})
            seen = []

            def progress(entry):
                seen.append(entry["input"])
                if len(seen) == 1:
                    signal.raise_signal(signal.SIGTERM)
            before = signal.getsignal(signal.SIGTERM)
            rep = run_checked(inp, out, decoder_package=HOSTILE, jobs=2, progress=progress)
            self.assertIs(signal.getsignal(signal.SIGTERM), before)   # handler restored
            done = len(rep["files"])
            self.assertTrue(1 <= done < 6, done)
            self.assertEqual(rep["errors"], [f"interrupted: {6 - done} files not processed"])
            self.assertEqual(json_outputs(out), {e["output"] for e in rep["files"]})
            self.assertEqual(load_report(out), rep)


# -- B5 ------------------------------------------------------------------------

class ConsoleEncodingTests(unittest.TestCase):
    def test_unencodable_names_on_an_ascii_console(self):
        names = ["café.stub", "नमस्ते.stub", "😀 smile.bin"]
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            make_tree(inp, {n: CLEAN for n in names})
            proc = subprocess.run([sys.executable, "-m", "salvage.cli", "--jobs", "1", inp, out],
                                  cwd=ROOT, env=env(PYTHONIOENCODING="ascii"),
                                  capture_output=True, timeout=60)
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn(b"Traceback", proc.stderr)
            self.assertNotIn(b"internal error", proc.stderr)
            lines = proc.stderr.decode("ascii").splitlines()
            self.assertEqual(len(lines), 3, lines)
            self.assertTrue(all("?" in line for line in lines), lines)
            self.assertIn(b"3 files", proc.stdout)
            rep = load_report(out)
            self.assertEqual(sorted(e["input"] for e in rep["files"]), sorted(names))


# -- B6 ------------------------------------------------------------------------

class FileSystemEdgeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="salvage-fs-")
        self.tmp = self._tmp.name
        self.inp, self.out = os.path.join(self.tmp, "in"), os.path.join(self.tmp, "out")

    def tearDown(self):
        self._tmp.cleanup()

    def run_stub(self, **kw):
        return run_checked(self.inp, self.out, decoder_package=HOSTILE, timeout=20,
                           jobs=kw.pop("jobs", 2), **kw)

    def test_spaces_emoji_and_devanagari_names(self):
        names = ["with space.stub", "sub dir/😀.stub", "हिन्दी/फ़ाइल.stub"]
        make_tree(self.inp, {n: CLEAN for n in names})
        rep = self.run_stub()
        self.assertEqual([e["input"] for e in rep["files"]], names)   # walk order
        for e in rep["files"]:
            self.assertEqual((e["status"], e["output"]), ("decoded", e["input"] + ".json"))
            with open(os.path.join(self.out, *e["output"].split("/")), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["source"]["path"], e["input"])

    def test_names_differing_only_by_case(self):
        make_tree(self.inp, {"A.stub": CLEAN})
        try:
            with open(os.path.join(self.inp, "a.stub"), "xb") as fh:
                fh.write(CLEAN + b"\x00")
        except FileExistsError:
            self.skipTest("case-insensitive file system: cannot create A.stub and a.stub")
        rep = self.run_stub()
        self.assertEqual([(e["input"], e["output"]) for e in rep["files"]],
                         [("A.stub", "A.stub.json"), ("a.stub", "a.stub~2.json")])
        self.assertEqual(json_outputs(self.out), {"A.stub.json", "a.stub~2.json"})

    def test_tree_60_levels_deep(self):
        # One-letter folder names keep the path short enough for Windows'
        # 260-character limit when the temp folder is not too deep.
        rel = "/".join("d" * 60) + "/deep.stub"
        try:
            make_tree(self.inp, {rel: CLEAN})
        except OSError as exc:
            self.skipTest(f"path length limit hit creating a 60-level tree "
                          f"({len(self.inp) + len(rel)} chars): {exc.strerror or exc}")
        rep = self.run_stub()
        entry = rep["files"][0]
        self.assertEqual(entry["input"], rel)
        if entry["output"] is None:
            # Windows without long paths: recorded honestly, never a crash.
            self.assertTrue(entry["errors"][-1].startswith("cannot write output"), entry)
            self.skipTest("path length limit hit writing the output: "
                          + entry["errors"][-1])
        self.assertEqual((entry["status"], entry["output"]), ("decoded", rel + ".json"))

    def test_file_deleted_between_walk_and_read(self):
        make_tree(self.inp, {"a.stub": CLEAN, "gone.stub": CLEAN})
        real = walk.list_inputs

        def list_then_delete(*args, **kw):
            found = real(*args, **kw)
            os.remove(os.path.join(self.inp, "gone.stub"))
            return found
        with mock.patch.object(pipeline.walk, "list_inputs", list_then_delete):
            rep = self.run_stub()
        a, gone = rep["files"]
        self.assertEqual(a["status"], "decoded")
        self.assertEqual((gone["status"], gone["errors"]), ("failed", ["file disappeared"]))
        self.assertIsNone(gone["sha256"])

    def test_file_deleted_before_the_worker_reads_it(self):
        payload = isolate.process_file(os.path.join(self.tmp, "missing.stub"), "missing.stub",
                                       HOSTILE)
        self.assertEqual(payload["entry"]["errors"], ["file disappeared"])

    def test_output_path_is_an_existing_folder(self):
        make_tree(self.inp, {"a.stub": CLEAN, "b.stub": CLEAN})
        os.makedirs(os.path.join(self.out, "a.stub.json", "keep"))
        rep = self.run_stub()
        a, b = rep["files"]
        self.assertIsNone(a["output"])
        self.assertEqual(a["errors"], ["cannot write output: output path is an existing folder"])
        self.assertEqual(b["output"], "b.stub.json")
        self.assertTrue(os.path.isdir(os.path.join(self.out, "a.stub.json", "keep")))
        self.assertEqual(load_report(self.out), rep)

    def test_output_dir_not_empty(self):
        make_tree(self.inp, {"a.stub": CLEAN})
        make_tree(self.out, {"old.txt": b"keep me", "sub/older.bin": b"x",
                             "a.stub.json": b"stale"})
        rep = self.run_stub()
        self.assertEqual(rep["warnings"], ["output dir was not empty: 3 existing files"])
        with open(os.path.join(self.out, "old.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"keep me")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "sub", "older.bin")))
        with open(os.path.join(self.out, "a.stub.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["status"], "decoded")   # ours: overwritten
        self.assertEqual(validate.errors("report", load_report(self.out)), [])
        # A fresh output dir gets no warning.
        fresh = run_checked(self.inp, os.path.join(self.tmp, "fresh"),
                            decoder_package=HOSTILE, jobs=1)
        self.assertEqual(fresh["warnings"], [])

    def test_too_large_via_salvage_limits_is_hashed_never_decoded(self):
        make_tree(self.inp, {"big.bin": b"\x00" * (2 * 1024 * 1024), "small.stub": CLEAN})
        script = (
            "import json, sys\n"
            "from salvage import cli\n"
            "from salvage.core import isolate, pipeline\n"
            "seen = []\n"
            "real_sha, real_worker = pipeline.sha256_file, isolate.Worker\n"
            "def sha(path):\n"
            "    seen.append(path); return real_sha(path)\n"
            "def worker(path, *a, **kw):\n"
            "    seen.append(path); return real_worker(path, *a, **kw)\n"
            "pipeline.sha256_file, isolate.Worker = sha, worker\n"
            "if __name__ == '__main__':\n"
            "    cli.main(['--jobs', '1', sys.argv[1], sys.argv[2]])\n"
            "    print(json.dumps(seen))\n")
        proc = subprocess.run([sys.executable, "-c", script, self.inp, self.out], cwd=ROOT,
                              env=env(SALVAGE_LIMITS='{"MAX_FILE_BYTES": 1048576}'),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seen = json.loads(proc.stdout.splitlines()[-1])
        # big.bin is hashed (streamed) but never given to a worker.
        self.assertEqual([os.path.basename(p) for p in seen],
                         ["big.bin", "small.stub", "small.stub"])
        big, small = load_report(self.out)["files"]
        self.assertEqual((big["status"], big["sha256"]),
                         ("failed", hashlib.sha256(bytes(2 * 1024 * 1024)).hexdigest()))
        self.assertEqual(big["errors"], ["too large (2097152 bytes > 1048576)"])
        self.assertEqual(small["status"], "decoded")


if __name__ == "__main__":
    unittest.main()
