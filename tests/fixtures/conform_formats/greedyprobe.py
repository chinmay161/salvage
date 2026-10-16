"""CF-GREEDYPROBE: probe claims every file (expected: C3)."""

from tests.fixtures.conform_formats._base import CrcDecoder


class GreedyProbeDecoder(CrcDecoder):
    name = "CF-GREEDYPROBE"
    extensions = (".cfgp",)
    magic = b"CFGP"

    def probe(self, data):
        return 1.0  # bug: never looks at the bytes
