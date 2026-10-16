"""Golden tests for every tests/<format>/cases/ folder (see tests/golden.py).

Set SALVAGE_GOLDEN=<format> to check one format only
(``python tools/task.py golden <format>`` does this).
"""

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from salvagekit.core import emit
from salvagekit.formats.stub import MAGIC
from tests import golden


class GoldenTests(unittest.TestCase):
    def test_golden_cases(self):
        only = os.environ.get("SALVAGE_GOLDEN") or None
        dirs = golden.case_dirs(only)
        if only and not dirs:
            self.fail(f"tests/{only}/cases/ does not exist")
        for fmt, cases in dirs.items():
            for case, problem in sorted(golden.check(cases).items()):
                with self.subTest(format=fmt, case=case):
                    if problem is not None:
                        self.fail(f"{fmt}/{case}: {problem}")


CLEAN = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)


class GoldenSelfTests(unittest.TestCase):
    """The checker itself: wrong, missing and orphan expectations all fail."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="salvage-golden-self-")
        self.addCleanup(tmp.cleanup)
        self.cases = Path(tmp.name) / "cases"
        self.cases.mkdir()
        (self.cases / "a.stub").write_bytes(CLEAN)

    def expect(self, name, obj):
        (self.cases / (name + golden.SUFFIX)).write_text(emit.dumps(obj), encoding="utf-8",
                                                         newline="\n")

    def real_output(self):
        return golden.run_cases(self.cases)["a.stub"]

    def test_wrong_expectation_gives_path_diff(self):
        wrong = json.loads(json.dumps(self.real_output()))
        wrong["records"][2]["value"] = 21   # real value is 20
        wrong["status"] = "partial"
        del wrong["metadata"]["decoded_count"]
        self.expect("a.stub", wrong)
        problem = golden.check(self.cases)["a.stub"]
        self.assertIsNotNone(problem)
        self.assertEqual(problem.splitlines(), [
            "3 difference(s):",
            "  metadata.decoded_count: expected nothing (unexpected key), got 3",
            "  records[2].value: expected 21, got 20",
            '  status: expected "partial", got "ok"',
        ])

    def test_correct_expectation_passes(self):
        self.expect("a.stub", self.real_output())
        self.assertEqual(golden.check(self.cases), {"a.stub": None})

    def test_missing_and_orphan(self):
        self.expect("gone.bin", {})
        problems = golden.check(self.cases)
        self.assertTrue(problems["a.stub"].startswith("missing expectation"), problems)
        self.assertTrue(problems["gone.bin.expected.json"].startswith("orphan expectation"),
                        problems)

    def test_diff_caps_at_20_and_handles_lists(self):
        exp = {"r": list(range(30))}
        got = {"r": [v + 1 for v in range(30)] + [99]}
        diffs = golden.diff(exp, got)
        self.assertEqual(len(diffs), golden.MAX_DIFFS)
        self.assertEqual(diffs[0], "r: expected 30 items, got 31")
        self.assertEqual(diffs[1], "r[0]: expected 0, got 1")
        self.assertEqual(golden.diff({"x": 1}, {"x": 1.0}), [])
        self.assertEqual(golden.diff({"x": 1}, {"x": True}), ["x: expected 1, got true"])


if __name__ == "__main__":
    unittest.main()
