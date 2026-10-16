# WKS

## Summary

WKS is the native spreadsheet file format of Lotus 1-2-3 Release 1A for DOS (context hint: "Spreadsheet saved on a DOS PC, early 1990s"). The format consists of a sequential record stream beginning with a Beginning-of-File (BOF) record and concluding with an End-of-File (EOF) record. Studied samples: `kit/samples/s11.wks` (452 bytes, valid), `kit/samples/s12.wks` (409 bytes, contains unknown record 0x00fa and blank cell), `kit/samples/s13.wks` (409 bytes, truncated during number record at offset 401). Reference output calibrated: `kit/expected_outputs/s11.wks.json`.

## Identification

Files begin with a 4-byte BOF record header: opcode `0x0000` (`00 00`) followed by length `0x0002` (`02 00`), and a 2-byte version payload `0x0404` (`04 04`).
- Magic bytes at offset 0: `00 00 02 00 04 04`.
- Probing:
  - Exact match of 6-byte sequence `00 00 02 00 04 04` gives probe score 1.0.
  - Opcode 0x0000 with length 2 but unrecognized version gives probe score 0.6.
  - Extension `.wks` serves as a tie-breaker hint only.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 2 | u16 | LE | bof_opcode | BOF record opcode (`0x0000`) | confirmed in s11, s12, s13 |
| 0x02 | 2 | u16 | LE | bof_length | BOF payload length (2 bytes) | confirmed in s11, s12, s13 |
| 0x04 | 2 | u16 | LE | version_code | Lotus spreadsheet version (`0x0404`) | s11.wks.json metadata |
| 0x06 | 4 | header | LE | next_record | Next record header (opcode, length) | stream continues until EOF |

## Records

Every record consists of a 4-byte header (`<HH`, 2-byte opcode and 2-byte length) followed by `length` payload bytes:
- `0x0000` (BOF): Length 2, payload is version code `0x0404`.
- `0x0001` (EOF): Length 0, marks end of spreadsheet data.
- `0x0006` (RANGE): Length 8, 4 uint16le values `(col_start, row_start, col_end, row_end)`. Offsets define spreadsheet bounds (e.g., `(0, 0, 3, 4)` maps to `"A1:D5"`).
- `0x0008` (COLUMN_WIDTH): Length 3, `<HB` (column uint16le, width uint8).
- `0x000c` (BLANK): Length 5, format byte (1 byte), col (uint16le), row (uint16le).
- `0x000d` (INTEGER): Length 7, format byte (1 byte), col (uint16le), row (uint16le), integer value (int16le).
- `0x000e` (NUMBER): Length 13, format byte (1 byte), col (uint16le), row (uint16le), float value (64-bit IEEE 754 double little-endian).
- `0x000f` (LABEL): Length >= 6, format byte (1 byte), col (uint16le), row (uint16le), alignment prefix (1 byte: `'` left, `"` right, `^` center, `\` repeat), followed by null-terminated ASCII string.
- `0x0010` (FORMULA): Length >= 15, format byte, col, row, cached_value (64-bit IEEE 754 double little-endian), formula length (uint16le), raw formula bytecode (hex-encoded in output).
- Global settings opcodes (`0x0002` CALC_MODE, `0x0003` CALC_ORDER, `0x0004` SPLIT, `0x0005` SYNC, `0x0007` WINDOW, `0x000b` QUERY): Skipped or stored in metadata.

Cell coordinates are 0-based integers for `col` and `row` fields, while cell labels are 1-based alphanumeric strings (e.g., `col: 1, row: 1` -> `"B2"`).

## Checksums

None. Lotus 1-2-3 WKS records do not contain CRC or checksum fields. Record integrity is verified via framing bounds and EOF termination.

## Compression and obfuscation

None. All integer, floating point, and text data are stored uncompressed.

## Damage handling

- **Unknown opcodes:** Safely skipped using their declared length. Reported as `unknown_record` damage with `lossy: false`. File status becomes `partial`.
- **Truncation:** If a record's declared length exceeds remaining file bytes, or file ends before record header can be read, decoding halts. Reported as `truncated` damage covering `[offset, file_size)` with `lossy: true`. File status becomes `partial`.
- **Resynchronization:** In damaged streams, the decoder scans for plausible record headers matching valid opcodes and reasonable lengths.

## Open questions

- Full formula opcode expression parsing: Formula AST evaluation is out of scope per contract; raw bytecode is preserved in `formula_raw_hex`.
- Detailed date formatting flags: Date-formatted cells use special format bytes (bits 4-6 = 7) and map day serial numbers from epoch 1899-12-30.
