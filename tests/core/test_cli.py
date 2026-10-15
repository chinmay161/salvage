import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "salvage.cli", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)


class CliTests(unittest.TestCase):
    def test_wrong_argument_counts_exit_0(self):
        for args in ((), ("a",), ("a", "b", "c")):
            with self.subTest(args=args):
                proc = run_cli(*args)
                self.assertEqual(proc.returncode, 0)
                self.assertIn("usage", proc.stderr)
                self.assertEqual(proc.stdout, "")

    def test_help_on_stdout(self):
        for flag in ("-h", "--help"):
            proc = run_cli(flag)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("usage", proc.stdout)

    def test_version(self):
        proc = run_cli("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("salvage "))

    def test_missing_input_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            proc = run_cli(os.path.join(tmp, "missing"), out)
            self.assertEqual(proc.returncode, 0)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
            self.assertEqual(rep["summary"]["files"], 0)
            self.assertTrue(rep["errors"])
            self.assertIn("error:", proc.stderr)
            self.assertEqual(len(proc.stdout.splitlines()), 1)

    def test_output_dir_is_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "file")
            with open(blocker, "wb") as fh:
                fh.write(b"x")
            proc = run_cli(tmp, blocker)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("error:", proc.stderr)
            with open(blocker, "rb") as fh:
                self.assertEqual(fh.read(), b"x")

    def test_one_line_per_file_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "in")
            os.makedirs(inp)
            with open(os.path.join(inp, "x.bin"), "wb") as fh:
                fh.write(b"\x00\x01")
            proc = run_cli(inp, os.path.join(tmp, "out"))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.splitlines(), ["unknown unknown x.bin"])
            self.assertEqual(len(proc.stdout.splitlines()), 1)
            self.assertIn("1 files", proc.stdout)


if __name__ == "__main__":
    unittest.main()
