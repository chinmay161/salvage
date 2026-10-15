import os
import tempfile
import unittest

from salvage.core.walk import list_inputs


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

    def test_sorted_walk_order(self):
        for rel in ("b", "a", "z/2", "z/1", "c/x", "Q"):
            touch(self.root, rel)
        inputs, skipped = list_inputs(self.root)
        self.assertEqual([i.rel for i in inputs], ["Q", "a", "b", "c/x", "z/1", "z/2"])
        self.assertEqual(skipped, [])
        self.assertTrue(all(os.path.isabs(i.path) for i in inputs))
        self.assertEqual(inputs[0].size, 1)

    def test_output_dir_inside_input_is_not_walked(self):
        touch(self.root, "keep")
        touch(self.root, "out/old.json")
        inputs, skipped = list_inputs(self.root, os.path.join(self.root, "out"))
        self.assertEqual([i.rel for i in inputs], ["keep"])
        self.assertEqual(skipped, [])

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
        self.assertEqual(sorted(s.rel for s in skipped), ["dlink", "link"])
        self.assertTrue(all("symlink" in s.reason for s in skipped))

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
