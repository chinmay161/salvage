import os
import tempfile
import unittest

from salvage.core import fallback, identify, isolate
from salvage.core.model import DecodeResult, Field, Record, Status
from salvage.core.plugin import Decoder
from salvage.formats.stub import MAGIC

PKG = "tests.fixtures.pipeline_formats"


class Fixed(Decoder):
    def __init__(self, name, score, extensions=(), result=None):
        self.name, self.score, self.extensions, self.result = name, score, extensions, result

    def probe(self, data):
        if isinstance(self.score, Exception):
            raise self.score
        return self.score

    def decode(self, reader):
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ChooseTests(unittest.TestCase):
    def test_ranked_and_threshold(self):
        decs = [Fixed("B", 0.4), Fixed("A", 0.9), Fixed("C", RuntimeError("boom"))]
        choice = identify.choose(decs, b"", "f.bin")
        self.assertEqual([(r.format, r.score) for r in choice.ranked],
                         [("A", 0.9), ("B", 0.4), ("C", 0.0)])
        self.assertIn("RuntimeError", choice.ranked[2].error)
        self.assertEqual([d.name for d in choice.candidates], ["A"])
        self.assertEqual(choice.warnings, [])

    def test_extension_breaks_ties_within_margin(self):
        decs = [Fixed("A", 0.9), Fixed("B", 0.85, (".DAT",)), Fixed("C", 0.6)]
        choice = identify.choose(decs, b"", "x.dat")
        self.assertEqual([d.name for d in choice.candidates], ["B", "A", "C"])
        self.assertEqual(choice.warnings, ["ambiguous: B, A"])

    def test_name_breaks_ties_without_extension(self):
        decs = [Fixed("Z", 0.9), Fixed("Y", 0.9)]
        choice = identify.choose(decs, b"", "noext")
        self.assertEqual([d.name for d in choice.candidates], ["Y", "Z"])

    def test_no_candidates(self):
        self.assertEqual(identify.choose([Fixed("A", 0.49)], b"", "x").candidates, [])


class AttemptTests(unittest.TestCase):
    def ok(self):
        return DecodeResult("OK", 1.0, records=[Record(0, Status.VERIFIED)])

    def test_order_and_outcomes(self):
        bad = DecodeResult("BAD", 1.0, records=[
            Record(0, Status.VERIFIED, fields=[Field("f", 1, 99, 1, Status.VERIFIED)])])
        decs = [Fixed("E", 1, result=ValueError("x")), Fixed("I", 1, result=bad),
                Fixed("N", 1, result=None), Fixed("M", 1, result=DecodeResult("M", 1.0)),
                Fixed("O", 1, result=self.ok())]
        result, dec, attempts = isolate.try_candidates(decs, b"abc")
        self.assertEqual(dec.name, "O")
        self.assertEqual([a[0] for a in attempts], ["E", "I", "N", "M", "O"])
        self.assertEqual(attempts[0][1], "error: ValueError: x")
        self.assertTrue(attempts[1][1].startswith("invalid: records[0].fields[0]"))
        self.assertTrue(attempts[2][1].startswith("invalid: "))
        self.assertEqual(attempts[3][1], "empty")
        self.assertEqual(attempts[4][1], "ok")

    def test_first_empty_used_when_nothing_ok(self):
        e1, e2 = DecodeResult("E1", 0.5), DecodeResult("E2", 0.5)
        result, dec, _ = isolate.try_candidates(
            [Fixed("A", 1, result=e1), Fixed("B", 1, result=e2)], b"")
        self.assertIs(result, e1)

    def test_all_failed(self):
        result, dec, attempts = isolate.try_candidates(
            [Fixed("A", 1, result=SystemExit(1))], b"")
        self.assertIsNone(result)
        self.assertTrue(attempts[0][1].startswith("error: SystemExit"))


class FallbackTests(unittest.TestCase):
    def test_entropy(self):
        self.assertEqual(fallback.entropy(b""), 0.0)
        self.assertEqual(fallback.entropy(b"aaaa"), 0.0)
        self.assertEqual(fallback.entropy(bytes(range(256))), 8.0)
        self.assertEqual(fallback.entropy(b"ab"), 1.0)

    def test_entropy_sample_layout(self):
        mb = 1024 * 1024
        self.assertFalse(fallback.entropy_is_sampled(4 * mb))
        self.assertTrue(fallback.entropy_is_sampled(4 * mb + 1))
        small = b"x" * (4 * mb)
        self.assertIs(fallback.entropy_sample(small), small)
        # 10 MB of distinct 1 MB blocks: sample = block 0, blocks 4-5, block 9.
        data = b"".join(bytes([i]) * mb for i in range(10))
        sample = fallback.entropy_sample(data)
        self.assertEqual(sample, bytes([0]) * mb + bytes([4]) * mb + bytes([5]) * mb
                         + bytes([9]) * mb)
        self.assertEqual(fallback.entropy(data), 2.0)

    def test_entropy_large_input_fast_and_deterministic(self):
        import random
        import time
        data = random.Random(7).randbytes(64 * 1024 * 1024)
        start = time.perf_counter()
        first = fallback.entropy(data)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0)
        self.assertEqual(fallback.entropy(data), first)
        self.assertGreater(first, 7.99)

    def test_unknown_marks_sampling(self):
        self.assertIs(fallback.unknown(b"abc", []).meta["entropy_sampled"], False)
        big = bytes(5 * 1024 * 1024)
        self.assertIs(fallback.unknown(big, []).meta["entropy_sampled"], True)

    def test_unknown_result(self):
        ranked = [identify.Ranked(n, 0.1) for n in "ABCD"]
        res = fallback.unknown(b"xyz", ranked)
        self.assertEqual((res.format, res.confidence, res.records), ("unknown", 0.0, []))
        self.assertEqual(res.meta["top_candidates"],
                         [{"format": n, "score": 0.1} for n in "ABC"])
        self.assertEqual(res.validate(3), [])


class IsolateTests(unittest.TestCase):
    """Run one stub file through every start method this OS offers."""

    def test_every_start_method(self):
        import multiprocessing
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.stub")
            with open(path, "wb") as fh:
                fh.write(MAGIC + b"\x00\x00")
            expected = isolate.process_file(path, "a.stub", PKG)
            for method in multiprocessing.get_all_start_methods():
                with self.subTest(method=method):
                    payload, reason, info = isolate.run_isolated(path, "a.stub", PKG, 20, method)
                    self.assertIsNone(reason)
                    self.assertEqual(info["candidates"], ["STUB"])
                    self.assertEqual(payload, expected)
                    self.assertEqual(payload["entry"]["status"], "decoded")

    def test_read_error_is_data(self):
        # A folder cannot be read as a file (Windows: permission denied;
        # POSIX: not a regular file). A missing file is "file disappeared".
        with tempfile.TemporaryDirectory() as folder:
            payload = isolate.process_file(folder, "x", PKG)
        self.assertEqual(payload["entry"]["status"], "failed")
        self.assertTrue(payload["entry"]["errors"][0].startswith("cannot read file"))
        payload = isolate.process_file(os.path.join(os.getcwd(), "no-such-file"), "x", PKG)
        self.assertEqual(payload["entry"]["errors"], ["file disappeared"])


if __name__ == "__main__":
    unittest.main()
