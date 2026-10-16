"""CF-NOCASES: well-behaved, but has no golden case folder (expected: C10)."""

from tests.fixtures.conform_formats._base import CrcDecoder


class NoCasesDecoder(CrcDecoder):
    name = "CF-NOCASES"
    extensions = (".cfnc",)
    magic = b"CFNC"
