"""tools/calibrate.py: how our outputs are compared with kit/expected_outputs/."""

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("salvage_calibrate", ROOT / "tools" / "calibrate.py")
cal = importlib.util.module_from_spec(_spec)
sys.modules["salvage_calibrate"] = cal
_spec.loader.exec_module(cal)

EXPECTED = {
    "status": "partial", "format": "LIBRA-98", "file": "s04.dat",
    "metadata": {"version": 2, "branch_id": 1991},
    "records": [{"id": 1000, "title": "A", "price_cents": 1250, "due_date": None},
                {"id": 1008, "title": "B", "price_cents": 699, "due_date": "1998-12-19"}],
    "expected_damage": [{"any_of": ["truncated"], "lossy": True}],
    "match_on": ["id"],
    "optional_partial_records": [{"id": 1040}],
}


def ours():
    """Our output matching EXPECTED (records in another order, ints as floats)."""
    return {"source_file": "s04.dat", "format": "LIBRA-98", "status": "partial",
            "metadata": {"branch_id": 1991, "version": 2.0},
            "records": [copy.deepcopy(EXPECTED["records"][1]),
                        copy.deepcopy(EXPECTED["records"][0])],
            "damage": [{"kind": "truncated", "offset": 240, "detail": "x", "lossy": True}]}


class CompareTests(unittest.TestCase):
    def test_match(self):
        self.assertEqual(cal.compare(EXPECTED, ours()), [])

    def test_optional_partial_record_allowed_others_not(self):
        got = ours()
        got["records"].append({"id": 1040, "title": None, "verified": False})
        self.assertEqual(cal.compare(EXPECTED, got), [])
        got["records"].append({"id": 1050})
        self.assertEqual(cal.compare(EXPECTED, got),
                         ['records[id=1050]: not expected (extra record) {"id": 1050}'])

    def test_record_differences_by_path(self):
        got = ours()
        got["records"][0]["due_date"] = "1998-12-20"
        got["records"][1]["verified"] = False
        del got["records"][1]["price_cents"]
        self.assertEqual(cal.compare(EXPECTED, got), [
            "records[id=1000].price_cents: expected 1250, got nothing (key missing)",
            "records[id=1000].verified: not expected (extra key), got false",
            'records[id=1008].due_date: expected "1998-12-19", got "1998-12-20"'])
        got = ours()
        got["records"] = got["records"][:1]
        self.assertEqual(cal.compare(EXPECTED, got)[0][:31], "records[id=1000]: missing (expe")

    def test_top_level_and_metadata(self):
        got = ours()
        got.update(source_file="x", format="UNKNOWN", status="unrecognized")
        got["metadata"] = {"version": 2, "extra": True}
        self.assertEqual(cal.compare(EXPECTED, got), [
            'source_file: expected "s04.dat", got "x"',
            'format: expected "LIBRA-98", got "UNKNOWN"',
            'status: expected "partial", got "unrecognized"',
            "metadata.branch_id: expected 1991, got nothing (key missing)",
            "metadata.extra: not expected (extra key), got true"])

    def test_bool_is_not_a_number(self):
        exp = dict(EXPECTED, records=[{"id": 1, "checked_out": False}],
                   optional_partial_records=[])
        got = dict(ours(), records=[{"id": 1, "checked_out": 0}])
        self.assertEqual(cal.compare(exp, got),
                         ["records[id=1].checked_out: expected false, got 0"])

    def test_damage_any_of_and_lossy(self):
        got = ours()
        got["damage"][0]["lossy"] = False
        self.assertEqual(cal.compare(EXPECTED, got), [
            "damage: expected a damage of kind truncated, lossy true, found none",
            'damage[0]: not expected (no expected_damage entry accounts for it) '
            '{"detail": "x", "kind": "truncated", "lossy": false, "offset": 240}'])
        got = ours()
        got["damage"].append({"kind": "count_mismatch", "offset": 4, "detail": "", "lossy": True})
        self.assertEqual(len(cal.compare(EXPECTED, got)), 1)
        clean = dict(EXPECTED, expected_damage=[], status="ok")
        self.assertEqual(cal.compare(clean, dict(ours(), status="ok", damage=[])), [])

    def test_real_answer_keys_compare_with_themselves(self):
        # Every kit/expected_outputs/ file, turned into the output it describes, matches.
        for path in sorted((ROOT / "kit" / "expected_outputs").glob("*.json")):
            with self.subTest(key=path.name):
                exp = json.loads(path.read_text(encoding="utf-8"))
                kinds = [spec["any_of"][0] for spec in exp["expected_damage"]]
                got = {"source_file": exp["file"], "format": exp["format"],
                       "status": exp["status"], "metadata": exp["metadata"],
                       "records": exp["records"],
                       "damage": [{"kind": k, "offset": 0, "detail": "", "lossy": True}
                                  for k in kinds]}
                self.assertEqual(cal.compare(exp, got), [])


if __name__ == "__main__":
    unittest.main()
