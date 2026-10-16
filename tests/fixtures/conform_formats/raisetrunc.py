"""CF-RAISETRUNC: decode raises IndexError on input shorter than the header (expected: C4)."""

from tests.fixtures.conform_formats._base import HEADER_SIZE, CrcDecoder


class RaiseTruncDecoder(CrcDecoder):
    name = "CF-RAISETRUNC"
    extensions = (".cfrt",)
    magic = b"CFRT"

    def decode(self, reader):
        head = reader.peek(HEADER_SIZE)
        if head[:4] == self.magic:
            _ = head[HEADER_SIZE - 1]  # bug: IndexError when the header is cut short
        return super().decode(reader)
