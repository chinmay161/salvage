"""Fixture: a valid decoder named GOOD."""

from salvage.core.model import DecodeResult
from salvage.core.plugin import Decoder


class GoodDecoder(Decoder):
    name = "GOOD"

    def probe(self, data: bytes) -> float:
        return 0.5

    def decode(self, reader) -> DecodeResult:
        return DecodeResult(format=self.name, confidence=0.5)
