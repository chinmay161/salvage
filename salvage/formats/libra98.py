"""LIBRA-98: Library circulation catalogue format decoder.

Layout:
  Header (16 bytes fixed, plus optional extension):
    offset 0x00: 4 bytes magic b"LB98"
    offset 0x04: u8 major version (2)
    offset 0x05: u8 minor version (0 or 1)
    offset 0x06: u16le declared record count
    offset 0x08: u16le created DOS date
    offset 0x0A: u16le created DOS time
    offset 0x0C: u16le data offset (16 for v2.0, 40 for v2.1)
    offset 0x0E: u16le branch ID
    offset 0x10..data_offset: optional banner text (e.g. "LIBSYS/98 REL 2.1")

  Records (back to back starting at data_offset):
    +0x00: u8 marker 0xA5
    +0x01: u8 payload length N (bytes from flags up to and including checksum)
    +0x02: u8 flags (bit 0: checked_out, bit 1: reference_only, bit 2: deleted)
    +0x03: u32le book ID
    +0x07: u8 title length L_T
    +0x08: L_T bytes title string (CP437)
    +0x08 + L_T: u8 author length L_A
    +0x09 + L_T: L_A bytes author string (CP437)
    +0x09 + L_T + L_A: u16le year offset (year = year_offset + 1500)
    +0x0B + L_T + L_A: u16le price in cents
    +0x0D + L_T + L_A: u8 copies
    +0x0E + L_T + L_A: 10 bytes ISBN (ASCII)
    +0x18 + L_T + L_A: u16le due date (DOS date, 0 if not checked out / null)
    +0x1A + L_T + L_A: u8 record checksum (sum8 over flags through due date)

  Trailer (6 bytes, clean files only):
    offset: 4 bytes magic b"END!"
    offset + 4: u16le sum16 over all file bytes prior to b"END!"
"""

from __future__ import annotations

import struct

from salvage.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                Status)
from salvage.core.plugin import Decoder
from salvage.core.reader import SafeReader
from salvage.core.resync import ByteView, resync, resync_damage
from salvage.core.standalone import run_standalone

MAGIC = b"LB98"
RECORD_MARKER = 0xA5
TRAILER_MAGIC = b"END!"
HEADER_MIN_SIZE = 16
YEAR_EPOCH = 1500
MIN_RECORD_PAYLOAD = 24


def _format_dos_datetime(d: int, t: int) -> str:
    """Format 16-bit DOS date and 16-bit DOS time as ISO 8601 string."""
    year = ((d >> 9) & 0x7F) + 1980
    month = (d >> 5) & 0x0F
    day = d & 0x1F
    hour = (t >> 11) & 0x1F
    minute = (t >> 5) & 0x3F
    second = (t & 0x1F) * 2
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def _format_dos_date(d: int) -> str:
    """Format 16-bit DOS date as YYYY-MM-DD."""
    year = ((d >> 9) & 0x7F) + 1980
    month = (d >> 5) & 0x0F
    day = d & 0x1F
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_iso_datetime(s: str) -> tuple[int, int]:
    """Parse ISO 8601 YYYY-MM-DDTHH:MM:SS to 16-bit DOS date and time."""
    try:
        date_part, time_part = s.split("T")
        y, m, d = (int(x) for x in date_part.split("-"))
        h, mn, sec = (int(x) for x in time_part.split(":"))
        dos_date = ((y - 1980) << 9) | (m << 5) | d
        dos_time = (h << 11) | (mn << 5) | (sec // 2)
        return dos_date & 0xFFFF, dos_time & 0xFFFF
    except Exception:
        return 0, 0


def _parse_iso_date(s: str | None) -> int:
    """Parse YYYY-MM-DD to 16-bit DOS date (0 if None or invalid)."""
    if not s:
        return 0
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return (((y - 1980) << 9) | (m << 5) | d) & 0xFFFF
    except Exception:
        return 0


def _looks_like_record(view: ByteView, offset: int) -> bool:
    """Strict resync check: marker 0xA5, valid length, and valid sum8."""
    try:
        if view.u8(offset) != RECORD_MARKER:
            return False
        plen = view.u8(offset + 1)
        if plen is None or plen < MIN_RECORD_PAYLOAD:
            return False
        if offset + 2 + plen > view.size:
            return False
        payload = view.bytes(offset + 2, plen - 1)
        if len(payload) != plen - 1:
            return False
        stored_chk = view.u8(offset + 1 + plen)
        return stored_chk is not None and (sum(payload) & 0xFF) == stored_chk
    except Exception:
        return False


class Libra98Decoder(Decoder):
    """Decoder for LIBRA-98 library catalogue files."""

    name = "LIBRA-98"
    extensions = (".lb9", ".dat")

    def probe(self, data: bytes) -> float:
        """Probe for LIBRA-98 files. Fast and never raises.

        Rejects files shorter than header minimum (16 bytes) such as
        s29_almost_libra.dat.
        """
        try:
            if len(data) < HEADER_MIN_SIZE:
                return 0.0
            if bytes(data[:4]) != MAGIC:
                return 0.0
            version_major = data[4]
            if version_major != 2:
                return 0.2
            data_offset, = struct.unpack_from("<H", data, 12)
            if data_offset < HEADER_MIN_SIZE or data_offset > len(data):
                return 0.2
            if TRAILER_MAGIC in data:
                idx = data.rfind(TRAILER_MAGIC)
                if idx + 6 <= len(data):
                    stored_crc, = struct.unpack_from("<H", data, idx + 4)
                    if (sum(data[:idx]) & 0xFFFF) == stored_crc:
                        return 1.0
            return 0.8
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode a LIBRA-98 file using reader."""
        if reader.peek(4) != MAGIC:
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=0.8)

        # -- Header -----------------------------------------------------------
        reader.bytes(4, "header.magic")
        version_major = reader.u8("header.version_major")
        version_minor = reader.u8("header.version_minor")
        declared_record_count = reader.u16le("header.declared_record_count")
        created_date = reader.u16le("header.created_date")
        created_time = reader.u16le("header.created_time")
        data_offset = reader.u16le("header.data_offset")
        branch_id = reader.u16le("header.branch_id")

        if (version_major is None or version_minor is None
                or declared_record_count is None or created_date is None
                or created_time is None or data_offset is None or branch_id is None):
            result.damage.append(Damage(0, reader.size, DamageKind.TRUNCATED,
                                        "header cut short"))
            result.warnings.append("header truncated")
            return result

        result.meta["version"] = version_major
        result.meta["version_minor"] = version_minor
        result.meta["encoding"] = "cp437"
        result.meta["created"] = _format_dos_datetime(created_date, created_time)
        result.meta["branch_id"] = branch_id
        result.meta["declared_record_count"] = declared_record_count
        result.meta["data_offset"] = data_offset

        if data_offset > HEADER_MIN_SIZE:
            ext_len = data_offset - HEADER_MIN_SIZE
            ext_bytes = reader.bytes(ext_len, "header.extension")
            result.meta["header_extension"] = ext_bytes.hex()
            ext_text = ext_bytes.rstrip(b"\x00").decode("cp437", errors="replace")
            if ext_text:
                result.meta["software"] = ext_text

        # Move reader to data_offset if header extension was skipped or aligned
        if reader.tell() < data_offset:
            skip_len = data_offset - reader.tell()
            reader.bytes(skip_len, "header.padding")

        # -- Records Loop -----------------------------------------------------
        rec_idx = 0
        trailer_found = False

        while reader.tell() < reader.size:
            # Check for trailer first
            if reader.peek(4) == TRAILER_MAGIC:
                trailer_off = reader.tell()
                reader.bytes(4, "trailer.magic")
                stored_sum = reader.u16le("trailer.checksum")
                if stored_sum is not None:
                    computed_sum = sum(reader._data[:trailer_off]) & 0xFFFF
                    if stored_sum == computed_sum:
                        result.confidence = 1.0
                    else:
                        result.damage.append(Damage(
                            trailer_off, reader.tell(), DamageKind.CHECKSUM,
                            f"trailer checksum mismatch: stored 0x{stored_sum:04x}, computed 0x{computed_sum:04x}"
                        ))
                else:
                    result.damage.append(Damage(
                        trailer_off, reader.size, DamageKind.TRUNCATED,
                        "trailer cut short"
                    ))
                trailer_found = True
                break

            rec_start = reader.tell()
            marker = reader.u8(f"record[{rec_idx}].marker")
            if marker is None:
                break
            if marker != RECORD_MARKER:
                # Corrupted record or junk bytes -> resync
                hit = resync(reader, _looks_like_record, start=rec_start)
                dmg = resync_damage(hit, f"invalid record marker 0x{marker:02x}; skipping to next record")
                if dmg is not None:
                    result.damage.append(dmg)
                if hit.offset is None:
                    break
                continue

            plen = reader.u8(f"record[{rec_idx}].length")
            if plen is None:
                result.damage.append(Damage(rec_start, reader.size, DamageKind.TRUNCATED,
                                            f"record {rec_idx} truncated at length byte"))
                break

            if plen < MIN_RECORD_PAYLOAD:
                hit = resync(reader, _looks_like_record, start=rec_start)
                dmg = resync_damage(hit, f"invalid record payload length {plen}")
                if dmg is not None:
                    result.damage.append(dmg)
                if hit.offset is None:
                    break
                continue

            if plen > reader.remaining():
                result.damage.append(Damage(rec_start, reader.size, DamageKind.TRUNCATED,
                                            f"file truncated inside record {rec_idx}"))
                break

            # Read record payload
            flags_off = reader.tell()
            flags = reader.u8(f"record[{rec_idx}].flags")
            id_off = reader.tell()
            rec_id = reader.u32le(f"record[{rec_idx}].id")
            title_len_off = reader.tell()
            title_len = reader.u8(f"record[{rec_idx}].title_len")
            title_off = reader.tell()
            title_bytes = reader.bytes(title_len or 0, f"record[{rec_idx}].title")
            author_len_off = reader.tell()
            author_len = reader.u8(f"record[{rec_idx}].author_len")
            author_off = reader.tell()
            author_bytes = reader.bytes(author_len or 0, f"record[{rec_idx}].author")
            year_off = reader.tell()
            year_offset = reader.u16le(f"record[{rec_idx}].year")
            price_off = reader.tell()
            price_val = reader.u16le(f"record[{rec_idx}].price_cents")
            copies_off = reader.tell()
            copies_val = reader.u8(f"record[{rec_idx}].copies")
            isbn_off = reader.tell()
            isbn_bytes = reader.bytes(10, f"record[{rec_idx}].isbn")
            due_off = reader.tell()
            raw_due = reader.u16le(f"record[{rec_idx}].due_date")
            chk_off = reader.tell()
            stored_chk = reader.u8(f"record[{rec_idx}].checksum")

            if (flags is None or rec_id is None or title_len is None
                    or title_bytes is None or author_len is None or author_bytes is None
                    or year_offset is None or price_val is None or copies_val is None
                    or isbn_bytes is None or raw_due is None or stored_chk is None):
                result.damage.append(Damage(rec_start, reader.size, DamageKind.TRUNCATED,
                                            f"record {rec_idx} cut short during field reads"))
                break

            # Checksum verification over bytes from flags to due_date
            computed_chk = sum(reader._data[flags_off:chk_off]) & 0xFF
            chk_ok = (stored_chk == computed_chk)

            if chk_ok:
                field_status = Status.VERIFIED
                evidence = "SUM8 checksum matched"
            else:
                field_status = Status.UNVERIFIED
                evidence = f"SUM8 mismatch: stored 0x{stored_chk:02x}, computed 0x{computed_chk:02x}"
                result.damage.append(Damage(rec_start, reader.tell(), DamageKind.CHECKSUM,
                                            f"record {rec_idx} checksum mismatch"))

            title = title_bytes.decode("cp437", errors="replace")
            author = author_bytes.decode("cp437", errors="replace")
            year = year_offset + YEAR_EPOCH
            isbn = isbn_bytes.decode("ascii", errors="replace")
            checked_out = bool(flags & 0x01)
            reference_only = bool(flags & 0x02)
            deleted = bool(flags & 0x04)
            due_date = _format_dos_date(raw_due) if raw_due != 0 else None

            rec = Record(offset=rec_start, status=field_status, kind="book")
            rec.fields = [
                Field("id", rec_id, id_off, 4, field_status, evidence),
                Field("title", title, title_off, title_len, field_status, evidence),
                Field("author", author, author_off, author_len, field_status, evidence),
                Field("year", year, year_off, 2, field_status, evidence),
                Field("price_cents", price_val, price_off, 2, field_status, evidence),
                Field("copies", copies_val, copies_off, 1, field_status, evidence),
                Field("isbn", isbn, isbn_off, 10, field_status, evidence),
                Field("checked_out", checked_out, flags_off, 1, field_status, evidence),
                Field("deleted", deleted, flags_off, 1, field_status, evidence),
                Field("reference_only", reference_only, flags_off, 1, field_status, evidence),
                Field("due_date", due_date, due_off, 2, field_status, evidence),
            ]
            result.records.append(rec)
            rec_idx += 1

        # -- Post-decode checks -----------------------------------------------
        if not trailer_found and not any(d.kind == DamageKind.TRUNCATED for d in result.damage):
            result.damage.append(Damage(reader.size, reader.size, DamageKind.TRUNCATED,
                                        "file ends before trailer"))

        if rec_idx < declared_record_count:
            if not any(d.kind == DamageKind.TRUNCATED for d in result.damage):
                result.damage.append(Damage(reader.tell(), reader.size, DamageKind.TRUNCATED,
                                            f"expected {declared_record_count} records, found {rec_idx}"))
            result.warnings.append(
                f"declared {declared_record_count} records, but only {rec_idx} recovered"
            )

        if rec_idx == declared_record_count and not trailer_found and reader.remaining() > 0:
            start = reader.tell()
            result.damage.append(Damage(start, reader.size, DamageKind.UNPARSED,
                                        "trailing unparsed bytes"))

        return result

    def encode(self, result: DecodeResult) -> bytes:
        """Rebuild LIBRA-98 file bytes from DecodeResult."""
        meta = result.meta or {}
        version_major = int(meta.get("version", 2))
        version_minor = int(meta.get("version_minor", 0))
        branch_id = int(meta.get("branch_id", 0))
        created_str = str(meta.get("created", "1998-01-01T00:00:00"))
        dos_date, dos_time = _parse_iso_datetime(created_str)

        records_data = bytearray()
        for rec in result.records:
            if rec.kind != "book":
                continue
            fd = {f.name: f.value for f in rec.fields}
            flags = 0
            if fd.get("checked_out"):
                flags |= 0x01
            if fd.get("reference_only"):
                flags |= 0x02
            if fd.get("deleted"):
                flags |= 0x04

            rec_id = int(fd.get("id", 0))
            title_b = str(fd.get("title", "")).encode("cp437", errors="replace")
            author_b = str(fd.get("author", "")).encode("cp437", errors="replace")
            year_val = max(0, int(fd.get("year", YEAR_EPOCH)) - YEAR_EPOCH)
            price_val = int(fd.get("price_cents", 0))
            copies_val = int(fd.get("copies", 0))
            isbn_b = str(fd.get("isbn", "")).ljust(10)[:10].encode("ascii", errors="replace")
            raw_due = _parse_iso_date(fd.get("due_date"))

            # Build record payload
            payload = bytearray()
            payload.append(flags)
            payload.extend(struct.pack("<I", rec_id))
            payload.append(len(title_b))
            payload.extend(title_b)
            payload.append(len(author_b))
            payload.extend(author_b)
            payload.extend(struct.pack("<HHB", year_val, price_val, copies_val))
            payload.extend(isbn_b)
            payload.extend(struct.pack("<H", raw_due))

            chk = sum(payload) & 0xFF
            payload.append(chk)

            # Prepend marker and payload length
            rec_bytes = bytearray([RECORD_MARKER, len(payload)]) + payload
            records_data.extend(rec_bytes)

        # Header extension
        ext_bytes = b""
        if "header_extension" in meta:
            ext_bytes = bytes.fromhex(str(meta["header_extension"]))
        elif "software" in meta:
            ext_bytes = str(meta["software"]).encode("cp437") + b"\x00"

        data_offset = HEADER_MIN_SIZE + len(ext_bytes)
        count = len(result.records)

        header = bytearray(MAGIC)
        header.append(version_major)
        header.append(version_minor)
        header.extend(struct.pack("<HHHH", count, dos_date, dos_time, data_offset))
        header.extend(struct.pack("<H", branch_id))
        header.extend(ext_bytes)

        file_data = header + records_data
        trailer_crc = sum(file_data) & 0xFFFF
        trailer = bytearray(TRAILER_MAGIC) + struct.pack("<H", trailer_crc)
        return bytes(file_data + trailer)


if __name__ == "__main__":
    run_standalone(Libra98Decoder)
