"""Keeps docs/decoder-template.py working: run it through the pipeline machinery."""

import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from salvage.core import isolate, report, validate
from salvage.core.model import Status
from salvage.core.reader import SafeReader

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
    rep["files"].append(payload["entry"])
    report.summarize(rep)
    payload["report"] = rep
    return payload


class TemplateTests(unittest.TestCase):
    def assertValid(self, payload):
        self.assertEqual(validate.errors("output", payload["output"]), [])
        self.assertEqual(validate.errors("report", payload["report"]), [])

    def test_not_discoverable_or_shipped(self):
        self.assertFalse((ROOT / "salvage" / "formats" / "decoder-template.py").exists())
        self.assertEqual(T.ExampleDecoder.name, "EXAMPLE")

    def test_clean_file(self):
        p = run(CLEAN)
        self.assertValid(p)
        out, entry = p["output"], p["entry"]
        self.assertEqual((out["status"], out["format"], out["variant"], out["confidence"]),
                         ("decoded", "EXAMPLE", "EXAMPLE v2", 1.0))
        self.assertEqual([r["fields"][0]["value"] for r in out["records"][1:]],
                         ["alpha", "beta", "γάμμα"])
        self.assertTrue(all(r["status"] == "verified" for r in out["records"][1:]))
        self.assertIn("CRC-16/XMODEM", out["records"][1]["fields"][0]["evidence"])
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
        out = p["output"]
        self.assertEqual((out["status"], out["variant"]), ("partial", "EXAMPLE v1"))
        texts = [(r["fields"][0]["value"], r["status"]) for r in out["records"][1:]]
        self.assertEqual(texts, [("alpha", "verified"), ("beta", "unverified"),
                                 ("gamma", "verified")])
        o_bad = 16 + len(good)
        o_junk = o_bad + len(bad)
        o_tail = o_junk + len(junk) + len(record("gamma"))
        self.assertEqual([(d["kind"], d["start"], d["end"]) for d in out["damage"]], [
            ("checksum", o_bad, o_junk),
            ("unparsed", o_junk, o_junk + len(junk)),
            ("truncated", o_tail, len(data)),
        ])
        count = out["records"][0]["fields"][2]
        self.assertEqual((count["name"], count["status"]), ("count", "unverified"))
        self.assertEqual(p["entry"]["coverage"]["unexplained"],
                         [[o_junk, o_junk + len(junk)], [o_tail, len(data)]])

    def test_nonzero_reserved_is_not_padding(self):
        p = run(example(2, 1, record("a"), padding=b"\x01" + bytes(7)))
        self.assertValid(p)
        self.assertEqual(p["entry"]["coverage"]["bytes_padding"], 0)
        names = [f["name"] for f in p["output"]["records"][0]["fields"]]
        self.assertIn("reserved", names)

    def test_truncated_header_and_garbage(self):
        for data in (T.MAGIC, T.MAGIC + b"\x02", T.MAGIC + b"\x02\x00\x01\x00\x00",
                     T.MAGIC + bytes(100), b"EXMP" + bytes(12) + b"\xA5\x5A\xff\xff"):
            with self.subTest(data=data[:20]):
                p = run(data)
                self.assertValid(p)
                self.assertIn(p["output"]["status"], ("partial", "decoded"))

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
