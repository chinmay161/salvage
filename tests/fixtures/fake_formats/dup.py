"""Fixture: a second decoder that reuses the name GOOD."""

from salvagekit.core.model import DecodeResult
from salvagekit.core.plugin import Decoder


class DupDecoder(Decoder):
    name = "GOOD"

    def decode(self, reader) -> DecodeResult:
        return DecodeResult(format=self.name, confidence=0.0)
