import os
import tempfile
import unittest
from unittest import mock

from salvage.core import caps, isolate, limits, report, validate
from tests.fixtures.limit_formats.many import ManyDecoder

PKG = "tests.fixtures.limit_formats"


def totals(result):
    recs = members = 0
    for res in report.walk_results(result):
        recs += len(res.records)
        members += res is not result
    return recs, members


def decode_many():
    return ManyDecoder().decode(None)


class WithinTests(unittest.TestCase):
    def test_within(self):
        self.assertTrue(limits.within(0, 5))
        self.assertTrue(limits.within(5, 5))
        for bad in (6, -1, True, 2.0, None, "3"):
            with self.subTest(n=bad):
                self.assertFalse(limits.within(bad, 5))

    def test_limit_values(self):
        self.assertEqual(limits.MAX_RECORDS, 1_000_000)
        self.assertEqual(limits.MAX_MEMBERS, 100_000)
        self.assertEqual(limits.MAX_DECOMPRESSED, 256 * 1024 * 1024)
        self.assertEqual(limits.MAX_RESYNC_SCAN, 16 * 1024 * 1024)


class EnforceTests(unittest.TestCase):
    def test_fixture_totals(self):
        self.assertEqual(totals(decode_many()), (23, 6))

    def test_under_the_limits_nothing_changes(self):
        res = decode_many()
        self.assertEqual(caps.enforce(res, 23, 6), [])
        self.assertEqual(totals(res), (23, 6))
        self.assertEqual(res.warnings, [])

    def test_records_capped_depth_first(self):
        res = decode_many()
        notes = caps.enforce(res, 10, 100)
        self.assertEqual(notes, ["output capped at 10 records"])
        self.assertEqual(res.warnings, notes)
        self.assertEqual(totals(res), (10, 6))
        # top 5, then m0 4, then m0/inner 1, then nothing
        self.assertEqual(len(res.records), 5)
        self.assertEqual(len(res.members[0].records), 4)
        self.assertEqual(len(res.members[0].members[0].records), 1)
        self.assertEqual(len(res.members[1].records), 0)

    def test_members_capped(self):
        res = decode_many()
        notes = caps.enforce(res, 1000, 3)
        self.assertEqual(notes, ["output capped at 3 members"])
        # m0, m0/inner, m1 (and m1's inner is cut)
        self.assertEqual([m.name for m in res.members], ["m0", "m1"])
        self.assertEqual(res.members[1].members, [])
        self.assertEqual(totals(res), (5 + 4 + 2 + 4, 3))

    def test_both(self):
        res = decode_many()
        self.assertEqual(caps.enforce(res, 2, 0),
                         ["output capped at 2 records", "output capped at 0 members"])
        self.assertEqual(totals(res), (2, 0))


class PipelineCapTests(unittest.TestCase):
    """The worker caps the result, warns, and reports "partial"."""

    def test_capped_file_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.many")
            with open(path, "wb") as fh:
                fh.write(b"T-MANY")
            with mock.patch.object(limits, "MAX_RECORDS", 7), \
                    mock.patch.object(limits, "MAX_MEMBERS", 2):
                payload = isolate.process_file(path, "x.many", PKG)
            out, entry = payload["output"], payload["entry"]
            self.assertEqual(entry["status"], "partial")
            self.assertEqual(out["status"], "partial")
            self.assertIn("output capped at 7 records", out["warnings"])
            self.assertIn("output capped at 2 members", out["warnings"])
            self.assertEqual(sum(entry["records_by_status"].values()), 7)
            self.assertEqual(entry["members"], 2)
            out["source"]["sha256"] = None
            self.assertEqual(validate.errors("output", out), [])

    def test_uncapped_file_is_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.many")
            with open(path, "wb") as fh:
                fh.write(b"T-MANY")
            payload = isolate.process_file(path, "x.many", PKG)
            self.assertEqual(payload["entry"]["status"], "decoded")
            self.assertEqual(payload["output"]["warnings"], [])


if __name__ == "__main__":
    unittest.main()
