"""CF-CRASH: kills its own process on a damaged header (expected: C4 worker crash)."""

import os

from tests.fixtures.conform_formats._base import CrcDecoder


class CrashDecoder(CrcDecoder):
    name = "CF-CRASH"
    extensions = (".cfcr",)
    magic = b"CFCR"

    def decode(self, reader):
        result = super().decode(reader)
        if any(d.reason == "header CRC-32 mismatch" for d in result.damage):
            os._exit(3)  # bug: hard exit (as a crashing C extension would)
        return result
