import unittest

from salvage.core.emit import output_names


class NamingTests(unittest.TestCase):
    def test_default_names(self):
        self.assertEqual(output_names(["a.bin", "b"]), {"a.bin": "a.bin.json", "b": "b.json"})

    def test_report_is_reserved_at_root_only(self):
        names = output_names(["report", "REPORT", "sub/report"])
        self.assertEqual(names["REPORT"], "REPORT~2.json")
        self.assertEqual(names["report"], "report~3.json")
        self.assertEqual(names["sub/report"], "sub/report.json")

    def test_casefold_collisions(self):
        names = output_names(["a.BIN", "A.bin", "a.bin"])
        self.assertEqual(names, {"A.bin": "A.bin.json", "a.BIN": "a.BIN~2.json",
                                 "a.bin": "a.bin~3.json"})
        self.assertEqual(output_names(["Straße", "STRASSE"])["Straße"], "Straße~2.json")

    def test_nested_folders(self):
        names = output_names(["x/y/z.dat", "x/y.dat", "X/Y/Z.DAT"])
        self.assertEqual(names["X/Y/Z.DAT"], "X/Y/Z.DAT.json")
        self.assertEqual(names["x/y/z.dat"], "x/y/z.dat~2.json")
        self.assertEqual(names["x/y.dat"], "x/y.dat.json")

    def test_deterministic_regardless_of_input_order(self):
        rels = ["b", "B", "a/c", "A/C", "report", "c~2", "C"]
        first = output_names(rels)
        self.assertEqual(output_names(reversed(rels)), first)
        self.assertEqual(len({v.casefold() for v in first.values()}), len(rels))

    def test_file_never_shadows_an_output_folder(self):
        names = output_names(["a", "a.json/b"])
        self.assertEqual(names["a"], "a~2.json")
        self.assertEqual(names["a.json/b"], "a.json/b.json")

    def test_root_folder_named_like_the_report(self):
        names = output_names(["report.json/x", "Report.JSON"])
        self.assertEqual(names["report.json/x"], "report.json~dir/x.json")
        self.assertEqual(names["Report.JSON"], "Report.JSON.json")


if __name__ == "__main__":
    unittest.main()
