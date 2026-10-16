"""BRAVO: Xerox Alto Bravo document format decoder.

Format layout:
- Plain text printable ASCII stream with paragraphs separated by carriage return (\\r).
- Delimited by a Ctrl-Z (0x1A) byte.
- Followed by a binary formatting trailer ("looks").
"""

from __future__ import annotations

from salvagekit.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                  Status)
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.standalone import run_standalone


class BravoDecoder(Decoder):
    """Decoder for Xerox Alto Bravo document files."""

    name = "BRAVO"
    extensions = (".bravo",)

    def probe(self, data: bytes) -> float:
        """Probe for Bravo format: ASCII text delimited by CR and ended by Ctrl-Z."""
        if len(data) < 4:
            return 0.0
        prefix = data[:4096]
        ctrl_z = prefix.find(b"\x1a")
        if ctrl_z == -1:
            return 0.0
        text = prefix[:ctrl_z]
        if len(text) < 2 or b"\r" not in text:
            return 0.0
        if b"\n" in text:
            return 0.0
        for b in text:
            if not (0x20 <= b <= 0x7E or b in (0x0D, 0x09)):
                return 0.0
        return 1.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode Bravo file into paragraphs and damage."""
        size = reader.size
        result = DecodeResult(format=self.name, confidence=1.0)

        if size == 0:
            result.damage.append(Damage(0, 0, DamageKind.TRUNCATED, "empty file", lossy=True))
            return result

        all_bytes = reader.peek(size)
        ctrl_z = all_bytes.find(b"\x1a")

        if ctrl_z == -1:
            text_bytes = reader.bytes(size, "text")
            result.damage.append(Damage(size, size, DamageKind.TRUNCATED,
                                        "missing Ctrl-Z trailer delimiter", lossy=True))
            result.warnings.append("missing Ctrl-Z trailer delimiter")
        else:
            text_bytes = reader.bytes(ctrl_z, "text")
            reader.u8("ctrl_z")
            trailer_len = reader.remaining()
            if trailer_len == 0:
                result.damage.append(Damage(ctrl_z + 1, size, DamageKind.TRUNCATED,
                                            "missing formatting trailer", lossy=True))
                result.warnings.append("missing formatting trailer")
            else:
                trailer_bytes = reader.bytes(trailer_len, "trailer")
                if trailer_len < 15 or not trailer_bytes.endswith(b"\x00"):
                    result.damage.append(Damage(ctrl_z + 1, size, DamageKind.TRUNCATED,
                                                "incomplete formatting trailer", lossy=True))
                    result.warnings.append("incomplete formatting trailer")

        if not text_bytes:
            return result

        # Split into paragraphs by \r
        parts = text_bytes.split(b"\r")
        if text_bytes.endswith(b"\r"):
            parts = parts[:-1]

        curr = 0
        for idx, p in enumerate(parts):
            p_len = len(p)
            text_str = p.decode("ascii", errors="replace")
            fields = [
                Field("index", idx, curr, p_len, Status.CONSISTENT),
                Field("text", text_str, curr, p_len, Status.CONSISTENT),
            ]
            result.records.append(Record(offset=curr, status=Status.CONSISTENT,
                                         kind="paragraph", fields=fields))
            curr += p_len + 1  # advance past \r delimiter

        return result


if __name__ == "__main__":
    run_standalone(BravoDecoder)
