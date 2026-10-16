"""CF-HANG: decode loops forever when bytes follow the last record (expected: C4 timeout)."""

from tests.fixtures.conform_formats._base import CrcDecoder


class HangDecoder(CrcDecoder):
    name = "CF-HANG"
    extensions = (".cfhg",)
    magic = b"CFHG"

    def trailing(self, result, reader):
        while True:  # bug: waits for a record that never comes
            pass
