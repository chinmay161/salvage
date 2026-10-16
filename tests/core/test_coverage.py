import struct
import unittest

from salvagekit.core.coverage import coverage
from salvagekit.core.reader import SafeReader
from salvagekit.formats.stub import MAGIC, StubDecoder


class CoverageTests(unittest.TestCase):
    def test_hand_computed_example(self):
        # 40 bytes. Claims (start, end, label):
        #   [0, 10) "a"   [5, 12) "b"         -> explained 0..12 (overlap counted once)
        #   [12, 16) "padding"                 -> padding 4
        #   [14, 20) "c"                       -> explained 14..20, overlaps padding 14..16
        #   [24, 28) "padding" twice           -> padding 4 (duplicates counted once)
        #   gaps: [20, 24), [28, 40)
        r = SafeReader(bytes(40))
        r.bytes(10, "a")
        r.seek(5)
        r.bytes(7, "b")
        r.bytes(4, "padding")
        r.seek(14)
        r.bytes(6, "c")
        for _ in range(2):
            r.seek(24)
            r.bytes(4, "padding")
        cov = coverage(r)
        # explained = [0,12) + [14,20) = 18; padding only = [12,14) + [24,28) = 6
        self.assertEqual(cov, {
            "bytes_total": 40, "bytes_explained": 18, "bytes_padding": 6,
            "explained_pct": 45.0, "accounted_pct": 60.0,
            "unexplained": [[20, 24], [28, 40]], "unexplained_truncated": False,
        })

    def test_rounding(self):
        r = SafeReader(bytes(3))
        r.u8("x")
        cov = coverage(r)
        self.assertEqual((cov["explained_pct"], cov["accounted_pct"]), (33.33, 33.33))

    def test_unlabelled_reads_count_as_explained(self):
        r = SafeReader(b"ab")
        r.u8()
        self.assertEqual(coverage(r)["bytes_explained"], 1)

    def test_empty_file(self):
        self.assertEqual(coverage(SafeReader(b"")), {
            "bytes_total": 0, "bytes_explained": 0, "bytes_padding": 0,
            "explained_pct": None, "accounted_pct": None,
            "unexplained": [], "unexplained_truncated": False,
        })

    def test_nothing_read(self):
        cov = coverage(SafeReader(bytes(7)))
        self.assertEqual((cov["bytes_explained"], cov["explained_pct"], cov["unexplained"]),
                         (0, 0.0, [[0, 7]]))

    def test_unexplained_capped_at_100(self):
        r = SafeReader(bytes(1000))
        for off in range(0, 1000, 4):     # claim 1 byte of every 4 -> 250 gaps
            r.seek(off)
            r.u8("x")
        cov = coverage(r)
        self.assertEqual(len(cov["unexplained"]), 100)
        self.assertTrue(cov["unexplained_truncated"])
        self.assertEqual(cov["unexplained"][0], [1, 4])

    def test_stub_clean_file_fully_explained(self):
        data = MAGIC + struct.pack("<H3I", 3, 10, 20, 30)
        r = SafeReader(data)
        StubDecoder().decode(r)
        cov = coverage(r)
        self.assertEqual((cov["explained_pct"], cov["accounted_pct"], cov["unexplained"]),
                         (100.0, 100.0, []))
        self.assertEqual(cov["bytes_explained"], len(data))

    def test_stub_truncated_tail_unexplained(self):
        data = MAGIC + struct.pack("<H2I", 5, 100, 200) + b"\x07\x00"
        r = SafeReader(data)
        StubDecoder().decode(r)
        cov = coverage(r)
        self.assertEqual(cov["unexplained"], [[23, 25]])
        self.assertEqual(cov["explained_pct"], 92.0)


if __name__ == "__main__":
    unittest.main()
