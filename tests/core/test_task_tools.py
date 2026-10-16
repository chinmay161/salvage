"""tools/task.py helpers that need no Docker: the Dockerfile lint and check-outputs."""

import importlib.util
import io
import os
import posixpath
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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


class HostPathTests(unittest.TestCase):
    def test_git_bash_paths_on_windows(self):
        if os.name == "nt":
            self.assertEqual(task.host_path("/c/arbitrary/project/dir"), "C:/arbitrary/project/dir")
            self.assertEqual(task.host_path("/d/arbitrary/data"), "D:/arbitrary/data")
            self.assertEqual(task.host_path("/c"), "C:/")
            self.assertEqual(task.host_path("/c/"), "C:/")
            self.assertEqual(task.host_path("//c/arbitrary/project"), "C:/arbitrary/project")
            self.assertEqual(task.host_path(Path("/c/arbitrary/project")), "C:/arbitrary/project")

    def test_native_windows_paths(self):
        if os.name == "nt":
            self.assertEqual(task.host_path(r"C:\arbitrary\project\dir"), "C:/arbitrary/project/dir")
            self.assertEqual(task.host_path("C:/arbitrary/project/dir"), "C:/arbitrary/project/dir")
            self.assertEqual(task.host_path(Path("C:/arbitrary/project/dir")), "C:/arbitrary/project/dir")

    def test_relative_paths(self):
        rel = "some/relative/test_path"
        expected = os.path.abspath(rel).replace("\\", "/") if os.name == "nt" else os.path.abspath(rel)
        self.assertEqual(task.host_path(rel), expected)
        self.assertEqual(task.host_path(Path(rel)), expected)

    def test_non_windows_behavior(self):
        self.assertEqual(task.normalize_git_bash_path("/c/arbitrary/dir", _os_name="posix"), "/c/arbitrary/dir")
        self.assertEqual(task.normalize_git_bash_path("/var/log/salvage", _os_name="posix"), "/var/log/salvage")
        with patch("os.name", "posix"), patch("os.path.abspath", posixpath.abspath):
            self.assertEqual(task.host_path("/c/arbitrary/dir", _os_name="posix"), "/c/arbitrary/dir")
            self.assertEqual(task.host_path("/var/log/salvage", _os_name="posix"), "/var/log/salvage")
            self.assertEqual(task.host_path("relative/test", _os_name="posix"), posixpath.abspath("relative/test"))

    def test_docker_run_args_uses_host_path(self):
        if os.name == "nt":
            args = task.docker_run_args("/c/input_test", "/c/output_test")
            self.assertIn("-v", args)
            self.assertIn("C:/input_test:/in:ro", args)
            self.assertIn("C:/output_test:/out", args)
            self.assertFalse(any("C:/c/" in arg for arg in args))


if __name__ == "__main__":
    unittest.main()
