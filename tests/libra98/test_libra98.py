"""Unit tests for LIBRA-98 format decoder."""

from __future__ import annotations

import unittest
from pathlib import Path

from salvagekit.core.model import DamageKind, Status
from salvagekit.core.reader import SafeReader
from salvagekit.formats.libra98 import Libra98Decoder

CASES_DIR = Path(__file__).resolve().parent / "cases"
KIT_SAMPLES = Path(__file__).resolve().parent.parent.parent / "kit" / "samples"


class Libra98DecoderTests(unittest.TestCase):
    def setUp(self):
        self.decoder = Libra98Decoder()

    def test_probe_valid_file(self):
        clean = (CASES_DIR / "clean.lb9").read_bytes()
        self.assertEqual(self.decoder.probe(clean), 1.0)

    def test_probe_short_or_invalid(self):
        self.assertEqual(self.decoder.probe(b""), 0.0)
        self.assertEqual(self.decoder.probe(b"LB98"), 0.0)
        self.assertEqual(self.decoder.probe(b"LB98\x02\x00\x03"), 0.0)  # s29_almost_libra
        self.assertEqual(self.decoder.probe(b"\x00" * 32), 0.0)

    def test_decode_clean_case(self):
        clean = (CASES_DIR / "clean.lb9").read_bytes()
        res = self.decoder.decode(SafeReader(clean))
        self.assertEqual(res.format, "LIBRA-98")
        self.assertEqual(res.confidence, 1.0)
        self.assertEqual(res.meta["branch_id"], 100)
        self.assertEqual(res.meta["version"], 2)
        self.assertEqual(res.meta["created"], "1998-10-03T11:20:22")
        self.assertEqual(len(res.records), 1)

        rec = res.records[0]
        self.assertEqual(rec.status, Status.VERIFIED)
        fmap = {f.name: f.value for f in rec.fields}
        self.assertEqual(fmap["id"], 1001)
        self.assertEqual(fmap["title"], "Dune")
        self.assertEqual(fmap["author"], "Frank Herbert")
        self.assertEqual(fmap["year"], 1965)
        self.assertEqual(fmap["price_cents"], 799)
        self.assertEqual(fmap["copies"], 2)
        self.assertEqual(fmap["isbn"], "0441172717")
        self.assertFalse(fmap["checked_out"])
        self.assertFalse(fmap["reference_only"])
        self.assertFalse(fmap["deleted"])
        self.assertIsNone(fmap["due_date"])

    def test_decode_bad_checksum(self):
        bad = (CASES_DIR / "bad_checksum.lb9").read_bytes()
        res = self.decoder.decode(SafeReader(bad))
        self.assertEqual(len(res.records), 1)
        rec = res.records[0]
        self.assertEqual(rec.status, Status.UNVERIFIED)
        self.assertTrue(any(d.kind == DamageKind.CHECKSUM_MISMATCH for d in res.damage))

    def test_decode_truncated(self):
        trunc = (CASES_DIR / "truncated.lb9").read_bytes()
        res = self.decoder.decode(SafeReader(trunc))
        self.assertEqual(len(res.records), 0)
        self.assertTrue(any(d.kind == DamageKind.TRUNCATED for d in res.damage))

    def test_round_trip_encode(self):
        clean = (CASES_DIR / "clean.lb9").read_bytes()
        res = self.decoder.decode(SafeReader(clean))
        encoded = self.decoder.encode(res)
        self.assertEqual(encoded, clean)

    def test_data_offset_oob(self):
        """Regression: invalid data offset beyond file bounds records OOB_POINTER damage."""
        clean = bytearray((CASES_DIR / "clean.lb9").read_bytes())
        # Set data_offset (offset 12) to 9999
        clean[12:14] = (9999).to_bytes(2, "little")
        res = self.decoder.decode(SafeReader(bytes(clean)))
        self.assertTrue(any(d.kind == DamageKind.OOB_POINTER for d in res.damage))

    def test_malformed_record_field_lengths(self):
        """Regression: record field lengths claiming beyond payload length record BAD_LENGTH."""
        clean = bytearray((CASES_DIR / "clean.lb9").read_bytes())
        # Record starts at offset 16 (clean.lb9 has 16-byte header)
        # Offset 16: marker 0xA5, 17: plen, 18: flags, 19..22: id, 23: title_len
        # Set title_len at offset 23 to 250 (exceeds payload length)
        clean[23] = 250
        res = self.decoder.decode(SafeReader(bytes(clean)))
        self.assertTrue(any(d.kind == DamageKind.BAD_LENGTH for d in res.damage))

    def test_missing_trailer_at_eof_no_zero_length(self):
        """Regression: missing trailer at EOF never emits zero-length damage."""
        clean = (CASES_DIR / "clean.lb9").read_bytes()
        # Strip the 6-byte trailer "END!\x..\x.."
        no_trailer = clean[:-6]
        res = self.decoder.decode(SafeReader(no_trailer))
        # Ensure no damage has start == end
        for d in res.damage:
            self.assertLess(d.start, d.end, f"Found zero-length damage range: {d}")

    def test_independent_record_count_mismatch(self):
        """Regression: count mismatch reported even if records were parsed."""
        clean = bytearray((CASES_DIR / "clean.lb9").read_bytes())
        # Change declared record count (offset 6) from 1 to 5
        clean[6:8] = (5).to_bytes(2, "little")
        # Update trailer checksum so trailer is valid
        data_part = clean[:-6]
        trailer_crc = sum(data_part) & 0xFFFF
        clean[-2:] = trailer_crc.to_bytes(2, "little")
        res = self.decoder.decode(SafeReader(bytes(clean)))
        self.assertTrue(any(d.kind == DamageKind.COUNT_MISMATCH for d in res.damage))


if __name__ == "__main__":
    unittest.main()
