"""tools/task.py helpers that need no Docker: the Dockerfile lint and check-outputs."""

import importlib.util
import io
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("salvage_task", ROOT / "tools" / "task.py")
task = importlib.util.module_from_spec(_spec)
sys.modules["salvage_task"] = task
_spec.loader.exec_module(task)

PINNED = "FROM python:3.12-slim@sha256:" + "a" * 64 + "\n"


class LintDockerTests(unittest.TestCase):
    def test_repo_dockerfile_passes(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertEqual(task.lint_dockerfile(text), [])
        self.assertRegex(task.base_image(), r"^python:3\.12-slim@sha256:[0-9a-f]{64}$")

    def test_unpinned_from(self):
        for line in ("FROM python:3.12-slim\n", "FROM --platform=linux/amd64 python:3.12\n",
                     "FROM python@sha256:abc\n"):
            problems = task.lint_dockerfile(line + "RUN true\n")
            self.assertEqual(len(problems), 1, line)
            self.assertTrue(problems[0].startswith("line 1: FROM python"), problems)
        self.assertEqual(task.lint_dockerfile("RUN true\n"), ["line 1: no FROM instruction"])

    def test_network_tools_in_run(self):
        for cmd in ("apt-get update", "apt install x", "pip install x", "python -m pip install x",
                    "pip3 install x", "curl -O x", "wget x", "git clone x", "npm ci",
                    "aptitude install x"):
            problems = task.lint_dockerfile(PINNED + "RUN " + cmd + "\n")
            self.assertEqual(len(problems), 1, cmd)
            self.assertTrue(problems[0].startswith("line 2: RUN uses"), problems)

    def test_continuation_reports_the_first_line(self):
        text = PINNED + "# comment\n\nRUN chmod 755 /x \\\n    && echo ok \\\n    && wget x\n"
        problems = task.lint_dockerfile(text)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("line 4: RUN uses 'wget'"), problems)

    def test_urls(self):
        problems = task.lint_dockerfile(PINNED + "RUN echo http://example.org\n"
                                        + "ADD https://example.org/x.tgz /x\n")
        self.assertEqual([p.split(":")[0] for p in problems], ["line 2", "line 3"])
        self.assertIn("URL", problems[0])

    def test_no_false_positives(self):
        text = PINNED + ("COPY salvage/ /app/salvage/\n"
                         "RUN python3 -m compileall -q /app && echo digit legit .git-x\n"
                         "ENV PIPELINE=1\n")
        self.assertEqual(task.lint_dockerfile(text), [])


class CheckOutputsTests(unittest.TestCase):
    def test_good_run_passes_and_problems_are_found(self):
        magic = b"SALVAGE-STUB\x00"
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            os.makedirs(os.path.join(inp, "sub"))
            for rel, data in {"a.stub": magic + struct.pack("<H1I", 1, 5),
                              "sub/b.bin": b"xyz"}.items():
                with open(os.path.join(inp, *rel.split("/")), "wb") as fh:
                    fh.write(data)
            proc = subprocess.run([sys.executable, "-m", "salvage.cli", "--jobs", "1", inp, out],
                                  cwd=ROOT, capture_output=True, timeout=120)
            self.assertEqual(proc.returncode, 0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(task.cmd_check_outputs(inp, out), 0)
            self.assertIn("2 inputs, 3 files in output, 0 problems", buf.getvalue())

            os.remove(os.path.join(out, "sub", "b.bin.json"))
            with open(os.path.join(out, "a.stub.json"), "w", encoding="utf-8") as fh:
                fh.write('{"status": "nonsense"}')
            with open(os.path.join(out, "extra.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(task.cmd_check_outputs(inp, out), 1)
            text = buf.getvalue()
            self.assertIn("FAIL  missing output: sub/b.bin.json", text)
            self.assertIn("FAIL  unexpected file: extra.json", text)
            self.assertIn("FAIL  a.stub.json: ", text)


if __name__ == "__main__":
    unittest.main()
