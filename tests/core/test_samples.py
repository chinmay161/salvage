"""E3: the real pipeline on the organizers' samples (kit/samples/).

The input folder rebuilds the organizers' layout: every file of kit/samples/
(including its nested/ subfolder) plus kit/HINTS.md next to them.
tests/sample_formats.json says what each sample SHOULD be identified as
(from kit/HINTS.md). A format whose decoder does not exist yet is skipped
with a note, not failed.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from salvagekit.core import emit, report, validate, walk
from salvagekit.core.plugin import discover_decoders
from tests.pipeline_helpers import run_checked

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "kit" / "samples"
HINTS = ROOT / "kit" / "HINTS.md"
EXPECTED = ROOT / "kit" / "expected_outputs"
UNRECOGNIZED = ("s25_random.bin", "s26_empty.dat", "s27_notes.txt", "s28_tiny.dat",
                "s30_png_like.dat")


def sample_formats() -> dict[str, str]:
    with open(ROOT / "tests" / "sample_formats.json", encoding="utf-8") as fh:
        return json.load(fh)["formats"]


@unittest.skipUnless(SAMPLES.is_dir(), "kit/samples/ is not present")
class SampleRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="salvage-samples-")
        cls.inp = os.path.join(cls.tmp, "samples")
        shutil.copytree(SAMPLES, cls.inp)
        if HINTS.is_file():
            shutil.copyfile(HINTS, os.path.join(cls.inp, "HINTS.md"))
        cls.out = os.path.join(cls.tmp, "out")
        cls.report = run_checked(cls.inp, cls.out, jobs=4)
        cls.outputs = {}
        for name in os.listdir(cls.out):
            with open(os.path.join(cls.out, name), encoding="utf-8") as fh:
                cls.outputs[name] = json.load(fh)
        cls.decoders = {d.name for d in discover_decoders().decoders}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def output(self, name):
        return self.outputs[name + ".json"]

    def test_one_output_per_top_level_file_and_subfolder_skipped(self):
        top = sorted(n for n in os.listdir(self.inp)
                     if os.path.isfile(os.path.join(self.inp, n)))
        self.assertIn("HINTS.md", top)
        self.assertEqual(len(top), 31)   # 30 samples + HINTS.md
        self.assertEqual(sorted(self.outputs), sorted([n + ".json" for n in top]
                                                      + ["report.json"]))
        self.assertEqual([r["file"] for r in self.report["files"]], top)
        self.assertEqual(self.report["diagnostics"]["skipped"],
                         [{"input": "nested", "reason": walk.DIRECTORY}])
        self.assertNotIn("readme_ignore.txt.json", self.outputs)

    def test_every_output_valid_against_the_official_schemas(self):
        for name, doc in sorted(self.outputs.items()):
            with self.subTest(output=name):
                kind = "report" if name == emit.REPORT_NAME else "output"
                self.assertEqual(validate.errors(kind, doc), [])
        self.assertEqual(self.report["diagnostics"]["errors"], [])
        self.assertEqual(sum(self.report["totals"].values()), 31)
        self.assertEqual(list(self.report["totals"]), list(report.FILE_STATUSES))

    def test_identified_as_the_hinted_format(self):
        for name, fmt in sorted(sample_formats().items()):
            with self.subTest(sample=name, format=fmt):
                if fmt != "UNKNOWN" and fmt not in self.decoders:
                    self.skipTest(f"no {fmt} decoder yet")
                self.assertEqual(self.output(name)["format"], fmt)

    def test_noise_files_are_unrecognized(self):
        for name in UNRECOGNIZED:
            with self.subTest(sample=name):
                expected = EXPECTED / (name + ".json")
                if expected.is_file():
                    self.skipTest(f"{expected.name} decides this sample")
                out = self.output(name)
                self.assertEqual((out["status"], out["format"]), ("unrecognized", "UNKNOWN"))
        self.assertEqual(self.output("HINTS.md")["format"], "UNKNOWN")

    def test_sample_map_matches_the_hints(self):
        formats = sample_formats()
        samples = sorted(n for n in os.listdir(SAMPLES) if (SAMPLES / n).is_file())
        self.assertEqual(sorted(formats), [n for n in samples if n != "s29_almost_libra.dat"])


if __name__ == "__main__":
    unittest.main()
