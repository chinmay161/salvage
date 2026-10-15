import unittest

from salvage.core import limits
from salvage.core.model import DamageKind
from salvage.core.reader import SafeReader
from salvage.core.resync import ByteView, ResyncResult, resync, resync_damage

MARK = b"REC!"


def at_marker(view, offset):
    return view.bytes(offset, 4) == MARK


class ByteViewTests(unittest.TestCase):
    def test_reads_and_bounds(self):
        v = ByteView(SafeReader(b"\x01\x02\x03\x04\x05"))
        self.assertEqual(v.size, 5)
        self.assertEqual(v.u8(0), 1)
        self.assertEqual(v.u16le(0), 0x0201)
        self.assertEqual(v.u16be(0), 0x0102)
        self.assertEqual(v.u32le(1), 0x05040302)
        self.assertEqual(v.u32be(1), 0x02030405)
        self.assertEqual(v.bytes(3, 10), b"\x04\x05")       # short at the end
        for bad in (-1, 5, 4.0, None, True, "0"):
            with self.subTest(offset=bad):
                self.assertIsNone(v.u8(bad))
                self.assertIsNone(v.u16le(bad))
                self.assertEqual(v.bytes(bad, 1), b"")
        self.assertIsNone(v.u32le(2))
        self.assertIsNone(v.u16be(4))
        self.assertEqual(v.bytes(0, -1), b"")

    def test_view_creates_no_claims_or_events(self):
        r = SafeReader(bytes(16))
        v = ByteView(r)
        v.u32le(0), v.bytes(0, 100), v.u8(99)
        self.assertEqual((r.claimed(), r.events, r.tell()), ([], [], 0))


class ResyncTests(unittest.TestCase):
    def test_marker_after_junk(self):
        data = b"HEAD" + b"junkjunk" + MARK + b"payload"
        r = SafeReader(data)
        r.bytes(4, "head")
        res = resync(r, at_marker)
        self.assertEqual(res, ResyncResult(12, 5, 12, 8))   # default start = tell() + 1
        self.assertEqual(r.tell(), 12)
        dmg = resync_damage(res, "junk")
        self.assertEqual((dmg.start, dmg.end, dmg.kind, dmg.reason),
                         (5, 12, DamageKind.UNPARSED, "junk"))

    def test_explicit_start_and_step(self):
        data = b"xx" + MARK + b"x" + MARK
        r = SafeReader(data)
        self.assertEqual(resync(r, at_marker, start=0).offset, 2)
        r.seek(0)
        res = resync(r, at_marker, start=1, step=2)   # 1, 3, 5, 7: finds 7
        self.assertEqual((res.offset, res.skipped_start, res.skipped_end, res.checks),
                         (7, 1, 7, 4))

    def test_nothing_found(self):
        r = SafeReader(b"no marker anywhere")
        r.seek(3)
        res = resync(r, at_marker)
        self.assertEqual(res, ResyncResult(None, 4, 18, 14))
        self.assertEqual(r.tell(), 3)                 # position unchanged
        self.assertEqual(resync_damage(res, "x").end, 18)

    def test_max_scan_stops_early(self):
        data = bytes(100) + MARK
        r = SafeReader(data)
        res = resync(r, at_marker, start=0, max_scan=50)
        self.assertEqual(res, ResyncResult(None, 0, 50, 50))
        self.assertEqual(r.tell(), 0)
        self.assertEqual(resync(r, at_marker, start=0, max_scan=104).offset, 100)

    def test_default_max_scan_is_the_limit(self):
        seen = []
        orig = limits.MAX_RESYNC_SCAN
        limits.MAX_RESYNC_SCAN = 10
        try:
            resync(SafeReader(bytes(100)), lambda v, o: seen.append(o), start=0)
        finally:
            limits.MAX_RESYNC_SCAN = orig
        self.assertEqual(seen, list(range(10)))

    def test_raising_callback_counts_as_false(self):
        def check(view, offset):
            if offset < 6:
                raise ValueError("boom")
            return offset == 8

        r = SafeReader(bytes(20))
        res = resync(r, check, start=0)
        self.assertEqual((res.offset, res.checks), (8, 9))

    def test_probing_leaves_claims_unchanged(self):
        data = b"HEAD" + bytes(1000) + MARK
        r = SafeReader(data)
        r.bytes(4, "head")
        before = r.claimed()

        def heavy(view, offset):
            view.bytes(offset, 64), view.u32le(offset), view.u16be(offset)
            return view.bytes(offset, 4) == MARK

        res = resync(r, heavy)
        self.assertEqual(res.offset, 1004)
        self.assertEqual(r.claimed(), before)
        self.assertEqual(r.covered_bytes(), 4)
        self.assertEqual(r.events, [])

    def test_bad_arguments_never_raise(self):
        r = SafeReader(bytes(10))
        for kw in ({"start": -5}, {"start": 99}, {"start": "x"}, {"step": 0},
                   {"step": "2"}, {"max_scan": -1}, {"max_scan": 1.5}):
            with self.subTest(kw=kw):
                res = resync(r, at_marker, **kw)
                self.assertIsNone(res.offset)
                self.assertTrue(0 <= res.skipped_start <= res.skipped_end <= 10)

    def test_empty_skip_gives_no_damage(self):
        self.assertIsNone(resync_damage(ResyncResult(5, 5, 5, 1), "x"))
        self.assertIsNone(resync_damage(ResyncResult(None, 10, 10, 0), "x"))


if __name__ == "__main__":
    unittest.main()
