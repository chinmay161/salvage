"""The well-behaved CF format shared by the conformance fixtures (underscore: not discovered).

Layout (all integers little-endian):

    offset 0   4 bytes   magic (one per fixture, e.g. b"CFOK")
    offset 4   u16       record count
    offset 6   u32       CRC-32 of bytes 0-5
    offset 10  records, back to back:
                 2 bytes   marker b"\\xA5\\x5A"
                 u16       payload length n (at most 1024)
                 n bytes   payload, UTF-8 text
                 u32       CRC-32 of the payload

:class:`CrcDecoder` decodes it the way the decoder guide asks (labelled
reads, CRC-verified fields, resync, damage reporting, encode). Each fixture
subclasses it and breaks exactly one thing through the hooks below.
"""

from __future__ import annotations

import struct

from salvagekit.core import checksums
from salvagekit.core.model import Damage, DamageKind, DecodeResult, Field, Record, Status
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.resync import ByteView, resync, resync_damage

MARKER = b"\xA5\x5A"
HEADER_SIZE = 10
MAX_PAYLOAD = 1024
TEXTS = ("alpha", "bravo charlie", "delta")


def crc32(data: bytes) -> int:
    return checksums.crc_preset("CRC-32", data)


def build(magic: bytes, texts: tuple[str, ...] = TEXTS) -> bytes:
    """A clean CF file."""
    head = magic + struct.pack("<H", len(texts))
    out = head + struct.pack("<I", crc32(head))
    for text in texts:
        payload = text.encode("utf-8")
        out += MARKER + struct.pack("<H", len(payload)) + payload
        out += struct.pack("<I", crc32(payload))
    return out


def looks_like_record(view: ByteView, offset: int) -> bool:
    if view.bytes(offset, 2) != MARKER:
        return False
    n = view.u16le(offset + 2)
    if n is None or n > MAX_PAYLOAD:
        return False
    stored = view.u32le(offset + 4 + n)
    return stored is not None and stored == crc32(view.bytes(offset + 4, n))


class CrcDecoder(Decoder):
    """Well-behaved decoder for the CF format; ``magic`` is set per fixture."""

    magic = b""

    def probe(self, data: bytes) -> float:
        try:
            head = bytes(data[:HEADER_SIZE])
            if len(self.magic) != 4 or head[:4] != self.magic:
                return 0.0
            if len(head) == HEADER_SIZE and struct.unpack_from("<I", head, 6)[0] == crc32(head[:6]):
                return 1.0
            return 0.6
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        if len(self.magic) != 4 or reader.peek(4) != self.magic:
            return DecodeResult(format=self.name, confidence=0.0)
        size = reader.size
        result = DecodeResult(format=self.name, confidence=0.6)
        header = Record(offset=0, status=Status.UNVERIFIED, kind="header")
        result.records.append(header)
        reader.bytes(4, "magic")
        header.fields.append(Field("magic", self.magic.decode("ascii"), 0, 4,
                                   Status.VERIFIED, "exact magic match"))
        count = reader.u16le("count")
        stored = reader.u32le("header_crc")
        if count is None or stored is None:
            result.damage.append(Damage(4, size, DamageKind.TRUNCATED, "header cut short"))
            result.warnings.append("truncated header")
            return result

        view = ByteView(reader)
        computed = crc32(view.bytes(0, 6))
        header_ok = stored == computed
        if header_ok:
            header.fields.append(Field("count", count, 4, 2, Status.VERIFIED,
                                       f"CRC-32 {computed:#010x} of the header matches"))
        else:
            header.fields.append(Field("count", count, 4, 2, Status.UNVERIFIED,
                                       f"header CRC-32 mismatch: stored {stored:#010x}, "
                                       f"computed {computed:#010x}"))
            result.damage.append(Damage(0, HEADER_SIZE, DamageKind.HEADER_CHECKSUM,
                                        "header CRC-32 mismatch"))
        header.status = Status.worst(f.status for f in header.fields)

        found = verified = 0
        while reader.remaining() > 0:
            off = reader.tell()
            n = view.u16le(off + 2) if view.bytes(off, 2) == MARKER else None
            if n is not None and n <= MAX_PAYLOAD and off + 8 + n > size:
                self.truncated_record(result, off, n, size)
                break
            if n is None or n > MAX_PAYLOAD:
                if found == count:
                    self.trailing(result, reader)
                hit = resync(reader, looks_like_record, start=off)
                damage = resync_damage(hit, "no valid record here; bytes skipped")
                if damage is not None:
                    result.damage.append(damage)
                if hit.offset is None:
                    break
                continue
            i = found
            reader.bytes(2, f"record[{i}].marker")
            reader.u16le(f"record[{i}].length")
            payload = reader.bytes(n, f"record[{i}].payload")
            crc = reader.u32le(f"record[{i}].crc")
            found += 1
            try:
                value, kind = payload.decode("utf-8"), "text"
            except UnicodeDecodeError:
                value, kind = payload.hex(), "blob"
            if crc == crc32(payload):
                status, evidence = Status.VERIFIED, f"CRC-32 {crc:#010x} matches"
                verified += 1
            else:
                status, evidence = Status.UNVERIFIED, "CRC-32 mismatch"
                result.damage.append(Damage(off, reader.tell(), DamageKind.CRC_MISMATCH,
                                            f"record {i}: CRC-32 mismatch"))
            result.records.append(Record(offset=off, status=status, kind=kind, fields=[
                Field(kind, value, off + 4, n, status, evidence)]))

        if found < count and not result.damage:
            result.damage.append(Damage(size, size, DamageKind.TRUNCATED,
                                        f"header declares {count} records, {found} found"))
        if found != count:
            result.warnings.append(f"header declares {count} records, {found} found")
        result.meta.update({"declared_count": count, "records_found": found,
                            "records_verified": verified})
        result.confidence = 1.0 if header_ok or verified else 0.6
        return result

    def encode(self, result: DecodeResult) -> bytes:
        payloads = []
        for rec in result.records:
            for f in rec.fields:
                if f.name == "text":
                    payloads.append(str(f.value).encode("utf-8"))
                elif f.name == "blob":
                    payloads.append(bytes.fromhex(str(f.value)))
        head = self.magic + struct.pack("<H", result.meta.get("declared_count", len(payloads)))
        out = head + struct.pack("<I", crc32(head))
        for payload in payloads:
            out += MARKER + struct.pack("<H", len(payload)) + payload
            out += struct.pack("<I", crc32(payload))
        return out

    # -- hooks the fixtures override ------------------------------------------

    def truncated_record(self, result: DecodeResult, off: int, n: int, size: int) -> None:
        """A record starts at ``off`` but the file ends inside it."""
        result.damage.append(Damage(off, size, DamageKind.TRUNCATED,
                                    f"record at {off} runs past the end"))
        result.warnings.append(f"truncated at offset {off}")

    def trailing(self, result: DecodeResult, reader: SafeReader) -> None:
        """All declared records were read and bytes remain (resync handles them)."""
