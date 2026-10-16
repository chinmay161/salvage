"""CF-BADTRIP: encode() drops the last byte (expected: C6)."""

from tests.fixtures.conform_formats._base import CrcDecoder


class BadTripDecoder(CrcDecoder):
    name = "CF-BADTRIP"
    extensions = (".cfbt",)
    magic = b"CFBT"

    def encode(self, result):
        return super().encode(result)[:-1]  # bug: off by one
