"""EBCDIC-DUMP: decoder for IBM university mainframe tape database dumps.

Handles both unblocked (RECFM=V) and blocked (RECFM=VB) mainframe files.
Records are variable-length, preceded by 4-byte Record Descriptor Words (RDW).
In blocked files, blocks are preceded by 4-byte Block Descriptor Words (BDW).
Text is encoded in EBCDIC (cp037), and numbers use IBM COMP-3 packed decimal
or big-endian binary integers.
"""

from __future__ import annotations

import datetime
import struct

from salvagekit.core.model import Damage, DamageKind, DecodeResult, Field, Record, Status
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.resync import ByteView, resync
from salvagekit.core.standalone import run_standalone

HEADER_TYPE = 0xC8   # 'H' in EBCDIC cp037
DETAIL_TYPE = 0xC4   # 'D' in EBCDIC cp037
TRAILER_TYPE = 0xE3  # 'T' in EBCDIC cp037

HEADER_RDW_LEN = 33   # 4 bytes RDW + 29 bytes payload
DETAIL_RDW_LEN = 48   # 4 bytes RDW + 44 bytes payload
TRAILER_RDW_LEN = 14  # 4 bytes RDW + 10 bytes payload

VALID_POS_SIGNS = (0x0C, 0x0F, 0x0A, 0x0E)
VALID_NEG_SIGNS = (0x0D, 0x0B)
VALID_SIGNS = VALID_POS_SIGNS + VALID_NEG_SIGNS


def parse_packed_decimal(data: bytes, decimals: int = 0) -> tuple[int | float | None, str | None]:
    """Parse IBM COMP-3 packed decimal bytes.

    Returns (value, None) on success, or (None, error_reason) on invalid digits or sign.
    """
    val = 0
    for i, b in enumerate(data):
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high > 9:
            return None, f"invalid high nibble {high:#x} in byte {i}"
        if i == len(data) - 1:
            if low not in VALID_SIGNS:
                return None, f"invalid sign nibble {low:#x}"
            val = val * 10 + high
            if low in VALID_NEG_SIGNS:
                val = -val
        else:
            if low > 9:
                return None, f"invalid low nibble {low:#x} in byte {i}"
            val = val * 100 + high * 10 + low
    if decimals > 0:
        return round(val / (10 ** decimals), decimals), None
    return val, None


def parse_ebcdic_date(data: bytes) -> tuple[str | None, str | None]:
    """Parse 5-byte COMP-3 packed decimal date YYYYMMDD.

    Returns (iso_date_string, None) on success, or (None, error_reason).
    """
    raw_val, err = parse_packed_decimal(data, decimals=0)
    if err is not None or raw_val is None:
        return None, err or "bad packed decimal"
    if raw_val <= 0:
        return None, f"non-positive date value {raw_val}"
    s = f"{raw_val:08d}"
    if len(s) != 8:
        return None, f"date digits length {len(s)} != 8"
    try:
        year = int(s[:4])
        month = int(s[4:6])
        day = int(s[6:8])
        dt = datetime.date(year, month, day)
        return dt.isoformat(), None
    except (ValueError, OverflowError) as exc:
        return None, f"impossible date {s}: {exc}"


def looks_like_record(view: ByteView, offset: int) -> bool:
    """Strict resync check for next valid detail or trailer record boundary."""
    # Option 1: Detail record RDW directly
    if (view.bytes(offset, 4) == b"\x00\x30\x00\x00" and
            view.u8(offset + 4) == DETAIL_TYPE and
            view.bytes(offset + 46, 2) == b"\x40\x40"):
        return True
    # Option 2: Trailer record RDW directly
    if (view.bytes(offset, 4) == b"\x00\x0e\x00\x00" and
            view.u8(offset + 4) == TRAILER_TYPE):
        return True
    # Option 3: BDW followed by Detail record RDW
    if (view.u16be(offset + 2) == 0 and
            view.bytes(offset + 4, 4) == b"\x00\x30\x00\x00" and
            view.u8(offset + 8) == DETAIL_TYPE):
        return True
    # Option 4: BDW followed by Trailer record RDW
    if (view.u16be(offset + 2) == 0 and
            view.bytes(offset + 4, 4) == b"\x00\x0e\x00\x00" and
            view.u8(offset + 8) == TRAILER_TYPE):
        return True
    return False


def looks_like_bdw(view: ByteView, offset: int) -> bool:
    """Check if offset looks like a Block Descriptor Word."""
    if view.u16be(offset + 2) != 0:
        return False
    blen = view.u16be(offset)
    if blen is None or blen < 4:
        return False
    return (view.bytes(offset + 4, 4) in (b"\x00\x21\x00\x00", b"\x00\x30\x00\x00", b"\x00\x0e\x00\x00") and
            view.u8(offset + 8) in (HEADER_TYPE, DETAIL_TYPE, TRAILER_TYPE))


def is_valid_detail_record(data: bytes, off: int) -> bool:
    """Check if a valid detail record starts at off (RDW 48, flags 00 00, type 'D', 6 EBCDIC digits)."""
    if len(data) < off + 48:
        return False
    if data[off:off + 4] != b"\x00\x30\x00\x00":
        return False
    if data[off + 4] != DETAIL_TYPE:
        return False
    return all(0xF0 <= b <= 0xF9 for b in data[off + 5:off + 11])


def has_detail_chain(data: bytes, start_off: int) -> bool:
    """Check if at least 2 consecutive detail records start at start_off."""
    if not is_valid_detail_record(data, start_off):
        return False
    if is_valid_detail_record(data, start_off + 48):
        return True
    if is_valid_detail_record(data, start_off + 48 + 4):
        return True
    return False


class EbcdicDumpDecoder(Decoder):
    """Decoder for IBM mainframe university student tape dumps (EBCDIC-DUMP)."""

    name = "EBCDIC-DUMP"
    extensions = (".000",)

    def probe(self, data: bytes) -> float:
        """Strict probe: header checks or damaged-header detail chain. Never raises."""
        try:
            if len(data) < 33:
                return 0.0

            # Check unblocked (RECFM=V): RDW at offset 0 (len 33, flags 0, type 'H')
            rlen = struct.unpack_from(">H", data, 0)[0]
            rflags = struct.unpack_from(">H", data, 2)[0]
            if rflags == 0 and rlen == HEADER_RDW_LEN and data[4] == HEADER_TYPE:
                title_raw = data[5:25]
                date_raw = data[25:33]
                if all(b == 0x40 or 0xC1 <= b <= 0xE9 or 0xF0 <= b <= 0xF9 for b in title_raw):
                    if all(0xF0 <= b <= 0xF9 for b in date_raw):
                        return 1.0
                return 0.6

            # Check blocked (RECFM=VB): BDW at offset 0, RDW at offset 4
            if len(data) >= 37:
                blen = struct.unpack_from(">H", data, 0)[0]
                bflags = struct.unpack_from(">H", data, 2)[0]
                rlen = struct.unpack_from(">H", data, 4)[0]
                rflags = struct.unpack_from(">H", data, 6)[0]
                if (bflags == 0 and rflags == 0 and rlen == HEADER_RDW_LEN and
                        blen >= rlen + 4 and data[8] == HEADER_TYPE):
                    title_raw = data[9:29]
                    date_raw = data[29:37]
                    if all(b == 0x40 or 0xC1 <= b <= 0xE9 or 0xF0 <= b <= 0xF9 for b in title_raw):
                        if all(0xF0 <= b <= 0xF9 for b in date_raw):
                            return 1.0
                    return 0.6

            # Check damaged header: chain of at least 2 valid detail records
            candidates = [0, 33, 4, 37]
            if len(data) >= 4:
                r0 = struct.unpack_from(">H", data, 0)[0]
                if 4 <= r0 <= 256:
                    candidates.append(r0)
            if len(data) >= 8:
                r4 = struct.unpack_from(">H", data, 4)[0]
                if 4 <= r4 <= 256:
                    candidates.append(4 + r4)
            for c in candidates:
                if has_detail_chain(data, c):
                    return 0.75

            return 0.0
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode EBCDIC-DUMP file contents."""
        result = DecodeResult(format=self.name, confidence=0.0)

        # Initialize required metadata keys
        result.meta["title"] = None
        result.meta["run_date"] = None
        result.meta["trailer_count"] = None
        result.meta["trailer_credits_total"] = None

        if reader.size < 4:
            result.damage.append(Damage(0, reader.size, DamageKind.TRUNCATED, "file too short for header RDW"))
            return result

        view = ByteView(reader)

        # Determine if blocked (RECFM=VB) or unblocked (RECFM=V)
        is_blocked = False
        prefix = reader.peek(9)
        if len(prefix) >= 9 and prefix[4:8] == b"\x00\x21\x00\x00" and prefix[8] == HEADER_TYPE:
            is_blocked = True
        elif len(prefix) >= 5 and prefix[:4] == b"\x00\x21\x00\x00" and prefix[4] == HEADER_TYPE:
            is_blocked = False
        else:
            data_sample = reader.peek(128)
            if is_valid_detail_record(data_sample, 37) or is_valid_detail_record(data_sample, 4):
                is_blocked = True
            elif is_valid_detail_record(data_sample, 33) or is_valid_detail_record(data_sample, 0):
                is_blocked = False

        result.format = f"EBCDIC-DUMP ({'RECFM=VB' if is_blocked else 'RECFM=V'})"
        result.confidence = 0.6

        block_index = 0
        current_block_end = reader.size
        header_parsed = False
        trailer_parsed = False
        trailer_count_val: int | None = None
        trailer_credits_val: int | None = None
        trailer_count_off = 0
        trailer_credits_off = 0
        detail_count = 0
        is_truncated = False

        while reader.remaining() > 0:
            # If blocked mode and at block start
            if is_blocked and (reader.tell() >= current_block_end or looks_like_bdw(view, reader.tell())):
                if reader.remaining() < 4:
                    result.damage.append(Damage(reader.tell(), reader.size, DamageKind.TRUNCATED,
                                                "file truncated inside block descriptor word"))
                    is_truncated = True
                    break
                block_off = reader.tell()
                blen = reader.u16be(f"block[{block_index}].length")
                bflags = reader.bytes(2, f"block[{block_index}].flags")
                if blen is None or bflags is None:
                    result.damage.append(Damage(block_off, reader.size, DamageKind.TRUNCATED,
                                                "block header cut short"))
                    is_truncated = True
                    break
                if blen < 4:
                    result.damage.append(Damage(block_off, block_off + 4, DamageKind.BAD_LENGTH,
                                                f"block length {blen} < 4"))
                    break
                current_block_end = block_off + blen
                if current_block_end > reader.size:
                    result.damage.append(Damage(block_off, reader.size, DamageKind.TRUNCATED,
                                                f"block length {blen} extends beyond end of file"))
                    is_truncated = True
                    current_block_end = reader.size
                block_index += 1

            rec_off = reader.tell()
            if is_blocked and rec_off >= current_block_end:
                continue

            if reader.remaining() < 4:
                result.damage.append(Damage(rec_off, reader.size, DamageKind.TRUNCATED,
                                            "file ends inside record descriptor word"))
                is_truncated = True
                break

            rlen = view.u16be(rec_off)
            rflags = view.u16be(rec_off + 2)
            rtype = view.u8(rec_off + 4) if view.size > rec_off + 4 else None

            # Validate record start
            valid_header = (not header_parsed and rlen == HEADER_RDW_LEN and rtype == HEADER_TYPE)
            valid_detail = (rlen == DETAIL_RDW_LEN and rtype == DETAIL_TYPE)
            valid_trailer = (rlen == TRAILER_RDW_LEN and rtype == TRAILER_TYPE)
            valid_start = (rlen is not None and rflags == 0 and
                           (valid_header or valid_detail or valid_trailer))

            if not valid_start:
                # Check if file truncated inside record
                if rlen is not None and rec_off + rlen > reader.size:
                    result.damage.append(Damage(rec_off, reader.size, DamageKind.TRUNCATED,
                                                f"record at offset {rec_off} truncated by end of file"))
                    is_truncated = True
                    break

                # Resync to next valid record (starting strictly at rec_off + 1 to guarantee forward progress)
                hit = resync(reader, looks_like_record, start=rec_off + 1)
                skip_end = hit.offset if hit.offset is not None else reader.size
                result.damage.append(Damage(rec_off, skip_end, DamageKind.UNPARSED_BYTES,
                                            f"invalid record header at {rec_off}; scanning for next record"))
                if hit.offset is None:
                    break
                continue

            # Check if record extends past end of file
            assert rlen is not None
            if rec_off + rlen > reader.size:
                result.damage.append(Damage(rec_off, reader.size, DamageKind.TRUNCATED,
                                            f"record of length {rlen} truncated by end of file"))
                is_truncated = True
                break

            # Check if record extends past current block in blocked mode
            if is_blocked and rec_off + rlen > current_block_end:
                result.damage.append(Damage(rec_off, current_block_end, DamageKind.BAD_LENGTH,
                                            f"record of length {rlen} exceeds block boundary {current_block_end}"))
                break

            # Read Header Record
            if valid_header:
                reader.u16be("header.length")
                reader.bytes(2, "header.flags")
                reader.bytes(1, "header.type")
                title_bytes = reader.bytes(20, "header.title")
                date_bytes = reader.bytes(8, "header.run_date")
                title_str = title_bytes.decode("cp037", errors="replace").rstrip()
                date_str = date_bytes.decode("cp037", errors="replace")
                result.meta["title"] = title_str
                if len(date_str) == 8 and date_str.isdigit():
                    result.meta["run_date"] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                else:
                    result.meta["run_date"] = date_str
                    result.damage.append(Damage(rec_off + 25, rec_off + 33, DamageKind.INVALID_VALUE,
                                                f"invalid header run_date: {date_str!r}"))
                header_parsed = True
                continue

            # Read Trailer Record
            if valid_trailer:
                reader.u16be("trailer.length")
                reader.bytes(2, "trailer.flags")
                reader.bytes(1, "trailer.type")
                trailer_count_off = reader.tell()
                count_bytes = reader.bytes(4, "trailer.count")
                trailer_credits_off = reader.tell()
                credits_bytes = reader.bytes(5, "trailer.credits_total")

                c_val, c_err = parse_packed_decimal(count_bytes, decimals=0)
                cr_val, cr_err = parse_packed_decimal(credits_bytes, decimals=0)

                if c_err is not None or c_val is None:
                    result.damage.append(Damage(trailer_count_off, trailer_count_off + 4, DamageKind.INVALID_VALUE,
                                                f"corrupted trailer count: {c_err}"))
                    result.meta["trailer_count"] = None
                else:
                    trailer_count_val = int(c_val)
                    result.meta["trailer_count"] = trailer_count_val

                if cr_err is not None or cr_val is None:
                    result.damage.append(Damage(trailer_credits_off, trailer_credits_off + 5, DamageKind.INVALID_VALUE,
                                                f"corrupted trailer credits total: {cr_err}"))
                    result.meta["trailer_credits_total"] = None
                else:
                    trailer_credits_val = int(cr_val)
                    result.meta["trailer_credits_total"] = trailer_credits_val

                trailer_parsed = True
                continue

            # Read Student Detail Record
            if valid_detail:
                rec_i = detail_count
                detail_count += 1

                reader.u16be(f"record[{rec_i}].length")
                reader.bytes(2, f"record[{rec_i}].flags")
                reader.bytes(1, f"record[{rec_i}].type")

                # Field 1: student_id (6 bytes, EBCDIC digits)
                sid_off = reader.tell()
                sid_bytes = reader.bytes(6, f"record[{rec_i}].student_id")
                sid_str = sid_bytes.decode("cp037", errors="replace")
                sid_valid = len(sid_str) == 6 and sid_str.isdigit()

                # Field 2: name (20 bytes, EBCDIC text)
                name_off = reader.tell()
                name_bytes = reader.bytes(20, f"record[{rec_i}].name")
                name_str = name_bytes.decode("cp037", errors="replace").rstrip()

                # Field 3: dob (5 bytes, COMP-3 packed decimal date YYYYMMDD)
                dob_off = reader.tell()
                dob_bytes = reader.bytes(5, f"record[{rec_i}].dob")
                dob_iso, dob_err = parse_ebcdic_date(dob_bytes)

                # Field 4: gpa (3 bytes, COMP-3 packed decimal / 100)
                gpa_off = reader.tell()
                gpa_bytes = reader.bytes(3, f"record[{rec_i}].gpa")
                gpa_val, gpa_err = parse_packed_decimal(gpa_bytes, decimals=2)
                gpa_valid = gpa_err is None and gpa_val is not None and 0.0 <= gpa_val <= 4.0

                # Field 5: credits (2 bytes, u16be binary integer)
                credits_off = reader.tell()
                credits_val = reader.u16be(f"record[{rec_i}].credits")
                credits_valid = credits_val is not None and credits_val >= 0

                # Field 6: status (1 byte, EBCDIC char)
                status_off = reader.tell()
                status_byte = reader.bytes(1, f"record[{rec_i}].status")
                status_str = status_byte.decode("cp037", errors="replace")
                status_valid = len(status_str) == 1 and status_str.isalpha()

                # Field 7: balance (4 bytes, COMP-3 packed decimal / 100)
                bal_off = reader.tell()
                bal_bytes = reader.bytes(4, f"record[{rec_i}].balance")
                bal_val, bal_err = parse_packed_decimal(bal_bytes, decimals=2)
                bal_valid = bal_err is None and bal_val is not None

                # Padding (2 bytes, EBCDIC spaces 0x4040)
                pad_bytes = reader.peek(2)
                if pad_bytes == b"\x40\x40":
                    reader.bytes(2, "padding")
                else:
                    reader.bytes(2, f"record[{rec_i}].padding")

                # Validate record fields and construct Record
                rec_issues: list[DamageKind] = []

                if not sid_valid:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    result.damage.append(Damage(sid_off, sid_off + 6, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: invalid student_id {sid_str!r}"))
                    sid_field = Field("student_id", None, sid_off, 6, Status.LOST, "invalid student_id digits")
                else:
                    sid_field = Field("student_id", sid_str, sid_off, 6, Status.CONSISTENT, "EBCDIC string")

                name_field = Field("name", name_str, name_off, 20, Status.CONSISTENT, "EBCDIC string")

                if dob_iso is None:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    result.damage.append(Damage(dob_off, dob_off + 5, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: {dob_err}"))
                    dob_field = Field("dob", None, dob_off, 5, Status.LOST, f"invalid dob: {dob_err}")
                else:
                    dob_field = Field("dob", dob_iso, dob_off, 5, Status.CONSISTENT, "COMP-3 packed decimal date")

                if not gpa_valid:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    err_msg = gpa_err or f"GPA {gpa_val} out of range [0.0, 4.0]"
                    result.damage.append(Damage(gpa_off, gpa_off + 3, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: {err_msg}"))
                    gpa_field = Field("gpa", None, gpa_off, 3, Status.LOST, err_msg)
                else:
                    gpa_field = Field("gpa", gpa_val, gpa_off, 3, Status.CONSISTENT, "COMP-3 packed decimal")

                if not credits_valid or credits_val is None:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    result.damage.append(Damage(credits_off, credits_off + 2, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: invalid credits"))
                    credits_field = Field("credits", None, credits_off, 2, Status.LOST, "invalid credits")
                else:
                    credits_field = Field("credits", credits_val, credits_off, 2, Status.CONSISTENT, "u16be binary")

                if not status_valid:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    result.damage.append(Damage(status_off, status_off + 1, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: invalid status {status_str!r}"))
                    status_field = Field("status", None, status_off, 1, Status.LOST, "invalid status")
                else:
                    status_field = Field("status", status_str, status_off, 1, Status.CONSISTENT, "EBCDIC char")

                if not bal_valid or bal_val is None:
                    rec_issues.append(DamageKind.INVALID_VALUE)
                    result.damage.append(Damage(bal_off, bal_off + 4, DamageKind.INVALID_VALUE,
                                                f"record {rec_i}: {bal_err}"))
                    bal_field = Field("balance", None, bal_off, 4, Status.LOST, bal_err or "invalid balance")
                else:
                    bal_field = Field("balance", bal_val, bal_off, 4, Status.CONSISTENT, "COMP-3 packed decimal")

                rec_status = Status.UNVERIFIED if rec_issues else Status.CONSISTENT
                result.records.append(Record(
                    offset=rec_off,
                    status=rec_status,
                    kind="student",
                    issues=rec_issues,
                    fields=[sid_field, name_field, dob_field, gpa_field, credits_field, status_field, bal_field],
                ))
                continue

        # Consume any trailing padding or unparsed bytes at end of file
        if reader.remaining() > 0 and not is_truncated:
            rem_off = reader.tell()
            rem_bytes = reader.bytes(reader.remaining(), "padding" if reader.peek(reader.remaining()) == bytes(reader.remaining()) else "trailing")
            if rem_bytes != bytes(len(rem_bytes)) and rem_bytes != b"\x40" * len(rem_bytes):
                result.damage.append(Damage(rem_off, reader.size, DamageKind.UNPARSED_BYTES,
                                            "trailing unexplained bytes at end of file", lossy=False))

        # Trailer cross-checks
        if trailer_parsed and not is_truncated:
            # Check trailer count
            if trailer_count_val is not None and trailer_count_val != len(result.records):
                result.damage.append(Damage(trailer_count_off, trailer_count_off + 4, DamageKind.COUNT_MISMATCH,
                                            f"trailer count {trailer_count_val} != {len(result.records)} records found",
                                            lossy=len(result.records) < trailer_count_val))

            # Check trailer credits total
            actual_credits = sum((f.value for r in result.records for f in r.fields
                                  if f.name == "credits" and isinstance(f.value, int)), 0)
            if trailer_credits_val is not None and trailer_credits_val != actual_credits:
                result.damage.append(Damage(trailer_credits_off, trailer_credits_off + 5, DamageKind.COUNT_MISMATCH,
                                            f"trailer credits total {trailer_credits_val} != sum {actual_credits}",
                                            lossy=actual_credits < trailer_credits_val))

        # Final confidence
        if header_parsed and trailer_parsed and not result.damage:
            result.confidence = 1.0
        elif header_parsed and result.records:
            result.confidence = 0.8
        elif result.records:
            result.confidence = 0.7
        else:
            result.confidence = 0.0

        return result


if __name__ == "__main__":
    run_standalone(EbcdicDumpDecoder)
