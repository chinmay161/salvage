import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from salvage.core.model import DamageKind, Status
from salvage.core.reader import SafeReader
from salvage.formats.stub import MAGIC, StubDecoder

ROOT = Path(__file__).resolve().parents[2]


def stub_bytes(values: list[int], count: int | None = None) -> bytes:
    count = len(values) if count is None else count
    return MAGIC + struct.pack(f"<H{len(values)}I", count, *values)


def decode(data: bytes):
    return StubDecoder().decode(SafeReader(data))


def values_of(result) -> list[int]:
    return [f.value for r in result.records if r.kind == "value" for f in r.fields]


class StubTests(unittest.TestCase):
    def test_probe(self):
        d = StubDecoder()
        self.assertEqual(d.probe(stub_bytes([1])), 1.0)
        self.assertEqual(d.probe(b"SALVAGE-STU"), 0.0)
        self.assertEqual(d.probe(b"PK\x03\x04"), 0.0)

    def test_round_trip(self):
        for values in [[], [1], [0, 0xFFFFFFFF, 12345, 7]]:
            with self.subTest(values=values):
                data = stub_bytes(values)
                result = decode(data)
                self.assertEqual(result.validate(len(data)), [])
                self.assertEqual(result.damage, [])
                self.assertEqual(values_of(result), values)
                self.assertEqual(StubDecoder().encode(result), data)
        self.assertTrue(StubDecoder.can_encode())

    def test_statuses(self):
        result = decode(stub_bytes([5, 6]))
        header = result.records[0]
        magic, count = header.fields
        self.assertEqual(magic.status, Status.VERIFIED)
        self.assertEqual(magic.evidence, "exact magic match")
        self.assertEqual(count.status, Status.CONSISTENT)
        self.assertEqual((count.offset, count.length), (13, 2))
        values = result.records[1:]
        self.assertEqual(len(values), 2)
        for i, rec in enumerate(values):
            self.assertEqual(rec.status, Status.UNVERIFIED)
            self.assertEqual(rec.fields[0].status, Status.UNVERIFIED)
            self.assertEqual(rec.fields[0].offset, 15 + 4 * i)

    def test_truncated(self):
        full = stub_bytes([10, 20, 30])
        data = full[:-2]                        # last value cut in half
        result = decode(data)
        self.assertEqual(values_of(result), [10, 20])
        self.assertEqual(result.records[0].fields[1].status, Status.UNVERIFIED)
        self.assertEqual(len(result.damage), 1)
        dmg = result.damage[0]
        self.assertEqual(dmg.kind, DamageKind.TRUNCATED)
        self.assertEqual((dmg.start, dmg.end), (15 + 8, len(data)))
        self.assertTrue(result.warnings)
        self.assertEqual(result.validate(len(data)), [])

    def test_truncated_inside_count(self):
        data = MAGIC + b"\x02"
        result = decode(data)
        self.assertEqual(values_of(result), [])
        self.assertEqual([(d.start, d.end, d.kind) for d in result.damage],
                         [(13, 14, DamageKind.TRUNCATED)])
        self.assertEqual(result.validate(len(data)), [])

    def test_trailing_bytes_reported(self):
        data = stub_bytes([1]) + b"xyz"
        result = decode(data)
        self.assertEqual(values_of(result), [1])
        self.assertEqual([(d.start, d.end, d.kind) for d in result.damage],
                         [(19, 22, DamageKind.UNPARSED)])
        self.assertEqual(result.validate(len(data)), [])

    def test_wrong_magic(self):
        for data in [b"", b"hello world, not a stub", MAGIC[:-1]]:
            with self.subTest(data=data):
                result = decode(data)
                self.assertEqual(result.confidence, 0.0)
                self.assertEqual((result.records, result.damage, result.members), ([], [], []))
                self.assertEqual(result.validate(len(data)), [])

    def test_deterministic_json(self):
        data = stub_bytes([3, 1, 4])
        self.assertEqual(json.dumps(decode(data).to_dict()), json.dumps(decode(data).to_dict()))

    def test_standalone_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.stub")
            with open(path, "wb") as fh:
                fh.write(stub_bytes([1, 2, 3])[:-1])
            proc = subprocess.run([sys.executable, "-m", "salvage.formats.stub", path],
                                  cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["format"], "STUB")
            self.assertEqual(out["damage"][0]["kind"], "truncated")

            missing = subprocess.run(
                [sys.executable, "-m", "salvage.formats.stub", os.path.join(tmp, "nope")],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(missing.returncode, 0)
            self.assertEqual(missing.stdout, "")
            self.assertIn("cannot read", missing.stderr)

            usage = subprocess.run([sys.executable, "-m", "salvage.formats.stub"],
                                   cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(usage.returncode, 0)
            self.assertIn("usage", usage.stderr)


if __name__ == "__main__":
    unittest.main()
