"""Unit tests for LABLOG format decoder."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from salvage.core.model import DamageKind, Status
from salvage.core.reader import SafeReader
from salvage.formats.lablog import LablogDecoder, crc16_ccitt

CASES_DIR = Path(__file__).resolve().parent / "cases"
KIT_SAMPLES = Path(__file__).resolve().parent.parent.parent / "kit" / "samples"
EXPECTED_OUTPUTS = Path(__file__).resolve().parent.parent.parent / "kit" / "expected_outputs"


class LablogDecoderTests(unittest.TestCase):
    def setUp(self):
        self.decoder = LablogDecoder()

    def test_probe_valid_file(self):
        clean = (CASES_DIR / "clean.dat").read_bytes()
        self.assertEqual(self.decoder.probe(clean), 1.0)
        s05 = (KIT_SAMPLES / "s05.dat").read_bytes()
        self.assertEqual(self.decoder.probe(s05), 1.0)

    def test_probe_short_or_invalid(self):
        self.assertEqual(self.decoder.probe(b""), 0.0)
        self.assertEqual(self.decoder.probe(b"LLOG"), 0.0)
        self.assertEqual(self.decoder.probe(b"LLOG" + b"\x00" * 20), 0.0)
        self.assertEqual(self.decoder.probe(b"XXXX" + b"\x00" * 28), 0.0)
        # Unsupported version or 0 channels
        bad_ver = bytearray((CASES_DIR / "clean.dat").read_bytes())
        bad_ver[4] = 2
        self.assertEqual(self.decoder.probe(bad_ver), 0.2)
        zero_ch = bytearray((CASES_DIR / "clean.dat").read_bytes())
        zero_ch[5] = 0
        self.assertEqual(self.decoder.probe(zero_ch), 0.2)
        # Valid header but corrupted header CRC
        bad_crc = bytearray((CASES_DIR / "clean.dat").read_bytes())
        bad_crc[30] ^= 0xFF
        self.assertEqual(self.decoder.probe(bad_crc), 0.8)

    def test_decode_short_header(self):
        res = self.decoder.decode(SafeReader(b"LLOG\x01\x02"))
        self.assertEqual(res.format, "LABLOG")
        self.assertTrue(any(d.kind == DamageKind.TRUNCATED for d in res.damage))
        self.assertIn("header truncated", res.warnings)

    def test_decode_unsupported_version(self):
        raw = bytearray((CASES_DIR / "clean.dat").read_bytes())
        raw[4] = 99
        # Update header CRC so header CRC is valid
        hdr_crc = crc16_ccitt(raw[:30])
        struct.pack_into("<H", raw, 30, hdr_crc)
        res = self.decoder.decode(SafeReader(bytes(raw)))
        self.assertTrue(any(d.kind == DamageKind.OTHER and "unsupported" in d.reason for d in res.damage))
        self.assertTrue(any("unsupported" in w for w in res.warnings))

    def test_decode_zero_channels(self):
        raw = bytearray((CASES_DIR / "clean.dat").read_bytes())
        raw[5] = 0
        hdr_crc = crc16_ccitt(raw[:30])
        struct.pack_into("<H", raw, 30, hdr_crc)
        res = self.decoder.decode(SafeReader(bytes(raw)))
        self.assertTrue(any(d.kind == DamageKind.BOUNDS and "invalid channel count" in d.reason for d in res.damage))

    def test_decode_header_crc_mismatch(self):
        raw = bytearray((CASES_DIR / "clean.dat").read_bytes())
        raw[30] ^= 0x55
        res = self.decoder.decode(SafeReader(bytes(raw)))
        self.assertTrue(any(d.kind == DamageKind.CHECKSUM and "header CRC mismatch" in d.reason for d in res.damage))
        self.assertIn("header CRC mismatch", res.warnings)

    def test_decode_clean_case(self):
        clean = (CASES_DIR / "clean.dat").read_bytes()
        res = self.decoder.decode(SafeReader(clean))
        self.assertEqual(res.format, "LABLOG")
        self.assertEqual(res.confidence, 1.0)
        self.assertEqual(res.meta["version"], 1)
        self.assertEqual(res.meta["instrument"], "THERMO LOGGER")
        self.assertEqual(res.meta["sample_interval_ms"], 500)
        self.assertEqual(res.meta["start_time_utc"], "1992-10-11T05:07:43Z")
        self.assertEqual(res.meta["declared_block_count"], 3)
        self.assertEqual(len(res.meta["channels"]), 1)
        self.assertEqual(res.meta["channels"][0], {"index": 0, "unit": "mV"})
        self.assertEqual(len(res.meta["events"]), 1)
        self.assertEqual(res.meta["events"][0], {"sample": 0, "severity": 1, "message": "Test start"})

        self.assertEqual(len(res.records), 2)
        # Sample 0
        r0 = res.records[0]
        self.assertEqual(r0.status, Status.VERIFIED)
        f0 = {f.name: f.value for f in r0.fields}
        self.assertEqual(f0["sample"], 0)
        self.assertEqual(f0["time_ms"], 0)
        self.assertEqual(f0["values"], [150.0])

        # Sample 1 (dropout)
        r1 = res.records[1]
        self.assertEqual(r1.status, Status.VERIFIED)
        f1 = {f.name: f.value for f in r1.fields}
        self.assertEqual(f1["sample"], 1)
        self.assertEqual(f1["time_ms"], 500)
        self.assertEqual(f1["values"], [None])

    def test_decode_bad_block_crc(self):
        bad = (CASES_DIR / "bad_crc.dat").read_bytes()
        res = self.decoder.decode(SafeReader(bad))
        self.assertEqual(len(res.records), 2)
        # Records in damaged block should be UNVERIFIED
        for rec in res.records:
            self.assertEqual(rec.status, Status.UNVERIFIED)
        self.assertTrue(any(d.kind == DamageKind.CHECKSUM for d in res.damage))

    def test_decode_truncated_block(self):
        trunc = (CASES_DIR / "truncated.dat").read_bytes()
        res = self.decoder.decode(SafeReader(trunc))
        self.assertTrue(any(d.kind == DamageKind.TRUNCATED for d in res.damage))

    def test_decode_invalid_block_lengths_and_types(self):
        clean = (CASES_DIR / "clean.dat").read_bytes()
        # Insert unknown block type 0x09
        bad_type = bytearray(clean)
        bad_type[33] = 0x09  # block 1 type
        # recalculate block 1 CRC
        b_span = bad_type[33:48]
        b_crc = crc16_ccitt(b_span)
        struct.pack_into("<H", bad_type, 48, b_crc)
        res = self.decoder.decode(SafeReader(bytes(bad_type)))
        self.assertTrue(any(d.kind == DamageKind.UNPARSED and "unknown block type" in d.reason for d in res.damage))

    def test_decode_resync_on_junk(self):
        clean = (CASES_DIR / "clean.dat").read_bytes()
        # Corrupt marker of Block 2 (offset 50) to 0xFF followed by junk
        corrupted = clean[:50] + b"\xff\xff\xee\xdd\xcc" + clean[50:]
        res = self.decoder.decode(SafeReader(corrupted))
        self.assertTrue(any(d.kind == DamageKind.UNPARSED for d in res.damage))
        # After resyncing, the intact Block 2 and Block 3 should still be decoded
        self.assertEqual(len(res.records), 2)
        self.assertEqual(len(res.meta["events"]), 1)

    def test_verify_official_s05_reference(self):
        s05_bytes = (KIT_SAMPLES / "s05.dat").read_bytes()
        res = self.decoder.decode(SafeReader(s05_bytes))
        expected_json = json.loads((EXPECTED_OUTPUTS / "s05.dat.json").read_text())

        # Verify metadata
        exp_meta = expected_json["metadata"]
        self.assertEqual(res.meta["version"], exp_meta["version"])
        self.assertEqual(res.meta["instrument"], exp_meta["instrument"])
        self.assertEqual(res.meta["sample_interval_ms"], exp_meta["sample_interval_ms"])
        self.assertEqual(res.meta["channels"], exp_meta["channels"])
        self.assertEqual(res.meta["start_time_utc"], exp_meta["start_time_utc"])
        self.assertEqual(res.meta["declared_block_count"], exp_meta["declared_block_count"])
        self.assertEqual(res.meta["events"], exp_meta["events"])

        # Verify records
        exp_records = expected_json["records"]
        self.assertEqual(len(res.records), len(exp_records))
        for i, (rec, exp_rec) in enumerate(zip(res.records, exp_records)):
            fmap = {f.name: f.value for f in rec.fields}
            self.assertEqual(fmap["sample"], exp_rec["sample"], f"sample mismatch at {i}")
            self.assertEqual(fmap["time_ms"], exp_rec["time_ms"], f"time_ms mismatch at {i}")
            self.assertEqual(fmap["values"], exp_rec["values"], f"values mismatch at {i}")
            self.assertEqual(rec.status, Status.VERIFIED)

        # Clean file has 0 damage
        self.assertEqual(res.damage, [])
        self.assertEqual(res.confidence, 1.0)

    def test_s06_dropouts(self):
        s06_bytes = (KIT_SAMPLES / "s06.dat").read_bytes()
        res = self.decoder.decode(SafeReader(s06_bytes))
        self.assertEqual(res.format, "LABLOG")
        self.assertEqual(res.confidence, 1.0)
        self.assertEqual(res.meta["instrument"], "FLOWCELL-2")
        self.assertEqual(len(res.records), 25)
        # Samples with dropouts: 0, 6, 11, 12, 19, 23
        for s_idx in (0, 6, 11, 12, 19, 23):
            rec = res.records[s_idx]
            vals = [f.value for f in rec.fields if f.name == "values"][0]
            self.assertIn(None, vals, f"Sample {s_idx} expected dropout")

    def test_s07_damage_handling(self):
        s07_bytes = (KIT_SAMPLES / "s07.dat").read_bytes()
        res = self.decoder.decode(SafeReader(s07_bytes))
        self.assertEqual(res.format, "LABLOG")
        self.assertEqual(len(res.records), 28)
        # Block 5 CRC mismatch reported
        crc_damages = [d for d in res.damage if d.kind == DamageKind.CHECKSUM and "block 4 CRC mismatch" in d.reason]
        self.assertTrue(crc_damages, "Expected CHECKSUM damage for Block 5")
        # Records in Block 5 (samples 9..14) must be UNVERIFIED
        for s_idx in range(9, 15):
            self.assertEqual(res.records[s_idx].status, Status.UNVERIFIED, f"Sample {s_idx} should be unverified")
        # Records in other blocks must be VERIFIED
        for s_idx in list(range(0, 9)) + list(range(15, 28)):
            self.assertEqual(res.records[s_idx].status, Status.VERIFIED, f"Sample {s_idx} should be verified")


if __name__ == "__main__":
    unittest.main()
