"""Proves the conformance suite (tests/conformance.py) catches what it claims.

One decoder per bug in tests/fixtures/conform_formats/; each must fail with
its expected check ID, and the well-behaved "ok" must pass. The fixture
package is checked once (setUpClass); the tests read that run.
"""

import ast
import random
import tempfile
import unittest

from tests import conformance as cf

PACKAGE = "tests.fixtures.conform_formats"


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(prefix="salvage-conform-") as no_samples:
            reports = cf.run_conformance(
                PACKAGE, cases_root="tests/fixtures/conform_cases", samples_root=no_samples,
                docs_root="tests/fixtures/conform_docs", variant_timeout=2.0)
        cls.reports = {r.module.rsplit(".", 1)[-1]: r for r in reports}
        cls.lines = "\n".join(cf.format_lines(reports, verbose=True))

    def report(self, module):
        self.assertIn(module, self.reports, self.lines)
        return self.reports[module]

    def fails(self, module, check_id):
        """The FAIL findings of ``module`` for ``check_id`` (asserts there is one)."""
        rep = self.report(module)
        found = [f for f in rep.findings if f.check_id == check_id and f.severity == cf.FAIL]
        self.assertTrue(found, f"{module}: no FAIL {check_id}\n{self.lines}")
        self.assertEqual(rep.verdict, cf.FAIL)
        return found

    def test_ok_passes_with_no_findings(self):
        rep = self.report("ok")
        self.assertEqual((rep.verdict, rep.findings), ("PASS", []), self.lines)
        self.assertEqual(rep.inputs, 1)
        self.assertGreater(rep.variants, 30)

    def test_greedyprobe_c3(self):
        found = self.fails("greedyprobe", "C3")
        texts = " ".join(f.message for f in found)
        self.assertIn("synthetic input <empty>", texts)
        self.assertIn("golden case of CF-OK", texts)
        # Foreign files decode to an empty result ("not mine"): no round trip expected.
        self.assertEqual([f for f in self.report("greedyprobe").findings
                          if f.check_id == "C6"], [])

    def test_slowprobe_c2(self):
        found = self.fails("slowprobe", "C2")
        self.assertTrue(any("8 MB" in f.message for f in found), found)
        # A2: failed twice, once with no other decoder running; both timings shown.
        self.assertRegex(found[0].message, r"took \d+\.\d\d s, and \d+\.\d\d s when "
                                           r"re-measured alone \(limit 0\.5 s\)")

    def test_warmup_slow_only_on_first_call_passes(self):
        rep = self.report("warmup")
        self.assertEqual(rep.verdict, "PASS", self.lines)
        self.assertEqual([(f.check_id, f.severity) for f in rep.findings],
                         [("C2", cf.WARN), ("C9", cf.WARN)], self.lines)
        for f in rep.findings:
            self.assertIn("when re-measured alone", f.message)
            self.assertIn("passed on the re-measure", f.message)

    def test_raisetrunc_c4(self):
        found = self.fails("raisetrunc", "C4")
        self.assertIn("decode raised IndexError", found[0].message)
        self.assertIn("raisetrunc.py:", found[0].message)    # last traceback line
        self.assertTrue(found[0].variant.startswith("truncate@"), found[0])

    def test_badoffset_c4(self):
        found = self.fails("badoffset", "C4")
        self.assertIn("beyond file size", found[0].message)

    def test_hang_c4_timeout(self):
        found = self.fails("hang", "C4")
        self.assertTrue(any(f.message.startswith("timed out on append@") for f in found), found)

    def test_crash_c4(self):
        found = self.fails("crash", "C4")
        self.assertTrue(any("worker crashed" in f.message and "exit code 3" in f.message
                            for f in found), found)

    def test_liar_c5(self):
        found = self.fails("liar", "C5")
        self.assertIn("verified but bytes changed", found[0].message)

    def test_badtrip_c6(self):
        found = self.fails("badtrip", "C6")
        self.assertIn("offset 56", found[0].message)
        self.assertIn("encode gave end of data", found[0].message)

    def test_nondet_c7(self):
        found = self.fails("nondet", "C7")
        self.assertIn("meta.tags", found[0].message)

    def test_forbidden_c8_exactly_three(self):
        found = self.fails("forbidden", "C8")
        path = "tests/fixtures/conform_formats/forbidden.py"
        self.assertEqual([f.message.split(" (")[0] for f in found], [
            f"{path}:3: forbidden import socket",
            f"{path}:16: forbidden call open()",
            f"{path}:20: fromtimestamp() without a timezone"])   # line 24 (__main__) exempt

    def test_slow_c9(self):
        found = self.fails("slow", "C9")
        self.assertIn("limit 2 s", found[0].message)
        self.assertIn("when re-measured alone", found[0].message)

    def test_nocases_c10_and_c11(self):
        found = self.fails("nocases", "C10")
        self.assertIn("conform_cases/nocases/cases/", found[0].message)
        warns = [f for f in self.report("nocases").findings if f.check_id == "C11"]
        self.assertEqual([f.severity for f in warns], [cf.WARN, cf.WARN])

    def test_runner_lines(self):
        lines = cf.format_lines([self.report("ok"), self.report("liar")])
        self.assertRegex(lines[0], r"^PASS  CF-OK +1 inputs, \d+ variants, 0 warnings$")
        self.assertRegex(lines[1], r"^FAIL  CF-LIAR +C5 honesty: field \"text\" @0x[0-9a-f]+ "
                                   r"verified but bytes changed \(bitflip@")


class DiscoveryErrorTests(unittest.TestCase):
    def test_import_errors_and_duplicates_are_reported(self):
        reports = cf.run_conformance("tests.fixtures.fake_formats", cases_root="tests/fixtures",
                                     samples_root="tests/fixtures/__none__", variant_timeout=2.0)
        by_module = {r.module: r for r in reports}
        broken = by_module["tests.fixtures.fake_formats.broken"]
        self.assertEqual(broken.verdict, cf.FAIL)
        self.assertIn("broken on purpose", broken.findings[0].message)
        self.assertIn("duplicate decoder name",
                      " ".join(f.message for f in by_module["tests.fixtures.fake_formats.good"]
                               .findings))
        self.assertEqual(cf.run_conformance("tests.fixtures.fake_formats", only="nope"), [])


class VariantTests(unittest.TestCase):
    DATA = bytes(range(256)) * 2

    def test_reproducible_and_seeded_by_name(self):
        a = list(cf.variants(self.DATA, "X"))
        self.assertEqual(a, list(cf.variants(self.DATA, "X")))
        b = list(cf.variants(self.DATA, "Y"))
        self.assertNotEqual([v.name for v in a if v.name.startswith("bitflip")],
                            [v.name for v in b if v.name.startswith("bitflip")])

    def test_kinds_counts_and_ranges(self):
        vs = list(cf.variants(self.DATA, "X"))
        kinds = [v.name.split("@")[0] for v in vs]
        self.assertEqual([kinds.count(k) for k in ("truncate", "bitflip", "zero", "overwrite",
                                                   "append")], [16, 20, 3, 3, 1])
        n = len(self.DATA)
        self.assertEqual(vs[0].name, "truncate@0")
        self.assertEqual(vs[15], cf.Variant(f"truncate@{n - 1}", self.DATA[:-1], ((n - 1, n),)))
        for v in vs:
            if v.name.startswith("bitflip@"):
                i, bit = map(int, v.name[8:].split("."))
                self.assertEqual(v.changed, ((i, i + 1),))
                self.assertEqual(v.data[i] ^ self.DATA[i], 1 << bit)
            if v.name.startswith(("zero@", "overwrite@")):
                changed = {i for s, e in v.changed for i in range(s, e)}
                self.assertEqual(changed, {i for i in range(n) if v.data[i] != self.DATA[i]})
        self.assertEqual(vs[-1].name, f"append@{n}")
        self.assertEqual(vs[-1].changed, ((n, n + 100),))

    def test_no_op_and_duplicate_variants_are_skipped(self):
        names = [v.name for v in cf.variants(bytes(200), "X")]
        self.assertFalse([n for n in names if n.startswith("zero@")])
        self.assertEqual([v.name for v in cf.variants(b"", "X")], ["append@0"])

    def test_quick_mode_counts(self):
        vs = list(cf.variants(self.DATA, "X", quick=True))
        kinds = [v.name.split("@")[0] for v in vs]
        self.assertEqual([kinds.count(k) for k in ("truncate", "bitflip", "zero", "overwrite",
                                                   "append")], [8, 8, 2, 2, 1])
        big = random.Random(1).randbytes(cf.BIG_INPUT + 1)
        kinds = [v.name.split("@")[0] for v in cf.variants(big, "X", quick=True)]
        self.assertEqual((kinds.count("truncate"), kinds.count("bitflip")), (8, 8))

    def test_full_mode_is_unchanged_by_quick(self):
        # Quick mode must not shift the seeded draws of the full plan.
        names = [v.name for v in cf.variants(self.DATA, "X")]
        self.assertEqual(len(names), 43)
        self.assertEqual(names, [v.name for v in cf.variants(self.DATA, "X", quick=False)])

    def test_big_inputs_get_fewer(self):
        big = random.Random(1).randbytes(cf.BIG_INPUT + 1)
        kinds = [v.name.split("@")[0] for v in cf.variants(big, "X")]
        self.assertEqual((kinds.count("truncate"), kinds.count("bitflip")), (8, 10))


class StaticRuleTests(unittest.TestCase):
    def problems(self, source, module="salvage.formats.x"):
        checker = cf._StaticChecker(module, "salvage.formats", is_pkg=False)
        checker.visit(ast.parse(source))
        return [rule for _, rule in checker.problems], checker.helpers

    def test_allowed(self):
        src = ("import struct, zlib, re\nfrom salvage.core import checksums\n"
               "from salvage.core.model import Field\nfrom salvage.formats import _shared\n"
               "from . import _util\nfrom ._more import helper\n"
               "from datetime import datetime, timezone\n"
               "re.compile('x')\ndatetime.fromtimestamp(0, timezone.utc)\n"
               "datetime.fromtimestamp(0, tz=timezone.utc)\n"
               "if __name__ == '__main__':\n    import os\n    open('x')\n")
        problems, helpers = self.problems(src)
        self.assertEqual(problems, [])
        self.assertEqual(helpers, {"salvage.formats._shared", "salvage.formats._util",
                                   "salvage.formats._more"})

    def test_refused(self):
        src = ("import os.path\nfrom urllib import request\nimport numpy\n"
               "from salvage.formats import stub\nfrom .stub import MAGIC\n"
               "x = hash('a')\ny = eval('1')\nimport datetime\nz = datetime.datetime.now()\n"
               "def f():\n    if True:\n        open('a')\n"
               "if __name__ == '__main__':\n    pass\nelse:\n    id(1)\n")
        problems, _ = self.problems(src)
        self.assertEqual(problems, [
            "forbidden import os.path", "forbidden import urllib",
            "import numpy not allowed (only the standard library, salvage.core and private "
            "helpers salvage.formats._*)",
            "import salvage.formats.stub not allowed (another decoder's module; shared code "
            "goes in a private helper salvage.formats._name)",
            "import salvage.formats.stub not allowed (another decoder's module; shared code "
            "goes in a private helper salvage.formats._name)",
            "forbidden call hash()", "forbidden call eval()",
            "forbidden attribute .now (the current time makes output non-deterministic)",
            "forbidden call open()", "forbidden call id()"])

    def test_real_stub_is_clean(self):
        self.assertEqual(cf.static_problems("salvage.formats.stub", "salvage.formats"), [])


if __name__ == "__main__":
    unittest.main()
