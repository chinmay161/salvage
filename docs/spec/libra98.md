# LIBRA-98

## Summary

LIBRA-98 is a record-based municipal library circulation catalogue format (context hint: "Municipal library circulation desk PC, about 1998"). Studied: `kit/samples/s01.dat` (289 bytes, clean), `kit/samples/s02.dat` (424 bytes, clean with complex flags), `kit/samples/s03.dat` (311 bytes, clean v2.1 with header extension), `kit/samples/s04.dat` (259 bytes, truncated at record 5), and `kit/samples/s29_almost_libra.dat` (7 bytes, negative test case).

## Identification

Files begin with ASCII `LB98` (`4C 42 39 38`) at offset 0x00 followed by major version 2 at 0x04. `probe()` requires at least 16 bytes, valid magic, version 2, and a data offset within bounds. If the `END!` trailer with valid 16-bit sum is detected, probe scores 1.0; otherwise 0.8 for valid header. Files shorter than 16 bytes (such as `s29_almost_libra.dat`) or with wrong magic score 0.0. Extensions `.lb9` and `.dat` serve as weak hints.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|---|---|---|---|---|---|---|
| 0x00 | 4 | bytes | — | magic | ASCII `LB98` | all samples |
| 0x04 | 1 | u8 | — | version_major | Format major version (2) | all samples |
| 0x05 | 1 | u8 | — | version_minor | Format minor version (0 in s01/s02/s04, 1 in s03) | s01-s04 |
| 0x06 | 2 | u16 | LE | declared_record_count | Number of records declared | s01-s04 |
| 0x08 | 2 | u16 | LE | created_date | DOS FAT date: `((d >> 9) & 0x7F) + 1980`, `(d >> 5) & 0x0F`, `d & 0x1F` | log 2026-10-16 13:43 |
| 0x0A | 2 | u16 | LE | created_time | DOS FAT time: `(t >> 11) & 0x1F`, `(t >> 5) & 0x3F`, `(t & 0x1F) * 2` | log 2026-10-16 13:43 |
| 0x0C | 2 | u16 | LE | data_offset | Absolute start offset of records (16 for v2.0, 40 for v2.1) | s01-s04 |
| 0x0E | 2 | u16 | LE | branch_id | Library branch identifier | s01-s04 |
| 0x10 | data_offset - 16 | bytes | — | header_extension | Optional banner string padded with `\x00` (e.g. `LIBSYS/98 REL 2.1`) | s03 |

## Records

Records start at `data_offset` and follow sequentially back to back. Each record starts with marker `0xA5`, followed by a 1-byte payload length $N$ (the number of bytes from `flags` up to and including the record checksum). Total record length is $2 + N$.

Fields in order:
- `+0x00` (1B): record marker `0xA5`
- `+0x01` (1B): payload length $N$
- `+0x02` (1B): flags (bit 0 = `checked_out`, bit 1 = `reference_only`, bit 2 = `deleted`)
- `+0x03` (4B u32le): book ID
- `+0x07` (1B u8): title length $L_T$
- `+0x08` ($L_T$ bytes): title string (CP437)
- `+0x08 + L_T` (1B u8): author length $L_A$
- `+0x09 + L_T` ($L_A$ bytes): author string (CP437)
- `+0x09 + L_T + L_A` (2B u16le): year offset from 1500 (`year = year_offset + 1500`)
- `+0x0B + L_T + L_A` (2B u16le): price in cents
- `+0x0D + L_T + L_A` (1B u8): copy count
- `+0x0E + L_T + L_A` (10B ASCII): ISBN string
- `+0x18 + L_T + L_A` (2B u16le): due date (DOS FAT date, 0 if null)
- `+0x1A + L_T + L_A` (1B u8): record checksum (sum8 over flags through due date)

## Checksums

1. Record checksum: 1-byte `sum8` over all payload bytes from `flags` to `due_date` (`sum(rec[2:-1]) & 0xFF`), stored as the last byte of each record. Verified on all 22 complete records across s01–s04.
2. File trailer checksum: 2-byte `sum16` over all bytes from file offset 0 up to `END!` (`sum(data[:idx]) & 0xFFFF`), stored little-endian at `offset + 4` following `END!`. Verified on all clean samples (s01, s02, s03).

## Compression and obfuscation

None. All strings are plaintext CP437, and all numbers are plain little-endian integers.

## Damage handling

- Truncation: If the file ends before declared records finish (e.g. `s04.dat`), or during record header/payload reads, `DamageKind.TRUNCATED` is recorded covering the unread remainder.
- Resync: If record marker `0xA5` is missing or record length is corrupted, `salvage.core.resync` scans forward for `0xA5` with valid length and matching `sum8`. Corrupted bytes are reported as `DamageKind.UNPARSED`.
- Checksum mismatch: If a record's `sum8` fails, its status drops to `Status.UNVERIFIED` and `DamageKind.CHECKSUM` is reported over the record range.
- Trailer truncation/mismatch: A missing or corrupt `END!` trailer produces `DamageKind.TRUNCATED` or `DamageKind.CHECKSUM`.

## Open questions

None. The binary structure, field encodings, bitflags, string character sets, and checksum formulas are fully explained and verified against all genuine samples and official reference outputs.
