"""CF-NONDET: output order comes from iterating a set of str (expected: C7)."""

from tests.fixtures.conform_formats._base import CrcDecoder

TAGS = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"}


class NondetDecoder(CrcDecoder):
    name = "CF-NONDET"
    extensions = (".cfnd",)
    magic = b"CFND"

    def decode(self, reader):
        result = super().decode(reader)
        if result.records:
            result.meta["tags"] = [t for t in TAGS]  # bug: order depends on PYTHONHASHSEED
        return result
