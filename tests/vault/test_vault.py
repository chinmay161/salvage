"""Unit tests for the VAULT decoder."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from salvagekit.core.model import DamageKind, Status
from salvagekit.core.reader import SafeReader
from salvagekit.formats.vault import VaultDecoder

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "kit" / "samples"


class VaultDecoderTests(unittest.TestCase):
    def setUp(self):
        self.dec = VaultDecoder()

    def test_probe(self):
        # Empty and non-magic
        self.assertEqual(self.dec.probe(b""), 0.0)
        self.assertEqual(self.dec.probe(b"XXXX"), 0.0)
        self.assertEqual(self.dec.probe(b"VLT1"), 0.6)  # Short header

        # Valid sample files
        s08 = (SAMPLES / "s08.dat").read_bytes()
        self.assertEqual(self.dec.probe(s08), 1.0)
        s09 = (SAMPLES / "s09.dat").read_bytes()
        self.assertEqual(self.dec.probe(s09), 1.0)
        s10 = (SAMPLES / "s10.dat").read_bytes()
        self.assertEqual(self.dec.probe(s10), 1.0)

    def test_decode_s08(self):
        data = (SAMPLES / "s08.dat").read_bytes()
        result = self.dec.decode(SafeReader(data))

        self.assertEqual(result.format, "VAULT")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.meta["entry_count"], 3)
        self.assertEqual(result.meta["xor_key"], 32)
        self.assertEqual(result.meta["flags"], 0)
        self.assertEqual(len(result.damage), 0)
        self.assertEqual(len(result.records), 3)

        # Record 0
        r0 = result.records[0]
        self.assertEqual(r0.status, Status.VERIFIED)
        f0 = {f.name: f.value for f in r0.fields}
        self.assertEqual(f0["id"], 30574)
        self.assertEqual(f0["name"], "report.txt")
        self.assertEqual(f0["type"], "text")
        self.assertEqual(f0["size"], 149)
        self.assertEqual(f0["sha256"], "cc395ca4c42f1f1110b99a0dfb6f23725fa86190685bdecff362c51abf1fced9")
        self.assertTrue(f0["compressed"])
        self.assertTrue(f0["text"].startswith("Grade report - Term 3"))

        # Record 1
        r1 = result.records[1]
        self.assertEqual(r1.status, Status.VERIFIED)
        f1 = {f.name: f.value for f in r1.fields}
        self.assertEqual(f1["id"], 30577)
        self.assertEqual(f1["name"], "notes.txt")
        self.assertEqual(f1["type"], "text")
        self.assertEqual(f1["size"], 20)
        self.assertEqual(f1["sha256"], "f952b067f384c06988d09477ba06cf21834d031d66ae196a64be9a9a0b742b0a")
        self.assertFalse(f1["compressed"])
        self.assertEqual(f1["text"], "Remember: buy chalk.")

        # Record 2
        r2 = result.records[2]
        self.assertEqual(r2.status, Status.VERIFIED)
        f2 = {f.name: f.value for f in r2.fields}
        self.assertEqual(f2["id"], 30580)
        self.assertEqual(f2["name"], "logo.bin")
        self.assertEqual(f2["type"], "binary")
        self.assertEqual(f2["size"], 20)
        self.assertEqual(f2["sha256"], "98afdedaf84aeb6ac455d27f31de2ed07f24da3e9bba43788164068bcd91dfa2")
        self.assertFalse(f2["compressed"])
        self.assertNotIn("text", f2)

    def test_decode_s09(self):
        data = (SAMPLES / "s09.dat").read_bytes()
        result = self.dec.decode(SafeReader(data))

        self.assertEqual(result.format, "VAULT")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.meta["entry_count"], 3)
        self.assertEqual(result.meta["xor_key"], 252)
        self.assertEqual(result.meta["flags"], 1)
        self.assertEqual(len(result.damage), 0)
        self.assertEqual(len(result.records), 3)

        # Record 0: edge.bin (binary, ARC RLE compressed)
        f0 = {f.name: f.value for f in result.records[0].fields}
        self.assertEqual(f0["name"], "edge.bin")
        self.assertEqual(f0["type"], "binary")
        self.assertEqual(f0["size"], 822)
        self.assertTrue(f0["compressed"])

        # Record 1: icon.bmp8 (bitmap, ARC RLE compressed)
        f1 = {f.name: f.value for f in result.records[1].fields}
        self.assertEqual(f1["name"], "icon.bmp8")
        self.assertEqual(f1["type"], "bitmap")
        self.assertEqual(f1["size"], 130)
        self.assertEqual(f1["width"], 16)
        self.assertEqual(f1["height"], 8)

        # Record 2: unicode.txt (text, UTF-8)
        f2 = {f.name: f.value for f in result.records[2].fields}
        self.assertEqual(f2["name"], "unicode.txt")
        self.assertEqual(f2["type"], "text")
        self.assertEqual(f2["text"], "Müller – Zürich ✓ room 12")

    def test_decode_s10_corruption(self):
        data = (SAMPLES / "s10.dat").read_bytes()
        result = self.dec.decode(SafeReader(data))

        self.assertEqual(result.format, "VAULT")
        self.assertEqual(len(result.records), 3)

        # Record 0: report.txt (verified)
        self.assertEqual(result.records[0].status, Status.VERIFIED)

        # Record 1: sensor.bin (CRC mismatch intentional test damage)
        r1 = result.records[1]
        self.assertEqual(r1.status, Status.UNVERIFIED)
        self.assertIn(DamageKind.CRC_MISMATCH, r1.issues)
        f1 = {f.name: f.value for f in r1.fields}
        self.assertEqual(f1["name"], "sensor.bin")
        self.assertEqual(f1["type"], "binary")

        # Damage reported
        crc_damages = [d for d in result.damage if d.kind == DamageKind.CRC_MISMATCH]
        self.assertEqual(len(crc_damages), 1)
        self.assertEqual(crc_damages[0].start, 175)
        self.assertFalse(crc_damages[0].lossy)

        # Record 2: icon.bmp8 (verified)
        self.assertEqual(result.records[2].status, Status.VERIFIED)

    def test_hostile_and_malformed_inputs(self):
        # Truncated magic
        res = self.dec.decode(SafeReader(b"VLT"))
        self.assertEqual(res.confidence, 0.0)

        # Truncated header
        res = self.dec.decode(SafeReader(b"VLT1\x01\x00"))
        self.assertTrue(any(d.kind == DamageKind.TRUNCATED for d in res.damage))

        # Random bytes
        res = self.dec.decode(SafeReader(bytes(100)))
        self.assertEqual(res.confidence, 0.0)

        # Fuzzed s08
        s08 = bytearray((SAMPLES / "s08.dat").read_bytes())
        s08[4:6] = b"\xff\xff"  # Impossible entry count
        res = self.dec.decode(SafeReader(bytes(s08)))
        self.assertTrue(any(d.kind == DamageKind.TRUNCATED for d in res.damage))


if __name__ == "__main__":
    unittest.main()
