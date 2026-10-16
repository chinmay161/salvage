import json
import unittest
from enum import Enum

from salvagekit.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                Status, json_safe)


def sample_result() -> DecodeResult:
    member = DecodeResult(
        format="INNER", confidence=0.5, name="a.txt",
        records=[Record(4, Status.CONSISTENT, fields=[Field("x", 1, 4, 2, Status.CONSISTENT)])])
    return DecodeResult(
        format="TEST", confidence=0.9,
        records=[Record(0, Status.VERIFIED, kind="header", fields=[
            Field("magic", b"\xAB\xCD", 0, 2, Status.VERIFIED, "exact magic match"),
            Field("ratio", float("nan"), 2, 4, Status.UNVERIFIED),
        ])],
        members=[member],
        damage=[Damage(6, 10, DamageKind.TRUNCATED, "short")],
        meta={"k": (1, 2), 3: "three"},
        warnings=["w"],
    )


class StatusTests(unittest.TestCase):
    def test_values_and_rank(self):
        self.assertEqual(Status.VERIFIED.value, "verified")
        self.assertEqual([s.rank for s in Status], [3, 2, 1, 0])

    def test_worst(self):
        self.assertEqual(Status.worst([]), Status.UNVERIFIED)
        self.assertEqual(Status.worst([Status.VERIFIED]), Status.VERIFIED)
        self.assertEqual(Status.worst([Status.VERIFIED, Status.CONSISTENT]), Status.CONSISTENT)
        self.assertEqual(Status.worst([Status.CONSISTENT, Status.LOST, Status.VERIFIED]),
                         Status.LOST)
        self.assertEqual(Status.worst(iter([Status.UNVERIFIED, Status.VERIFIED])),
                         Status.UNVERIFIED)

    def test_damage_kind_values(self):
        # Exactly the output contract's vocabulary, in its order.
        self.assertEqual([k.value for k in DamageKind], [
            "truncated", "crc_mismatch", "checksum_mismatch", "bad_length", "unparsed_bytes",
            "count_mismatch", "invalid_value", "oob_pointer", "index_missing",
            "header_checksum", "encrypted", "unknown_record"])

    def test_damage_kinds_match_the_official_schemas(self):
        import os
        from salvagekit.core import validate
        kinds = [k.value for k in DamageKind]
        for rel in validate.SCHEMA_FILES.values():
            with open(os.path.join(validate.SCHEMA_DIR, *rel.split("/")),
                      encoding="utf-8") as fh:
                schema = json.load(fh)
            found = schema["$defs"].get("kind") or schema["$defs"]["damage"]["properties"]["kind"]
            self.assertEqual(found["enum"], kinds, rel)


class JsonSafeTests(unittest.TestCase):
    def test_passthrough(self):
        for v in [None, True, False, 0, -5, 10**30, "", "héllo", 1.5]:
            self.assertEqual(json_safe(v), v)
            self.assertIs(type(json_safe(v)), type(v))

    def test_non_finite_floats(self):
        self.assertEqual(json_safe(float("nan")), "nan")
        self.assertEqual(json_safe(float("inf")), "inf")
        self.assertEqual(json_safe(float("-inf")), "-inf")

    def test_bytes(self):
        self.assertEqual(json_safe(b"\x00\xAB"), "00ab")
        self.assertEqual(json_safe(bytearray(b"\xFF")), "ff")

    def test_containers(self):
        self.assertEqual(json_safe((1, [2, b"\x01"])), [1, [2, "01"]])
        self.assertEqual(json_safe({1: "a", "b": (None,)}), {"1": "a", "b": [None]})
        self.assertEqual(json_safe({Status.LOST: 1}), {"lost": 1})

    def test_enum(self):
        class Color(Enum):
            RED = 1
        self.assertEqual(json_safe(Status.VERIFIED), "verified")
        self.assertIs(type(json_safe(Status.VERIFIED)), str)
        self.assertEqual(json_safe(DamageKind.CRC_MISMATCH), "crc_mismatch")
        self.assertEqual(json_safe(Color.RED), 1)

    def test_unserializable(self):
        class Thing:
            pass
        self.assertEqual(json_safe(Thing()), "<unserializable Thing>")
        self.assertEqual(json_safe({1, 2}), "<unserializable set>")
        self.assertEqual(json_safe(object()), "<unserializable object>")

    def test_never_raises_on_cycles(self):
        a: list = []
        a.append(a)
        self.assertEqual(json_safe(a), ["<unserializable list>"])
        deep: list = []
        for _ in range(5000):
            deep = [deep]
        json.dumps(json_safe(deep))
        shared = [1]
        self.assertEqual(json_safe([shared, shared]), [[1], [1]])


class ToDictTests(unittest.TestCase):
    def test_deterministic(self):
        r = sample_result()
        one = json.dumps(r.to_dict())
        two = json.dumps(r.to_dict())
        self.assertEqual(one, two)
        self.assertEqual(one, json.dumps(sample_result().to_dict()))

    def test_shape(self):
        d = sample_result().to_dict()
        self.assertEqual(list(d), ["format", "confidence", "records", "members", "damage",
                                   "meta", "warnings", "name", "unsupported"])
        self.assertEqual(list(d["records"][0]), ["offset", "status", "kind", "fields", "issues"])
        f = d["records"][0]["fields"][0]
        self.assertEqual(list(f), ["name", "value", "offset", "length", "status", "evidence"])
        self.assertEqual(f["value"], "abcd")
        self.assertEqual(f["status"], "verified")
        self.assertIs(type(f["status"]), str)
        self.assertEqual(d["records"][0]["fields"][1]["value"], "nan")
        self.assertEqual(d["damage"][0], {"start": 6, "end": 10, "kind": "truncated",
                                          "reason": "short", "lossy": True})
        self.assertEqual(d["members"][0]["name"], "a.txt")
        self.assertEqual(d["meta"], {"k": [1, 2], "3": "three"})
        json.dumps(d, allow_nan=False)

    def test_bad_contents_do_not_raise(self):
        r = DecodeResult("X", 0.0, records=[object()], meta={"o": object()})
        json.dumps(r.to_dict())
        loop: dict = {}
        loop["self"] = loop
        d = DecodeResult("X", 0.0, meta=loop).to_dict()
        self.assertEqual(d["meta"], {"self": "<unserializable dict>"})


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sample_result().validate(10), [])
        self.assertEqual(DecodeResult("EMPTY", 0.0).validate(0), [])

    def assertOneProblem(self, result, size, needle):
        problems = result.validate(size)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(needle, problems[0])

    def test_confidence(self):
        for bad in [-0.1, 1.1, float("nan"), "high", True]:
            with self.subTest(bad=bad):
                self.assertOneProblem(DecodeResult("X", bad), 0, "confidence")

    def test_field_bounds(self):
        rec = lambda f: DecodeResult("X", 1.0, records=[Record(0, Status.VERIFIED, fields=[f])])
        self.assertOneProblem(rec(Field("a", 1, -1, 1, Status.VERIFIED)), 10, "offset")
        self.assertOneProblem(rec(Field("a", 1, 11, 0, Status.VERIFIED)), 10, "offset")
        self.assertOneProblem(rec(Field("a", 1, 8, 4, Status.VERIFIED)), 10, "beyond file size")
        self.assertOneProblem(rec(Field("a", 1, 0, -1, Status.VERIFIED)), 10, "negative")
        self.assertEqual(rec(Field("a", 1, 6, 4, Status.VERIFIED)).validate(10), [])

    def test_record_offset(self):
        self.assertOneProblem(DecodeResult("X", 1.0, records=[Record(11, Status.LOST)]),
                              10, "records[0].offset")

    def test_damage_range(self):
        for start, end in [(-1, 2), (5, 4), (0, 11)]:
            with self.subTest(start=start, end=end):
                r = DecodeResult("X", 1.0, damage=[Damage(start, end, DamageKind.BAD_LENGTH,
                                                          "")])
                self.assertOneProblem(r, 10, "damage[0]")

    def test_status_must_be_member(self):
        r = DecodeResult("X", 1.0, records=[Record(0, "verified")])
        self.assertOneProblem(r, 10, "status")
        r = DecodeResult("X", 1.0, records=[Record(0, Status.LOST, fields=[
            Field("a", 1, 0, 1, "bogus")])])
        self.assertOneProblem(r, 10, "status")

    def test_duplicate_and_reserved_field_names(self):
        # B5: a record becomes one flat object, so its field names must be unique.
        def rec(*names):
            return DecodeResult("X", 1.0, records=[Record(0, Status.VERIFIED, fields=[
                Field(n, 1, 0, 1, Status.VERIFIED) for n in names])])
        self.assertEqual(rec("a", "b").validate(10), [])
        self.assertOneProblem(rec("a", "b", "a"), 10, "duplicate field name 'a'")
        self.assertOneProblem(rec("verified"), 10, "'verified' is reserved")
        self.assertOneProblem(rec("issues"), 10, "'issues' is reserved")
        self.assertOneProblem(rec(7), 10, "fields[0].name: not a string")

    def test_issues_must_be_damage_kinds(self):
        good = Record(0, Status.UNVERIFIED, issues=[DamageKind.TRUNCATED])
        self.assertEqual(DecodeResult("X", 1.0, records=[good]).validate(10), [])
        bad = Record(0, Status.UNVERIFIED, issues=[DamageKind.TRUNCATED, "truncated"])
        self.assertOneProblem(DecodeResult("X", 1.0, records=[bad]), 10,
                              "records[0].issues[1]: 'truncated' is not a DamageKind member")
        self.assertOneProblem(DecodeResult("X", 1.0, records=[
            Record(0, Status.LOST, issues="truncated")]), 10, "issues: not a list")

    def test_lossy_and_unsupported_are_bools(self):
        self.assertOneProblem(DecodeResult("X", 1.0, damage=[
            Damage(0, 1, DamageKind.ENCRYPTED, "", lossy=1)]), 10, "lossy: not a bool")
        self.assertOneProblem(DecodeResult("X", 1.0, unsupported="yes"), 10,
                              "unsupported: not a bool")
        self.assertEqual(DecodeResult("X", 1.0, unsupported=True, damage=[
            Damage(0, 10, DamageKind.ENCRYPTED, "password", lossy=True)]).validate(10), [])

    def test_recurses_into_members(self):
        inner = DecodeResult("IN", 2.0)
        self.assertOneProblem(DecodeResult("X", 1.0, members=[inner]), 10, "members[0].")

    def test_never_raises(self):
        r = DecodeResult("X", 1.0, records=None, damage=[object()])
        self.assertTrue(r.validate(10))
        self.assertTrue(DecodeResult("X", 1.0).validate("big"))


if __name__ == "__main__":
    unittest.main()
