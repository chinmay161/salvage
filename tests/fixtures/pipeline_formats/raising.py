"""RAISE: decode raises ValueError."""

from tests.fixtures.pipeline_formats._base import MagicDecoder


class RaiseDecoder(MagicDecoder):
    name = "T-RAISE"
    magic = b"T-RAISE"

    def decode(self, reader):
        raise ValueError("raised on purpose")
