"""EXAMPLE: a complete decoder skeleton for a made-up format. Copy, rename, adapt.

This file lives in docs/, so it is never discovered or shipped. Copy it to
salvage/formats/<yourformat>.py, rename the class, set ``name`` and
``extensions``, and replace the layout below with your format's. A test
(tests/core/test_decoder_template.py) runs this exact file through the
pipeline machinery, so it is known to work.

The made-up EXAMPLE layout (all integers little-endian):

    offset 0   4 bytes   magic b"EXMP"
    offset 4   u16       version (1 or 2)
    offset 6   u16       number of records
    offset 8   8 bytes   reserved, always zero  (-> label it "padding")
    offset 16  records, back to back:
                 2 bytes   record marker b"\\xA5\\x5A"
                 u16       payload length n (at most 4096)
                 n bytes   payload, UTF-8 text
                 u16       CRC-16/XMODEM of the payload

What it shows: probe that never raises; reads that are all labelled;
padding labelled "padding"; a checksum check with salvage.core.checksums
("verified" with the evidence named); a truncation Damage; resync past
junk with salvage.core.resync; variant and confidence; run_standalone.

Run it alone:  PYTHONPATH=. python docs/decoder-template.py some-file.exmp
(a real decoder:  python -m salvage.formats.<name> some-file)
"""

from __future__ import annotations

import struct

from salvage.core import checksums
from salvage.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                Status)
from salvage.core.plugin import Decoder
from salvage.core.reader import SafeReader
from salvage.core.resync import ByteView, resync, resync_damage
from salvage.core.standalone import run_standalone

MAGIC = b"EXMP"
MARKER = b"\xA5\x5A"
HEADER_SIZE = 16
PADDING_SIZE = 8
MAX_PAYLOAD = 4096
KNOWN_VERSIONS = (1, 2)
CRC = "CRC-16/XMODEM"


def crc16(data: bytes) -> int:
    """The record checksum (one of the presets in salvage.core.checksums)."""
    return checksums.crc_preset(CRC, data)


def looks_like_record(view: ByteView, offset: int) -> bool:
    """Resync test: marker, plausible length, and a matching CRC at ``offset``.

    Uses the non-claiming ByteView, so probing does not count as coverage.
    Make this strict: a weak test "finds" records inside junk.
    """
    if view.bytes(offset, 2) != MARKER:
        return False
    n = view.u16le(offset + 2)
    if n is None or n > MAX_PAYLOAD:
        return False
    stored = view.u16le(offset + 4 + n)
    return stored is not None and stored == crc16(view.bytes(offset + 4, n))


class ExampleDecoder(Decoder):
    """Decoder for the made-up EXAMPLE format."""

    name = "EXAMPLE"            # unique; this is the "format" in the output
    extensions = (".exmp",)     # a weak hint only; content decides

    def probe(self, data: bytes) -> float:
        """1.0 for magic + known version, 0.6 for the magic alone, else 0.0.

        Look at the bytes only; never raise (wrap everything).
        """
        try:
            if bytes(data[:4]) != MAGIC:
                return 0.0
            if len(data) >= 6 and struct.unpack_from("<H", data, 4)[0] in KNOWN_VERSIONS:
                return 1.0
            return 0.6
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode everything reachable. Never raises; reads only via ``reader``."""
        if reader.peek(4) != MAGIC:
            # Not ours after all: an empty result (core tries the next candidate).
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=0.6)
        header = Record(offset=0, status=Status.UNVERIFIED, kind="header")
        result.records.append(header)

        # -- header ----------------------------------------------------------
        magic = reader.bytes(4, "magic")
        header.fields.append(Field("magic", magic.decode("ascii"), 0, 4,
                                   Status.VERIFIED, "exact magic match"))

        version = reader.u16le("version")
        if version is None:
            return self._truncated(result, header, 4, reader.size, "header cut short")
        if version in KNOWN_VERSIONS:
            header.fields.append(Field("version", version, 4, 2, Status.CONSISTENT,
                                       f"version {version} is a known version"))
            result.format = f"EXAMPLE v{version}"   # -> "variant" in the output
        else:
            header.fields.append(Field("version", version, 4, 2, Status.UNVERIFIED,
                                       "unknown version; decoding as version 2"))
            result.warnings.append(f"unknown version {version}")

        count = reader.u16le("count")
        if count is None:
            return self._truncated(result, header, 6, reader.size, "header cut short")
        count_field = Field("count", count, 6, 2, Status.UNVERIFIED, "")
        header.fields.append(count_field)       # status decided after the records

        # Reserved bytes: label them "padding" ONLY if they really are padding.
        reserved = reader.peek(PADDING_SIZE)
        if len(reserved) < PADDING_SIZE:
            return self._truncated(result, header, 8, reader.size, "header cut short")
        if reserved == bytes(PADDING_SIZE):
            reader.bytes(PADDING_SIZE, "padding")
        else:
            reader.bytes(PADDING_SIZE, "reserved")
            header.fields.append(Field("reserved", reserved.hex(), 8, PADDING_SIZE,
                                       Status.UNVERIFIED, "expected zero bytes"))
            result.warnings.append("reserved header bytes are not zero")

        # -- records ---------------------------------------------------------
        view = ByteView(reader)     # look ahead without claiming bytes
        found = verified = 0
        while reader.remaining() > 0:
            off = reader.tell()
            n = view.u16le(off + 2) if view.bytes(off, 2) == MARKER else None
            if n is not None and n <= MAX_PAYLOAD and off + 6 + n > reader.size:
                # A record starts here but the file ends inside it. Never
                # invent the missing bytes: report the range as truncated.
                result.damage.append(Damage(off, reader.size, DamageKind.TRUNCATED,
                                            f"record {found} at {off} runs past the end"))
                result.warnings.append(f"truncated at offset {off}")
                break
            if n is None or n > MAX_PAYLOAD:
                # No record here: skip to the next offset where a whole valid
                # record starts. start=off so the skipped range begins here.
                hit = resync(reader, looks_like_record, start=off)
                damage = resync_damage(hit, "no valid record here; bytes skipped")
                if damage is not None:
                    result.damage.append(damage)
                if hit.offset is None:
                    result.warnings.append(f"no further records after offset {off}")
                    break
                continue  # the reader now sits on the next good record

            i = found
            reader.bytes(2, f"record[{i}].marker")
            reader.u16le(f"record[{i}].length")
            payload = reader.bytes(n, f"record[{i}].payload")
            stored = reader.u16le(f"record[{i}].crc")
            computed = crc16(payload)
            found += 1

            try:
                value, note = payload.decode("utf-8"), ""
            except UnicodeDecodeError:
                value, note = payload.hex(), "; not UTF-8, shown as hex"
            if stored == computed:
                status = Status.VERIFIED
                evidence = f"{CRC} {computed:#06x} matches the stored value{note}"
                verified += 1
            else:
                status = Status.UNVERIFIED
                evidence = f"{CRC} mismatch: stored {stored:#06x}, computed {computed:#06x}{note}"
                result.damage.append(Damage(off, reader.tell(), DamageKind.CHECKSUM,
                                            f"record {i}: {evidence}"))
            result.records.append(Record(
                offset=off, status=status, kind="entry",
                fields=[Field("text", value, off + 4, n, status, evidence)]))

        # -- cross-checks, meta, confidence --------------------------------
        if found == count and not result.damage:
            count_field.status = Status.CONSISTENT
            count_field.evidence = f"matches the {found} records found"
        else:
            count_field.evidence = f"header says {count}, {found} records found"
            if found != count:
                result.warnings.append(count_field.evidence)
        header.status = Status.worst(f.status for f in header.fields)
        result.meta.update({"version": version, "declared_count": count,
                            "records_found": found, "records_verified": verified})
        # confidence = how sure we are, AFTER decoding, that this is EXAMPLE:
        # magic alone 0.6; at least one CRC-verified record proves it.
        result.confidence = 1.0 if verified else 0.6
        return result

    def encode(self, result: DecodeResult) -> bytes:
        """Optional: rebuild file bytes (enables round-trip checks)."""
        texts = [f.value for r in result.records if r.kind == "entry"
                 for f in r.fields if f.name == "text"]
        version = result.meta.get("version") or 2
        out = MAGIC + struct.pack("<HH", version, len(texts)) + bytes(PADDING_SIZE)
        for text in texts:
            payload = str(text).encode("utf-8")
            out += MARKER + struct.pack("<H", len(payload)) + payload
            out += struct.pack("<H", crc16(payload))
        return out

    @staticmethod
    def _truncated(result: DecodeResult, header: Record, start: int, size: int,
                   why: str) -> DecodeResult:
        result.damage.append(Damage(start, size, DamageKind.TRUNCATED, why))
        result.warnings.append(f"truncated at offset {start}: {why}")
        header.status = Status.worst(f.status for f in header.fields)
        return result


if __name__ == "__main__":
    run_standalone(ExampleDecoder)
