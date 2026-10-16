"""CF-SLOW: decode sleeps 3 s on a clean file (expected: C9)."""

import time

from tests.fixtures.conform_formats._base import CrcDecoder


class SlowDecoder(CrcDecoder):
    name = "CF-SLOW"
    extensions = (".cfsl",)
    magic = b"CFSL"

    def decode(self, reader):
        result = super().decode(reader)
        if result.records and not result.damage:
            time.sleep(3)  # bug: far too slow
        return result
