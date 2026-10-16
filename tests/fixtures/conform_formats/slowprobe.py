"""CF-SLOWPROBE: probe walks every byte of the file (expected: C2 speed)."""

from tests.fixtures.conform_formats._base import CrcDecoder


class SlowProbeDecoder(CrcDecoder):
    name = "CF-SLOWPROBE"
    extensions = (".cfsp",)
    magic = b"CFSP"

    def probe(self, data):
        acc = 0
        for _ in range(2):
            for b in bytes(data):  # bug: scans the whole file (twice) instead of the header
                acc = (acc * 31 + b) & 0xFFFFFFFF
        return super().probe(data)
