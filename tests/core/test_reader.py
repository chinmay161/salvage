import math
import random
import struct
import unittest

from salvagekit.core.reader import ReaderEvent, SafeReader


class ReadTypeTests(unittest.TestCase):
    def test_integers_both_endiannesses(self):
        data = bytes.fromhex("0102030405060708")
        cases = [
            ("u8", 0x01, 1), ("i8", 0x01, 1),
            ("u16le", 0x0201, 2), ("u16be", 0x0102, 2),
            ("i16le", 0x0201, 2), ("i16be", 0x0102, 2),
            ("u32le", 0x04030201, 4), ("u32be", 0x01020304, 4),
            ("i32le", 0x04030201, 4), ("i32be", 0x01020304, 4),
            ("u64le", 0x0807060504030201, 8),
        ]
        for method, expected, size in cases:
            with self.subTest(method=method):
                r = SafeReader(data)
                self.assertEqual(getattr(r, method)(), expected)
                self.assertEqual(r.tell(), size)

    def test_signed_negative(self):
        data = (b"\xff" + b"\xfe\xff" + b"\xff\xfe"
                + b"\xfe\xff\xff\xff" + b"\xff\xff\xff\xfe")
        r = SafeReader(data)
        self.assertEqual(r.i8(), -1)
        self.assertEqual(r.i16le(), -2)
        self.assertEqual(r.i16be(), -2)
        self.assertEqual(r.i32le(), -2)
        self.assertEqual(r.i32be(), -2)
        self.assertEqual(r.remaining(), 0)

    def test_floats(self):
        r = SafeReader(struct.pack("<f", 1.5) + struct.pack("<d", -2.25))
        self.assertEqual(r.f32le(), 1.5)
        self.assertEqual(r.f64le(), -2.25)
        r = SafeReader(struct.pack("<d", math.nan))
        self.assertTrue(math.isnan(r.f64le()))

    def test_size_tell_remaining(self):
        r = SafeReader(b"abcdef")
        self.assertEqual((r.size, r.tell(), r.remaining()), (6, 0, 6))
        r.u16le()
        self.assertEqual((r.tell(), r.remaining()), (2, 4))


class TruncationTests(unittest.TestCase):
    def test_truncated_read_returns_none_and_keeps_position(self):
        r = SafeReader(b"\x01\x02\x03")
        r.u8()
        self.assertIsNone(r.u32le("hdr"))
        self.assertEqual(r.tell(), 1)
        self.assertEqual(r.events, [ReaderEvent("truncated", 1, 4, 2, "hdr")])

    def test_every_numeric_read_truncates_cleanly(self):
        for method in ["u8", "i8", "u16le", "u16be", "i16le", "i16be", "u32le",
                       "u32be", "i32le", "i32be", "u64le", "f32le", "f64le"]:
            with self.subTest(method=method):
                r = SafeReader(b"")
                self.assertIsNone(getattr(r, method)())
                self.assertEqual(r.tell(), 0)
                self.assertEqual(r.events[0].kind, "truncated")
                self.assertEqual(r.claimed(), [])

    def test_bytes_short_tail(self):
        r = SafeReader(b"abcde")
        r.skip(3)
        self.assertEqual(r.bytes(10, "tail"), b"de")
        self.assertEqual(r.tell(), 5)
        self.assertEqual(r.events, [ReaderEvent("truncated", 3, 10, 2, "tail")])
        self.assertEqual(r.claimed(), [(3, 5, "tail")])

    def test_bytes_negative_length(self):
        r = SafeReader(b"abc")
        self.assertEqual(r.bytes(-1), b"")
        self.assertEqual(r.tell(), 0)
        self.assertEqual(r.events[0].kind, "bad_length")

    def test_bytes_exact(self):
        r = SafeReader(b"abc")
        self.assertEqual(r.bytes(3), b"abc")
        self.assertEqual(r.events, [])


class SeekTests(unittest.TestCase):
    def test_seek_bounds(self):
        r = SafeReader(b"abcd")
        self.assertTrue(r.seek(4))
        self.assertTrue(r.seek(0))
        r.seek(2)
        self.assertFalse(r.seek(5))
        self.assertFalse(r.seek(-1))
        self.assertEqual(r.tell(), 2)
        self.assertEqual([e.kind for e in r.events], ["bad_seek", "bad_seek"])

    def test_skip_bounds(self):
        r = SafeReader(b"abcd")
        self.assertTrue(r.skip(3))
        self.assertFalse(r.skip(2))
        self.assertEqual(r.tell(), 3)
        self.assertTrue(r.skip(-3))
        self.assertFalse(r.skip(-1))
        self.assertEqual(r.tell(), 0)

    def test_at_restores_position(self):
        r = SafeReader(b"\x00\x01\x02\x03")
        r.seek(1)
        with r.at(3) as ok:
            self.assertTrue(ok)
            self.assertEqual(r.u8(), 3)
        self.assertEqual(r.tell(), 1)

    def test_at_invalid_offset(self):
        r = SafeReader(b"\x00\x01")
        r.seek(1)
        with r.at(9) as ok:
            self.assertFalse(ok)
            self.assertEqual(r.tell(), 1)
        self.assertEqual(r.tell(), 1)
        self.assertEqual(r.events[-1].kind, "bad_seek")

    def test_at_restores_on_exception(self):
        r = SafeReader(b"\x00\x01")
        with self.assertRaises(KeyError):
            with r.at(2):
                raise KeyError("boom")
        self.assertEqual(r.tell(), 0)


class UnpackAndCStringTests(unittest.TestCase):
    def test_unpack(self):
        r = SafeReader(b"\x01\x00\x02\x00\x00\x00")
        self.assertEqual(r.unpack("<HI"), (1, 2))
        self.assertEqual(r.tell(), 6)

    def test_unpack_requires_endianness(self):
        for fmt in ["HI", "=H", "!H", "@H", "", None, 5, "<Z"]:
            with self.subTest(fmt=fmt):
                r = SafeReader(b"\x01\x00\x02\x00")
                self.assertIsNone(r.unpack(fmt))
                self.assertEqual(r.events[0].kind, "bad_format")
                self.assertEqual(r.tell(), 0)

    def test_unpack_truncated(self):
        r = SafeReader(b"\x01\x00")
        self.assertIsNone(r.unpack(">I"))
        self.assertEqual(r.tell(), 0)
        self.assertEqual(r.events[0].kind, "truncated")

    def test_cstring_with_nul(self):
        r = SafeReader(b"abc\x00def")
        self.assertEqual(r.cstring(label="s"), b"abc")
        self.assertEqual(r.tell(), 4)
        self.assertEqual(r.claimed(), [(0, 4, "s")])

    def test_cstring_without_nul(self):
        r = SafeReader(b"abcdef")
        self.assertIsNone(r.cstring())
        self.assertEqual(r.tell(), 0)
        self.assertEqual(r.events[0].kind, "truncated")

    def test_cstring_nul_beyond_max_len(self):
        r = SafeReader(b"abcdef\x00")
        self.assertIsNone(r.cstring(max_len=3))
        self.assertEqual(r.tell(), 0)
        self.assertEqual(r.cstring(max_len=7), b"abcdef")

    def test_cstring_empty(self):
        r = SafeReader(b"\x00x")
        self.assertEqual(r.cstring(), b"")
        self.assertEqual(r.tell(), 1)


class ClaimTests(unittest.TestCase):
    def test_peek_makes_no_claim(self):
        r = SafeReader(b"abcdef")
        self.assertEqual(r.peek(3), b"abc")
        self.assertEqual(r.peek(100), b"abcdef")
        self.assertEqual(r.peek(-1), b"")
        self.assertEqual(r.tell(), 0)
        self.assertEqual(r.claimed(), [])
        self.assertEqual(r.covered_bytes(), 0)

    def test_claim_merging_same_label_only(self):
        r = SafeReader(bytes(32))
        r.u16le("a")
        r.u16le("a")          # adjacent, same label -> merged
        r.u32le("b")          # adjacent, different label -> separate
        r.u8()                # default label "?"
        with r.at(2):
            r.u32le("a")      # overlaps a (0-4) and b (4-8)
        self.assertEqual(r.claimed(), [(0, 6, "a"), (4, 8, "b"), (8, 9, "?")])

    def test_covered_bytes_counts_distinct(self):
        r = SafeReader(bytes(32))
        r.u32le("x")
        r.seek(2)
        r.u32le("y")
        r.seek(20)
        r.u8()
        self.assertEqual(r.covered_bytes(), 6 + 1)


class FuzzTests(unittest.TestCase):
    def test_random_operations_never_raise(self):
        rng = random.Random(20261015)
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 64)))
        r = SafeReader(data)
        weird = [None, -1, 0, 1, 3, 7, 10**12, -10**12, 2.5, "x", b"", True,
                 [], object(), float("nan")]
        numeric = ["u8", "i8", "u16le", "u16be", "i16le", "i16be", "u32le", "u32be",
                   "i32le", "i32be", "u64le", "f32le", "f64le"]
        fmts = ["<I", ">hH", "I", "<", ">Z", "", None, 3, "<3s", "<q"]
        for _ in range(2000):
            op = rng.randrange(10)
            arg = rng.choice(weird + [rng.randrange(-5, len(data) + 5)])
            label = rng.choice([None, "lbl", 7, object()])
            if op == 0:
                getattr(r, rng.choice(numeric))(label)
            elif op == 1:
                r.bytes(arg, label)
            elif op == 2:
                r.seek(arg)
            elif op == 3:
                r.skip(arg)
            elif op == 4:
                r.unpack(rng.choice(fmts), label)
            elif op == 5:
                r.cstring(arg, label)
            elif op == 6:
                r.peek(arg)
            elif op == 7:
                with r.at(arg):
                    r.u8()
            elif op == 8:
                r.claimed()
                r.covered_bytes()
            else:
                r.size, r.tell(), r.remaining(), r.events
            self.assertTrue(0 <= r.tell() <= r.size)
        self.assertLessEqual(r.covered_bytes(), r.size)

    def test_constructor_accepts_bytearray(self):
        self.assertEqual(SafeReader(bytearray(b"ab")).bytes(2), b"ab")
        self.assertEqual(SafeReader(None).size, 0)


if __name__ == "__main__":
    unittest.main()
