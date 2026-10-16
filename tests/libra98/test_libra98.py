"""Unit tests for LIBRA-98 format decoder."""

from __future__ import annotations

import unittest
from pathlib import Path

from salvage.core.model import DamageKind, Status
from salvage.core.reader import SafeReader
from salvage.formats.libra98 import Libra98Decoder

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
        self.assertTrue(any(d.kind == DamageKind.CHECKSUM for d in res.damage))

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


if __name__ == "__main__":
    unittest.main()
