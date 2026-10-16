import os
import tempfile
import unittest

from salvagekit.core.walk import DIRECTORY, list_inputs


def touch(root, rel, data=b"x"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class WalkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_sorted_top_level_only(self):
        # C1: non-recursive. Subfolders are listed as skipped, never entered.
        for rel in ("b", "a", "z/2", "z/1", "c/x", "Q"):
            touch(self.root, rel)
        inputs, skipped = list_inputs(self.root)
        self.assertEqual([i.rel for i in inputs], ["Q", "a", "b"])
        self.assertEqual([(s.rel, s.reason) for s in skipped],
                         [("c", DIRECTORY), ("z", DIRECTORY)])
        self.assertTrue(all(os.path.isabs(i.path) for i in inputs))
        self.assertEqual(inputs[0].size, 1)

    def test_empty_subfolder_is_skipped_too(self):
        os.makedirs(os.path.join(self.root, "nested"))
        inputs, skipped = list_inputs(self.root)
        self.assertEqual((inputs, [s.rel for s in skipped]), ([], ["nested"]))

    def test_output_dir_inside_input_is_not_listed(self):
        touch(self.root, "keep")
        touch(self.root, "out/old.json")
        inputs, skipped = list_inputs(self.root, os.path.join(self.root, "out"))
        self.assertEqual([i.rel for i in inputs], ["keep"])
        self.assertEqual(skipped, [])

    def test_unreadable_input_dir_never_raises(self):
        inputs, skipped = list_inputs(os.path.join(self.root, "missing"))
        self.assertEqual(inputs, [])
        self.assertEqual(skipped[0].rel, ".")
        self.assertIn("unreadable directory", skipped[0].reason)

    def test_symlinks_skipped(self):
        target = touch(self.root, "real")
        os.makedirs(os.path.join(self.root, "dir"))
        try:
            os.symlink(target, os.path.join(self.root, "link"))
            os.symlink(os.path.join(self.root, "dir"), os.path.join(self.root, "dlink"),
                       target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here: {exc}")
        inputs, skipped = list_inputs(self.root)
        self.assertEqual([i.rel for i in inputs], ["real"])
        self.assertEqual([(s.rel, "symlink" in s.reason) for s in skipped],
                         [("dir", False), ("dlink", True), ("link", True)])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs on this OS")
    def test_fifo_skipped(self):
        os.mkfifo(os.path.join(self.root, "pipe"))
        touch(self.root, "real")
        inputs, skipped = list_inputs(self.root)
        self.assertEqual([i.rel for i in inputs], ["real"])
        self.assertEqual([s.rel for s in skipped], ["pipe"])
        self.assertIn("fifo", skipped[0].reason)


if __name__ == "__main__":
    unittest.main()
