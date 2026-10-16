"""WKS: Lotus 1-2-3 Release 1A spreadsheet format decoder.

Stream layout:
- Begins with BOF record (opcode 0x0000, length 2, version code 0x0404).
- Followed by settings records (range 0x0006, column widths 0x0008, window, etc.)
  and cell records (blank 0x000c, integer 0x000d, number 0x000e, label 0x000f,
  formula 0x0010).
- Concludes with EOF record (opcode 0x0001, length 0).
- All records use a 4-byte header: u16le opcode, u16le payload length.
"""

from __future__ import annotations

import datetime
import struct

from salvagekit.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                  Status)
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.standalone import run_standalone

OP_BOF = 0x0000
OP_EOF = 0x0001
OP_RANGE = 0x0006
OP_COL_WIDTH = 0x0008
OP_BLANK = 0x000C
OP_INTEGER = 0x000D
OP_NUMBER = 0x000E
OP_LABEL = 0x000F
OP_FORMULA = 0x0010

KNOWN_SETTINGS = (0x0002, 0x0003, 0x0004, 0x0005, 0x0007, 0x000B)
WKS_VERSION = 0x0404

ALIGNMENT_MAP = {
    0x27: "left",     # '
    0x22: "right",    # "
    0x5E: "center",   # ^
    0x5C: "repeat",   # \
}


def col_to_letter(col: int) -> str:
    """Convert 0-based column index to spreadsheet letter (0 -> 'A', 25 -> 'Z', 26 -> 'AA')."""
    res = ""
    col += 1
    while col > 0:
        col, rem = divmod(col - 1, 26)
        res = chr(65 + rem) + res
    return res


def cell_label(col: int, row: int) -> str:
    """Cell name from 0-based col and row (e.g. col=1, row=1 -> 'B2')."""
    return f"{col_to_letter(col)}{row + 1}"


def lotus_date_to_iso(serial: int) -> str | None:
    """Convert Lotus 1-2-3 date serial number to ISO YYYY-MM-DD string.

    Lotus date serials count from end of 1899. Due to Lotus treating 1900 as a leap
    year (day 60 = Feb 29, 1900), serials >= 60 are offset from 1899-12-30.
    """
    try:
        if serial < 1:
            return None
        base = datetime.date(1899, 12, 30) if serial >= 60 else datetime.date(1899, 12, 31)
        d = base + datetime.timedelta(days=serial)
        return d.isoformat()
    except Exception:
        return None


class WksDecoder(Decoder):
    """Decoder for Lotus 1-2-3 WKS spreadsheet files."""

    name = "WKS"
    extensions = (".wks",)

    def probe(self, data: bytes) -> float:
        """Probe for WKS: starts with BOF record (opcode 0x0000, length 2, version 0x0404)."""
        try:
            if len(data) < 6:
                return 0.0
            op, length, ver = struct.unpack_from("<HHH", data, 0)
            if op != OP_BOF or length != 2:
                return 0.0
            if ver == WKS_VERSION:
                return 1.0
            return 0.6
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode WKS record stream into metadata, cell records, and damage."""
        size = reader.size
        if reader.peek(4) != b"\x00\x00\x02\x00":
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=1.0)

        # -- BOF record --
        bof_off = reader.tell()
        op = reader.u16le("bof.opcode")
        length = reader.u16le("bof.length")
        ver = reader.u16le("bof.version")
        if ver is None:
            result.damage.append(Damage(bof_off, size, DamageKind.TRUNCATED, "BOF record cut short"))
            return result

        result.meta["version_code"] = f"0x{ver:04x}"
        rec_count = 0
        seen_eof = False

        # -- Record Stream Loop --
        while reader.remaining() > 0:
            rec_off = reader.tell()
            if reader.remaining() < 4:
                result.damage.append(Damage(rec_off, size, DamageKind.TRUNCATED,
                                            "file ends with incomplete record header"))
                result.warnings.append(f"truncated header at offset {rec_off}")
                break

            op = reader.u16le(f"record[{rec_count}].opcode")
            length = reader.u16le(f"record[{rec_count}].length")
            if op is None or length is None:
                break

            if length > reader.remaining():
                result.damage.append(Damage(rec_off, size, DamageKind.TRUNCATED,
                                            f"record 0x{op:04x} declared length {length} exceeds file size"))
                result.warnings.append(f"record 0x{op:04x} at offset {rec_off} cut short")
                break

            rec_count += 1
            payload_start = reader.tell()

            if op == OP_EOF:
                # Clean end of spreadsheet stream
                seen_eof = True
                break

            elif op == OP_RANGE:
                c1 = reader.u16le("range.col_start")
                r1 = reader.u16le("range.row_start")
                c2 = reader.u16le("range.col_end")
                r2 = reader.u16le("range.row_end")
                if c1 is not None and r1 is not None and c2 is not None and r2 is not None:
                    result.meta["declared_range"] = f"{cell_label(c1, r1)}:{cell_label(c2, r2)}"
                if length > 8:
                    reader.bytes(length - 8, "range.extra")

            elif op == OP_COL_WIDTH:
                col = reader.u16le("col_width.col")
                width = reader.u8("col_width.width")
                if col is not None and width is not None:
                    if "column_widths" not in result.meta:
                        result.meta["column_widths"] = {}
                    result.meta["column_widths"][col_to_letter(col)] = width
                if length > 3:
                    reader.bytes(length - 3, "col_width.extra")

            elif op == OP_BLANK:
                fmt = reader.u8("blank.fmt")
                col = reader.u16le("blank.col")
                row = reader.u16le("blank.row")
                if col is not None and row is not None:
                    c_name = cell_label(col, row)
                    fields = [
                        Field("cell", c_name, rec_off + 5, 4, Status.CONSISTENT),
                        Field("col", col, rec_off + 5, 2, Status.CONSISTENT),
                        Field("row", row, rec_off + 7, 2, Status.CONSISTENT),
                        Field("type", "blank", rec_off, 2, Status.CONSISTENT),
                        Field("value", None, rec_off, 0, Status.CONSISTENT),
                    ]
                    result.records.append(Record(offset=rec_off, status=Status.CONSISTENT,
                                                 kind="blank", fields=fields))
                if length > 5:
                    reader.bytes(length - 5, "blank.extra")

            elif op == OP_INTEGER:
                fmt = reader.u8("integer.fmt")
                col = reader.u16le("integer.col")
                row = reader.u16le("integer.row")
                val = reader.i16le("integer.value")
                if col is not None and row is not None and val is not None:
                    c_name = cell_label(col, row)
                    fields = [
                        Field("cell", c_name, rec_off + 5, 4, Status.CONSISTENT),
                        Field("col", col, rec_off + 5, 2, Status.CONSISTENT),
                        Field("row", row, rec_off + 7, 2, Status.CONSISTENT),
                        Field("type", "integer", rec_off, 2, Status.CONSISTENT),
                        Field("value", val, rec_off + 9, 2, Status.CONSISTENT),
                    ]
                    # Date check: format bits 4-6 == 7 and bits 0-3 in (1, 2, 3, 8)
                    if fmt is not None and (fmt & 0x70) == 0x70 and (fmt & 0x0F) in (1, 2, 3, 8):
                        iso = lotus_date_to_iso(val)
                        if iso:
                            fields.append(Field("iso_date", iso, rec_off + 9, 2, Status.CONSISTENT))
                    result.records.append(Record(offset=rec_off, status=Status.CONSISTENT,
                                                 kind="integer", fields=fields))
                if length > 7:
                    reader.bytes(length - 7, "integer.extra")

            elif op == OP_NUMBER:
                fmt = reader.u8("number.fmt")
                col = reader.u16le("number.col")
                row = reader.u16le("number.row")
                val_raw = reader.unpack("<d", "number.value")
                val = val_raw[0] if val_raw else None
                if col is not None and row is not None and val is not None:
                    c_name = cell_label(col, row)
                    fields = [
                        Field("cell", c_name, rec_off + 5, 4, Status.CONSISTENT),
                        Field("col", col, rec_off + 5, 2, Status.CONSISTENT),
                        Field("row", row, rec_off + 7, 2, Status.CONSISTENT),
                        Field("type", "number", rec_off, 2, Status.CONSISTENT),
                        Field("value", val, rec_off + 9, 8, Status.CONSISTENT),
                    ]
                    if fmt is not None and (fmt & 0x70) == 0x70 and (fmt & 0x0F) in (1, 2, 3, 8):
                        iso = lotus_date_to_iso(int(val))
                        if iso:
                            fields.append(Field("iso_date", iso, rec_off + 9, 8, Status.CONSISTENT))
                    result.records.append(Record(offset=rec_off, status=Status.CONSISTENT,
                                                 kind="number", fields=fields))
                if length > 13:
                    reader.bytes(length - 13, "number.extra")

            elif op == OP_LABEL:
                fmt = reader.u8("label.fmt")
                col = reader.u16le("label.col")
                row = reader.u16le("label.row")
                pfx = reader.u8("label.prefix")
                alignment = ALIGNMENT_MAP.get(pfx, "left")
                str_bytes = reader.bytes(length - 6, "label.text")
                raw_str = str_bytes.split(b"\x00", 1)[0]
                text_val = raw_str.decode("latin1", errors="replace")
                if col is not None and row is not None:
                    c_name = cell_label(col, row)
                    fields = [
                        Field("cell", c_name, rec_off + 5, 4, Status.CONSISTENT),
                        Field("col", col, rec_off + 5, 2, Status.CONSISTENT),
                        Field("row", row, rec_off + 7, 2, Status.CONSISTENT),
                        Field("type", "label", rec_off, 2, Status.CONSISTENT),
                        Field("value", text_val, rec_off + 10, len(raw_str), Status.CONSISTENT),
                        Field("alignment", alignment, rec_off + 9, 1, Status.CONSISTENT),
                    ]
                    result.records.append(Record(offset=rec_off, status=Status.CONSISTENT,
                                                 kind="label", fields=fields))

            elif op == OP_FORMULA:
                fmt = reader.u8("formula.fmt")
                col = reader.u16le("formula.col")
                row = reader.u16le("formula.row")
                cached_raw = reader.unpack("<d", "formula.cached_value")
                cached_val = cached_raw[0] if cached_raw else None
                f_len = reader.u16le("formula.length")
                f_bytes = reader.bytes(f_len, "formula.bytes") if f_len is not None else b""
                if col is not None and row is not None and cached_val is not None:
                    c_name = cell_label(col, row)
                    fields = [
                        Field("cell", c_name, rec_off + 5, 4, Status.CONSISTENT),
                        Field("col", col, rec_off + 5, 2, Status.CONSISTENT),
                        Field("row", row, rec_off + 7, 2, Status.CONSISTENT),
                        Field("type", "formula", rec_off, 2, Status.CONSISTENT),
                        Field("cached_value", cached_val, rec_off + 9, 8, Status.CONSISTENT),
                        Field("formula_raw_hex", f_bytes.hex(), rec_off + 19, len(f_bytes), Status.CONSISTENT),
                    ]
                    result.records.append(Record(offset=rec_off, status=Status.CONSISTENT,
                                                 kind="formula", fields=fields))
                rem = length - (15 + (f_len or 0))
                if rem > 0:
                    reader.bytes(rem, "formula.extra")

            elif op in KNOWN_SETTINGS:
                reader.bytes(length, f"settings[0x{op:04x}]")

            else:
                # Unknown opcode: safely skip using declared length
                reader.bytes(length, f"unknown[0x{op:04x}]")
                result.damage.append(Damage(rec_off, rec_off + 4 + length, DamageKind.UNKNOWN_RECORD,
                                            f"unknown record opcode 0x{op:04x} length {length}",
                                            lossy=False))
                result.warnings.append(f"unknown record 0x{op:04x} at offset {rec_off}")

        if not seen_eof and not any(d.kind == DamageKind.TRUNCATED for d in result.damage):
            result.damage.append(Damage(reader.tell(), size, DamageKind.TRUNCATED, "file truncated before EOF record"))
            result.warnings.append("missing EOF record")

        # Sort records deterministically by row then col (same as reference outputs)
        def _sort_key(r: Record) -> tuple[int, int]:
            row = next((f.value for f in r.fields if f.name == "row"), 0)
            col = next((f.value for f in r.fields if f.name == "col"), 0)
            return (int(row), int(col))

        result.records.sort(key=_sort_key)
        return result


if __name__ == "__main__":
    run_standalone(WksDecoder)
