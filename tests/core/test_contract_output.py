"""Phase 7: the per-file output follows the organizers' contract (D1-D3)."""

import unittest

from salvagekit.core import emit, isolate, report, validate
from salvagekit.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                   Status)
from salvagekit.core.plugin import Decoder


def rec(*fields, status=Status.CONSISTENT, issues=()):
    return Record(0, status, fields=[Field(n, v, 0, 1, s) for n, v, s in fields],
                  issues=list(issues))


C, V, U, L = Status.CONSISTENT, Status.VERIFIED, Status.UNVERIFIED, Status.LOST


class RecordObjectTests(unittest.TestCase):
    def test_flat_object_in_field_order(self):
        r = rec(("id", 7, V), ("title", "Emma", C), ("due_date", None, C))
        self.assertEqual(list(emit.record_object(r).items()),
                         [("id", 7), ("title", "Emma"), ("due_date", None)])

    def test_verified_false_only_for_unverified_or_lost(self):
        self.assertNotIn("verified", emit.record_object(rec(("a", 1, V), status=V)))
        self.assertNotIn("verified", emit.record_object(rec(("a", 1, C))))
        self.assertIs(emit.record_object(rec(("a", 1, C), status=U))["verified"], False)
        self.assertIs(emit.record_object(rec(("a", 1, C), ("b", None, L)))["verified"], False)
        self.assertIs(emit.record_object(rec(("a", 1, U)))["verified"], False)

    def test_issues_deduplicated_in_order_and_last(self):
        r = rec(("a", 1, U), status=U, issues=[DamageKind.CRC_MISMATCH, DamageKind.TRUNCATED,
                                               DamageKind.CRC_MISMATCH])
        self.assertEqual(list(emit.record_object(r).items()),
                         [("a", 1), ("verified", False),
                          ("issues", ["crc_mismatch", "truncated"])])
        self.assertNotIn("issues", emit.record_object(rec(("a", 1, C))))

    def test_values_json_safe_and_dicts_sorted(self):
        r = rec(("raw", b"\x01\xff", C), ("m", {"z": 1, "a": {"y": 2, "b": 3}}, C))
        obj = emit.record_object(r)
        self.assertEqual(obj["raw"], "01ff")
        self.assertEqual(list(obj["m"]), ["a", "z"])
        self.assertEqual(list(obj["m"]["a"]), ["b", "y"])


class ToOutputTests(unittest.TestCase):
    def test_damage_mapping_includes_members_but_not_member_records(self):
        member = DecodeResult("X", 1.0, name="a.txt", records=[rec(("text", "hi", V))],
                              damage=[Damage(40, 50, DamageKind.CRC_MISMATCH, "member crc",
                                             lossy=False)])
        res = DecodeResult("VAULT", 1.0, records=[rec(("name", "a.txt", C))], members=[member],
                           damage=[Damage(3, 9, DamageKind.TRUNCATED, "cut")],
                           meta={"z": 1, "a": 2})
        out = emit.to_output(source_file="v.dat", fmt="VAULT", status="partial", result=res)
        self.assertEqual(list(out), ["source_file", "format", "status", "metadata", "records",
                                     "damage"])
        self.assertEqual(out["records"], [{"name": "a.txt"}])
        self.assertEqual(out["damage"], [
            {"kind": "truncated", "offset": 3, "detail": "cut", "lossy": True},
            {"kind": "crc_mismatch", "offset": 40, "detail": "member crc", "lossy": False}])
        self.assertEqual(list(out["metadata"]), ["a", "z"])
        self.assertEqual(validate.errors("output", out), [])

    def test_no_result(self):
        self.assertEqual(emit.to_output(source_file="x", fmt="UNKNOWN", status="failed"),
                         {"source_file": "x", "format": "UNKNOWN", "status": "failed",
                          "metadata": {}, "records": [], "damage": []})


class FileStatusTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(report.file_status(DecodeResult("X", 1.0, records=[
            rec(("a", 1, V), status=V), rec(("b", 2, C))])), "ok")
        self.assertEqual(report.file_status(DecodeResult("X", 1.0)), "ok")

    def test_partial(self):
        for why, res in (
                ("damage", DecodeResult("X", 1.0, damage=[Damage(0, 0, DamageKind.TRUNCATED, "")])),
                ("unverified field", DecodeResult("X", 1.0, records=[rec(("a", 1, U))])),
                ("unverified record", DecodeResult("X", 1.0, records=[rec(status=U)])),
                ("lost field", DecodeResult("X", 1.0, records=[rec(("a", None, L))])),
                ("member", DecodeResult("X", 1.0, members=[
                    DecodeResult("Y", 1.0, records=[rec(("a", None, L))])])),
                ("non-lossy damage", DecodeResult("X", 1.0, damage=[
                    Damage(0, 1, DamageKind.UNPARSED_BYTES, "", lossy=False)]))):
            with self.subTest(why=why):
                self.assertEqual(report.file_status(res), "partial")

    def test_unsupported_wins(self):
        res = DecodeResult("WPD", 1.0, unsupported=True,
                           damage=[Damage(0, 10, DamageKind.ENCRYPTED, "password")])
        self.assertEqual(report.file_status(res), "unsupported")


class _Encrypted(Decoder):
    name = "WPD"

    def probe(self, data):
        return 1.0 if data.startswith(b"ENC") else 0.0

    def decode(self, reader):
        reader.bytes(3, "magic")
        return DecodeResult(self.name, 1.0, unsupported=True, meta={"encrypted": True},
                            damage=[Damage(3, reader.size, DamageKind.ENCRYPTED,
                                           "password-protected")])


class _Also(Decoder):
    name = "BRAVO"

    def probe(self, data):
        return 0.6 if data.startswith(b"ENC") else 0.0   # tried second (outside the margin)

    def decode(self, reader):
        reader.bytes(3, "magic")
        return DecodeResult(self.name, 1.0, records=[rec(("index", 0, C), ("text", "x", C))])


class UnsupportedPipelineTests(unittest.TestCase):
    def test_unsupported_result_stops_and_is_emitted(self):
        p = isolate.process_data("s14.wpd", b"ENC" + bytes(20), [_Encrypted(), _Also()])
        out, entry = p["output"], p["entry"]
        self.assertEqual(out, {"source_file": "s14.wpd", "format": "WPD",
                               "status": "unsupported", "metadata": {"encrypted": True},
                               "records": [],
                               "damage": [{"kind": "encrypted", "offset": 3,
                                           "detail": "password-protected", "lossy": True}]})
        self.assertEqual(entry["attempts"], [{"format": "WPD", "outcome": "unsupported"}])
        self.assertEqual(validate.errors("output", out), [])


if __name__ == "__main__":
    unittest.main()
