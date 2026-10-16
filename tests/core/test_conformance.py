"""Merge gate: every real decoder in salvage/formats/ must pass the conformance suite.

A teammate's decoder that FAILs any check (docs/conformance.md) breaks
``python tools/task.py test`` here. The gate runs in quick mode (golden
cases + synthetic inputs, fewer variants, C7 on one input);
``python tools/task.py conform`` runs the full suite, and
``python tools/task.py conform NAME --verbose`` shows every finding for one
decoder.
"""

import unittest

from tests import conformance


class RealPackageTests(unittest.TestCase):
    def test_every_decoder_passes(self):
        reports = conformance.run_conformance(quick=True)
        lines = conformance.format_lines(reports, verbose=True)
        self.assertTrue(reports, "no decoders found in salvage.formats")
        failed = [r.name for r in reports if r.verdict != "PASS"]
        self.assertEqual(failed, [], "conformance FAIL:\n" + "\n".join(lines))
        self.assertIn("STUB", [r.name for r in reports])


if __name__ == "__main__":
    unittest.main()
