import sys
import unittest

from salvagekit.core.plugin import Decoder, DiscoveryResult, discover_decoders, safe_probe

FAKE = "tests.fixtures.fake_formats"


class FakeProbe(Decoder):
    name = "FAKE"

    def __init__(self, behaviour):
        self.behaviour = behaviour

    def probe(self, data):
        return self.behaviour(data)


class DiscoveryTests(unittest.TestCase):
    def test_fake_formats(self):
        sys.modules.pop(f"{FAKE}._private", None)
        found = discover_decoders(FAKE)
        self.assertIsInstance(found, DiscoveryResult)
        self.assertEqual([d.name for d in found.decoders], ["GOOD"])
        # Modules are visited in name order, so dup.py ("dup" < "good") owns
        # the name and good.py's GoodDecoder is reported as the duplicate.
        self.assertEqual(type(found.decoders[0]).__module__, f"{FAKE}.dup")
        self.assertEqual(len(found.errors), 2, found.errors)
        broken = [e for e in found.errors if e.startswith(f"{FAKE}.broken:")]
        self.assertEqual(broken, [f"{FAKE}.broken: RuntimeError: broken on purpose"])
        dup = [e for e in found.errors if "duplicate" in e]
        self.assertEqual(len(dup), 1)
        self.assertIn("'GOOD'", dup[0])
        self.assertIn(f"{FAKE}.dup", dup[0])
        self.assertNotIn(f"{FAKE}._private", sys.modules)
        self.assertFalse(any("_private" in e for e in found.errors))

    def test_deterministic(self):
        a = discover_decoders(FAKE)
        b = discover_decoders(FAKE)
        self.assertEqual([type(d) for d in a.decoders], [type(d) for d in b.decoders])
        self.assertEqual(a.errors, b.errors)

    def test_real_package_finds_stub(self):
        found = discover_decoders()
        names = [d.name for d in found.decoders]
        self.assertIn("STUB", names)
        self.assertEqual(names, sorted(names))
        self.assertEqual(found.errors, [])

    def test_missing_package(self):
        found = discover_decoders("no_such_package_xyz")
        self.assertEqual(found.decoders, [])
        self.assertEqual(len(found.errors), 1)


class DecoderBaseTests(unittest.TestCase):
    def test_defaults(self):
        d = Decoder()
        self.assertEqual(d.probe(b"x"), 0.0)
        with self.assertRaises(NotImplementedError):
            d.decode(None)
        self.assertFalse(Decoder.can_encode())

    def test_can_encode(self):
        class Enc(Decoder):
            def encode(self, result):
                return b""
        self.assertTrue(Enc.can_encode())
        self.assertFalse(FakeProbe.can_encode())


class SafeProbeTests(unittest.TestCase):
    def check(self, behaviour, score, has_reason):
        got, reason = safe_probe(FakeProbe(behaviour), b"data")
        self.assertEqual(got, score)
        self.assertIsInstance(got, float)
        self.assertEqual(reason is not None, has_reason, reason)
        return reason

    def test_raising(self):
        def boom(_):
            raise ValueError("nope")
        self.assertIn("ValueError", self.check(boom, 0.0, True))

    def test_system_exit(self):
        def leave(_):
            raise SystemExit(3)
        self.check(leave, 0.0, True)

    def test_string(self):
        self.check(lambda _: "0.9", 0.0, True)

    def test_bool(self):
        self.check(lambda _: True, 0.0, True)

    def test_nan(self):
        self.check(lambda _: float("nan"), 0.0, True)

    def test_above_one(self):
        self.assertIn("clamped", self.check(lambda _: 1.5, 1.0, True))

    def test_below_zero(self):
        self.assertIn("clamped", self.check(lambda _: -1, 0.0, True))

    def test_normal(self):
        self.check(lambda _: 0.7, 0.7, False)
        self.check(lambda _: 1, 1.0, False)


if __name__ == "__main__":
    unittest.main()
