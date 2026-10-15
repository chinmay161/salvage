"""STUB: a tiny synthetic format for exercising the pipeline.

Layout: magic b"SALVAGE-STUB\\x00" (13 bytes), u16le count, then count x
u32le values. No real file starts with this magic, so it is harmless in
production.
"""

from __future__ import annotations

import struct

from salvage.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                Status)
from salvage.core.plugin import Decoder
from salvage.core.reader import SafeReader
from salvage.core.standalone import run_standalone

MAGIC = b"SALVAGE-STUB\x00"


class StubDecoder(Decoder):
    """Decoder for the synthetic STUB test format."""

    name = "STUB"
    extensions = (".stub",)

    def probe(self, data: bytes) -> float:
        """1.0 if ``data`` starts with the STUB magic, else 0.0."""
        try:
            return 1.0 if bytes(data[:len(MAGIC)]) == MAGIC else 0.0
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode magic, count and values; keep complete values on truncation."""
        size = reader.size
        if reader.peek(len(MAGIC)) != MAGIC:
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=1.0)
        header = Record(offset=0, status=Status.VERIFIED, kind="header")
        result.records.append(header)
        magic = reader.bytes(len(MAGIC), "magic")
        header.fields.append(Field("magic", magic.hex(), 0, len(MAGIC),
                                   Status.VERIFIED, "exact magic match"))

        count_off = reader.tell()
        count = reader.u16le("count")
        if count is None:
            self._truncated(result, count_off, size, "count field missing")
            header.status = Status.UNVERIFIED
            return result

        need = count * 4
        if need <= reader.remaining():
            count_status = Status.CONSISTENT
            evidence = f"{count} values x 4 bytes = {need} bytes fit in {reader.remaining()} remaining"
        else:
            count_status = Status.UNVERIFIED
            evidence = f"{count} values need {need} bytes but only {reader.remaining()} remain"
        header.fields.append(Field("count", count, count_off, 2, count_status, evidence))
        header.status = Status.worst(f.status for f in header.fields)
        result.meta["declared_count"] = count

        decoded = 0
        for i in range(count):
            off = reader.tell()
            value = reader.u32le(f"value[{i}]")
            if value is None:
                self._truncated(result, off, size,
                                f"expected {count} values, file ends after {decoded}")
                break
            result.records.append(Record(
                offset=off, status=Status.UNVERIFIED, kind="value",
                fields=[Field("value", value, off, 4, Status.UNVERIFIED,
                              "no checksum in format")]))
            decoded += 1
        result.meta["decoded_count"] = decoded

        if decoded == count and reader.remaining() > 0:
            start = reader.tell()
            result.damage.append(Damage(start, size, DamageKind.UNPARSED,
                                        "trailing bytes after the last value"))
            result.warnings.append(f"{size - start} trailing bytes not parsed")
        return result

    def encode(self, result: DecodeResult) -> bytes:
        """Rebuild STUB bytes from the ``value`` records of ``result``."""
        values = [f.value for rec in result.records if rec.kind == "value"
                  for f in rec.fields if f.name == "value"]
        return MAGIC + struct.pack(f"<H{len(values)}I", len(values), *values)

    @staticmethod
    def _truncated(result: DecodeResult, start: int, size: int, why: str) -> None:
        result.damage.append(Damage(start, size, DamageKind.TRUNCATED, why))
        result.warnings.append(f"truncated at offset {start}: {why}")


if __name__ == "__main__":
    run_standalone(StubDecoder)
