import random
import unittest
import zlib

from salvagekit.core import checksums as cs

CHECK = b"123456789"

# Literal catalogue check values; never recompute these.
EXPECTED_CHECKS = {
    "CRC-8/SMBUS": 0xF4,
    "CRC-16/ARC": 0xBB3D,
    "CRC-16/MODBUS": 0x4B37,
    "CRC-16/KERMIT": 0x2189,
    "CRC-16/XMODEM": 0x31C3,
    "CRC-16/IBM-3740": 0x29B1,
    "CRC-32": 0xCBF43926,
    "CRC-32/BZIP2": 0xFC891918,
    "CRC-32C": 0xE3069283,
}


class CrcPresetTests(unittest.TestCase):
    def test_preset_set_matches_spec(self):
        self.assertEqual(set(cs.CRC_PRESETS), set(EXPECTED_CHECKS))

    def test_every_preset_check_value(self):
        for name, expected in EXPECTED_CHECKS.items():
            with self.subTest(name=name):
                self.assertEqual(cs.crc_preset(name, CHECK), expected)
                self.assertEqual(cs.CRC_PRESETS[name]["check"], expected)
                fn, width = cs.ALGORITHMS[name]
                self.assertEqual(fn(CHECK), expected)
                self.assertEqual(width, cs.CRC_PRESETS[name]["width"])

    def test_crc32_matches_zlib_on_random_data(self):
        rng = random.Random(1234)
        for _ in range(50):
            data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
            self.assertEqual(cs.crc_preset("CRC-32", data), zlib.crc32(data))

    def test_empty_input(self):
        self.assertEqual(cs.crc_preset("CRC-32", b""), 0)
        self.assertEqual(cs.crc_preset("CRC-16/IBM-3740", b""), 0xFFFF)


class SimpleChecksumTests(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(cs.sum8(CHECK), 0xDD)
        self.assertEqual(cs.sum8_neg(CHECK), 0x23)
        self.assertEqual(cs.sum16(CHECK), 0x01DD)
        self.assertEqual(cs.xor8(CHECK), 0x31)
        self.assertEqual(cs.adler32(CHECK), 0x091E01DE)
        self.assertEqual(cs.fletcher16(b"abcde"), 0xC8F0)

    def test_sum8_neg_zeroes_total(self):
        self.assertEqual(cs.sum8(CHECK + bytes([cs.sum8_neg(CHECK)])), 0)

    def test_word_sums_pad_odd_length(self):
        self.assertEqual(cs.sum16_words_le(b"\x01\x02\x03"), 0x0201 + 0x0003)
        self.assertEqual(cs.sum16_words_be(b"\x01\x02\x03"), 0x0102 + 0x0300)
        self.assertEqual(cs.sum16_words_le(b"\xff\xff\x02\x00"), 0x0001)

    def test_sum32(self):
        self.assertEqual(cs.sum32(b"\xff" * 4), 0x3FC)

    def test_algorithms_cover_everything(self):
        simple = {"sum8", "sum8_neg", "sum16", "sum32", "sum16_words_le",
                  "sum16_words_be", "xor8", "adler32", "fletcher16"}
        self.assertTrue(simple | set(cs.CRC_PRESETS) <= set(cs.ALGORITHMS))


class FindChecksumTests(unittest.TestCase):
    def test_finds_planted_xmodem(self):
        rng = random.Random(42)
        data = bytearray(rng.randrange(256) for _ in range(256))
        target = cs.crc_preset("CRC-16/XMODEM", bytes(data[4:200]))
        data[200:202] = target.to_bytes(2, "big")
        ranges = [(s, e) for s in range(0, 9) for e in range(196, 205)]
        matches = cs.find_checksum(bytes(data), target, ranges=ranges)
        self.assertIn(cs.ChecksumMatch("CRC-16/XMODEM", 4, 200), matches)
        self.assertEqual(matches, sorted(matches))

    def test_default_ranges_cover_head_and_tail(self):
        data = bytes(range(100))
        target = cs.crc_preset("CRC-32", data[3:90])
        matches = cs.find_checksum(data, target, algorithms=["CRC-32"])
        self.assertIn(cs.ChecksumMatch("CRC-32", 3, 90), matches)

    def test_skips_narrow_algorithms(self):
        data = bytes(range(40))
        matches = cs.find_checksum(data, 0x1_0000_0000 - 1)
        self.assertTrue(all(cs.ALGORITHMS[m.name][1] >= 32 for m in matches))

    def test_never_raises(self):
        for args in [(None, 1), (b"abc", "x"), (b"abc", -1), (b"", 0)]:
            self.assertEqual(cs.find_checksum(*args), [])
        self.assertEqual(cs.find_checksum(b"abc", 1, ranges=[(5, 1), "bad", None]), [])
        self.assertIsInstance(cs.find_checksum(b"abc", 1, algorithms=["nope"]), list)

    def test_max_ranges(self):
        data = bytes(64)
        all_hits = cs.find_checksum(data, 0, algorithms=["sum8"])
        capped = cs.find_checksum(data, 0, algorithms=["sum8"], max_ranges=5)
        self.assertEqual(len(capped), 5)
        self.assertGreater(len(all_hits), 5)


if __name__ == "__main__":
    unittest.main()
