"""HANG: decode loops forever (timeout check)."""

from tests.fixtures.pipeline_formats._base import MagicDecoder


class HangDecoder(MagicDecoder):
    name = "T-HANG"
    magic = b"T-HANG"

    def decode(self, reader):
        while True:
            pass
