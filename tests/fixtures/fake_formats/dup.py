"""Fixture: a second decoder that reuses the name GOOD."""

from salvage.core.model import DecodeResult
from salvage.core.plugin import Decoder


class DupDecoder(Decoder):
    name = "GOOD"

    def decode(self, reader) -> DecodeResult:
        return DecodeResult(format=self.name, confidence=0.0)
