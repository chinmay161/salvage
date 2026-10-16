"""Keeps docs/decoder-template.py working: run it through the pipeline machinery."""

import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from salvagekit.core import isolate, report, validate
from salvagekit.core.model import Status
from salvagekit.core.reader import SafeReader

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docs" / "decoder-template.py"


def load_template():
    spec = importlib.util.spec_from_file_location("decoder_template", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T = load_template()


def record(text: str, bad_crc: bool = False) -> bytes:
    payload = text.encode("utf-8")
    crc = T.crc16(payload) ^ (0xFFFF if bad_crc else 0)
    return T.MARKER + struct.pack("<H", len(payload)) + payload + struct.pack("<H", crc)


def example(version: int, count: int, *records: bytes, padding: bytes = bytes(8)) -> bytes:
    return T.MAGIC + struct.pack("<HH", version, count) + padding + b"".join(records)


CLEAN = example(2, 3, record("alpha"), record("beta"), record("γάμμα"))


def run(data: bytes, name: str = "f.exmp") -> dict:
    payload = isolate.process_data(name, data, [T.ExampleDecoder()])
    rep = report.new_report()
    payload["entry"]["output"] = name + ".json"
    rep["files"].append(report.file_row(payload["output"]))
    rep["diagnostics"]["files"].append(payload["entry"])
    report.summarize(rep)
    payload["report"] = rep
    return payload


class TemplateTests(unittest.TestCase):
    def assertValid(self, payload):
        self.assertEqual(validate.errors("output", payload["output"]), [])
        self.assertEqual(validate.errors("report", payload["report"]), [])

    def test_not_discoverable_or_shipped(self):
        self.assertFalse((ROOT / "salvagekit" / "formats" / "decoder-template.py").exists())
        self.assertEqual(T.ExampleDecoder.name, "EXAMPLE")

    def test_clean_file(self):
        p = run(CLEAN)
        self.assertValid(p)
        out, entry = p["output"], p["entry"]
        self.assertEqual((out["status"], out["format"]), ("ok", "EXAMPLE"))
        self.assertEqual((entry["variant"], entry["confidence"]), ("EXAMPLE v2", 1.0))
        self.assertEqual(out["metadata"], {"declared_count": 3, "version": 2})
        self.assertEqual(out["records"], [{"index": 0, "text": "alpha"},
                                          {"index": 1, "text": "beta"},
                                          {"index": 2, "text": "γάμμα"}])
        result = T.ExampleDecoder().decode(SafeReader(CLEAN))
        self.assertTrue(all(r.status == Status.VERIFIED for r in result.records))
        self.assertIn("CRC-16/XMODEM", result.records[0].fields[1].evidence)
        cov = entry["coverage"]
        self.assertEqual((cov["accounted_pct"], cov["unexplained"], cov["bytes_padding"]),
                         (100.0, [], 8))
        self.assertEqual(cov["bytes_explained"], len(CLEAN) - 8)
        self.assertEqual(out["damage"], [])

    def test_round_trip(self):
        dec = T.ExampleDecoder()
        result = dec.decode(SafeReader(CLEAN))
        self.assertEqual(dec.encode(result), CLEAN)

    def test_damaged_file(self):
        good, bad = record("alpha"), record("beta", bad_crc=True)
        junk = b"\x00JUNK\xA5"
        tail = record("delta")[:7]
        data = example(1, 5, good, bad, junk, record("gamma"), tail)
        p = run(data)
        self.assertValid(p)
        out, entry = p["output"], p["entry"]
        self.assertEqual((out["status"], entry["variant"]), ("partial", "EXAMPLE v1"))
        self.assertEqual(out["records"], [
            {"index": 0, "text": "alpha"},
            {"index": 1, "text": "beta", "verified": False, "issues": ["crc_mismatch"]},
            {"index": 2, "text": "gamma"}])
        o_bad = 16 + len(good)
        o_junk = o_bad + len(bad)
        o_tail = o_junk + len(junk) + len(record("gamma"))
        self.assertEqual([(d["kind"], d["offset"], d["lossy"]) for d in out["damage"]], [
            ("crc_mismatch", o_bad, False),
            ("unparsed_bytes", o_junk, True),
            ("truncated", o_tail, True),
        ])
        self.assertEqual([(d["start"], d["end"]) for d in entry["damage"]],
                         [(o_bad, o_junk), (o_junk, o_junk + len(junk)), (o_tail, len(data))])
        self.assertEqual(entry["coverage"]["unexplained"],
                         [[o_junk, o_junk + len(junk)], [o_tail, len(data)]])

    def test_count_mismatch_only_when_nothing_else_explains_it(self):
        p = run(example(2, 3, record("a"), record("b")))   # ends cleanly after 2 of 3
        self.assertValid(p)
        self.assertEqual(p["output"]["damage"], [{
            "kind": "count_mismatch", "offset": 6, "detail": "header says 3, 2 records found",
            "lossy": True}])
        self.assertEqual(p["output"]["status"], "partial")

    def test_nonzero_reserved_is_not_padding(self):
        p = run(example(2, 1, record("a"), padding=b"\x01" + bytes(7)))
        self.assertValid(p)
        self.assertEqual(p["entry"]["coverage"]["bytes_padding"], 0)
        self.assertEqual(p["output"]["metadata"]["reserved"], "01" + "00" * 7)

    def test_truncated_header_and_garbage(self):
        for data in (T.MAGIC, T.MAGIC + b"\x02", T.MAGIC + b"\x02\x00\x01\x00\x00",
                     T.MAGIC + bytes(100), b"EXMP" + bytes(12) + b"\xA5\x5A\xff\xff"):
            with self.subTest(data=data[:20]):
                p = run(data)
                self.assertValid(p)
                self.assertIn(p["output"]["status"], ("partial", "ok"))

    def test_probe(self):
        dec = T.ExampleDecoder()
        self.assertEqual(dec.probe(CLEAN), 1.0)
        self.assertEqual(dec.probe(example(9, 0)), 0.6)
        self.assertEqual(dec.probe(b"nope"), 0.0)
        self.assertEqual(dec.probe(None), 0.0)
        self.assertEqual(Status.worst([]), Status.UNVERIFIED)

    def test_runs_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.exmp")
            with open(path, "wb") as fh:
                fh.write(CLEAN)
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            proc = subprocess.run([sys.executable, str(TEMPLATE), path], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"format": "EXAMPLE v2"', proc.stdout)


if __name__ == "__main__":
    unittest.main()
