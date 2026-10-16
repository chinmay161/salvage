import os
import tempfile
import unittest
from unittest import mock

from salvagekit.core import emit
from salvagekit.core.emit import output_names


class NamingTests(unittest.TestCase):
    def test_default_names_are_exact(self):
        # C2: exactly "<input file name>.json".
        names = output_names(["s01.dat", "b", "report.json", "x.json"])
        self.assertEqual(names, {"s01.dat": "s01.dat.json", "b": "b.json",
                                 "report.json": "report.json.json", "x.json": "x.json.json"})

    def test_report_is_reserved(self):
        self.assertEqual(output_names(["report"], case_insensitive=False),
                         {"report": "report~2.json"})
        self.assertEqual(output_names(["report"]), {"report": "report~2.json"})

    def test_case_sensitive_file_system_keeps_exact_names(self):
        names = output_names(["A.dat", "a.dat", "REPORT", "report"], case_insensitive=False)
        self.assertEqual(names, {"A.dat": "A.dat.json", "a.dat": "a.dat.json",
                                 "REPORT": "REPORT.json", "report": "report~2.json"})

    def test_case_insensitive_file_system_renames_case_collisions(self):
        names = output_names(["a.BIN", "A.bin", "a.bin", "REPORT"], case_insensitive=True)
        self.assertEqual(names, {"A.bin": "A.bin.json", "a.BIN": "a.BIN~2.json",
                                 "a.bin": "a.bin~3.json", "REPORT": "REPORT~2.json"})
        self.assertEqual(output_names(["Straße", "STRASSE"])["Straße"], "Straße~2.json")

    def test_deterministic_regardless_of_input_order(self):
        rels = ["b", "B", "report", "c~2", "C", "c", "c~2.json"]
        for ci in (True, False):
            first = output_names(rels, case_insensitive=ci)
            self.assertEqual(output_names(reversed(rels), case_insensitive=ci), first)
            key = str.casefold if ci else str
            self.assertEqual(len({key(v) for v in first.values()}), len(rels))
            self.assertNotIn(key("report.json"), {key(v) for v in first.values()})


class CaseProbeTests(unittest.TestCase):
    def test_matches_the_os_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = emit.is_case_insensitive(tmp)
            self.assertEqual(os.listdir(tmp), [])
        if os.name == "nt":
            self.assertTrue(got)   # NTFS default
        elif os.path.exists("/proc"):
            self.assertFalse(got)  # Linux temp dirs are case-sensitive

    def test_never_overwrites_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            taken = os.path.join(tmp, f"{emit.PROBE_NAME}-0.tmp")
            with open(taken, "wb") as fh:
                fh.write(b"precious")
            emit.is_case_insensitive(tmp)
            with open(taken, "rb") as fh:
                self.assertEqual(fh.read(), b"precious")
            self.assertEqual(os.listdir(tmp), [os.path.basename(taken)])

    def test_unwritable_folder_counts_as_insensitive(self):
        with mock.patch.object(emit.os, "open", side_effect=PermissionError(13, "denied")):
            self.assertTrue(emit.is_case_insensitive("anywhere"))


if __name__ == "__main__":
    unittest.main()
