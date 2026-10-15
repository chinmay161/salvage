"""Shared probe for the test decoders (underscore: not discovered)."""

from salvage.core.plugin import Decoder


class MagicDecoder(Decoder):
    magic = b""

    def probe(self, data: bytes) -> float:
        return 1.0 if self.magic and bytes(data[:len(self.magic)]) == self.magic else 0.0
