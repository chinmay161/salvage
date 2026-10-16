# EBCDIC-DUMP

## Summary

EBCDIC-DUMP is a record-based student database dump from an IBM university mainframe tape (context hint: "Dump from a university mainframe tape, 1999"). The format originates from an IBM OS/390 or MVS environment and supports both unblocked variable-length records (RECFM=V) and blocked variable-length records (RECFM=VB). Text is encoded in EBCDIC (cp037), and numeric fields utilize IBM COMP-3 packed decimal representation or big-endian binary integers.

Studied samples:
- `kit/samples/s20.000`: 287 bytes, unblocked (RECFM=V), 1 header, 5 detail records, 1 trailer.
- `kit/samples/s21.000`: 303 bytes, blocked (RECFM=VB), 4 blocks containing 1 header, 5 detail records, 1 trailer.
- `kit/samples/s22.000`: 210 bytes, unblocked (RECFM=V), truncated mid-record in record 4 (3 complete detail records).

## Identification

The format is identified by its mainframe record descriptor words and initial header record:
- Unblocked (RECFM=V): Bytes 0..3 are an RDW declaring record length 33 (`\x00\x21\x00\x00`), followed immediately at offset 4 by header record type 'H' (`\xc8` in EBCDIC cp037).
- Blocked (RECFM=VB): Bytes 0..3 are a BDW declaring block length `L_block >= 37` (`\x00\x55\x00\x00` in s21.000), followed at offset 4 by an RDW declaring length 33 (`\x00\x21\x00\x00`) and header record type 'H' (`\xc8`) at offset 8.

The `probe()` function checks for these prefixes, validates that the header title consists of valid EBCDIC characters (spaces, uppercase Latin letters, digits), and verifies that the 8-byte run date consists of valid EBCDIC digit characters (`\xf0`..`\xf9`). Matching files score 1.0; files with matching length and type 'H' but non-digit date score 0.6. Furthermore, if the header is damaged or missing but followed by a chain of at least 2 valid detail records (RDW length 48, flags 00 00, type 'D', 6 EBCDIC digits for student_id) either at offset 0, after a BDW, or after the corrupted header, `probe()` scores 0.75. All other files score 0.0. The file extension `.000` is used solely as a tie-breaker.

## Layout

### Block Descriptor Word (BDW) — RECFM=VB only

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 2 | u16 | BE | block_length | Total block length including 4-byte BDW | s21.000 offsets 0x00 (85), 0x55 (100), 0xb9 (100), 0x11d (18) |
| 0x02 | 2 | bytes | — | bdw_flags | Block descriptor flags (always `00 00`) | s21.000 |

### Record Descriptor Word (RDW) — Every record

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 2 | u16 | BE | record_length | Total record length including 4-byte RDW | 33 (Header), 48 (Detail), 14 (Trailer) |
| 0x02 | 2 | bytes | — | rdw_flags | Record descriptor flags (always `00 00`) | All samples |

### Header Record Payload (Length = 29 bytes, RDW = 33)

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 1 | char | — | type | Record type indicator: 'H' (`0xc8`) | s20.000:4, s21.000:8, s22.000:4 |
| +0x01 | 20 | string | — | title | EBCDIC cp037 string (e.g. "STUDENT EXTRACT     ") | s20.000:5..25, s20.000.json |
| +0x15 | 8 | string | — | run_date | EBCDIC cp037 digits YYYYMMDD (e.g. "19990314") | s20.000:25..33 -> "1999-03-14" |

### Student Detail Record Payload (Length = 44 bytes, RDW = 48)

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 1 | char | — | type | Record type indicator: 'D' (`0xc4`) | s20.000:37, s21.000:41, s22.000:37 |
| +0x01 | 6 | string | — | student_id | EBCDIC cp037 digits (e.g. "909014") | s20.000:38..44 |
| +0x07 | 20 | string | — | name | EBCDIC cp037 string, "LAST, FIRST" | s20.000:44..64 |
| +0x1B | 5 | packed | — | dob | COMP-3 packed decimal: YYYYMMDD + sign | s20.000:64..69 (`01 97 81 01 1f`) -> 1978-10-11 |
| +0x20 | 3 | packed | — | gpa | COMP-3 packed decimal: 2 decimals + sign | s20.000:69..72 (`00 26 3c`) -> 2.63 |
| +0x23 | 2 | u16 | BE | credits | Earned credits count (binary integer) | s20.000:72..74 (`00 28`) -> 40 |
| +0x25 | 1 | char | — | status | Academic status: 'G' (graduated), 'W' (withdrawn), 'A' (active) | s20.000:74..75 (`0xc7` = 'G') |
| +0x26 | 4 | packed | — | balance | COMP-3 packed decimal: 2 decimals, sign in last nibble (C/F positive, D negative) | s20.000:75..79 (`00 69 83 6c` -> 698.36), s21.000 (`00 12 55 0d` -> -125.50) |
| +0x2A | 2 | bytes | — | padding | Trailing spaces (`40 40`) | All detail records |

### Trailer Record Payload (Length = 10 bytes, RDW = 14)

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 1 | char | — | type | Record type indicator: 'T' (`0xe3`) | s20.000:277, s21.000:293 |
| +0x01 | 4 | packed | — | trailer_count | COMP-3 packed decimal: student record count (7 digits + sign) | s20.000:278..282 (`00 00 00 5f`) -> 5 |
| +0x05 | 5 | packed | — | trailer_credits_total | COMP-3 packed decimal: sum of credits (9 digits + sign) | s20.000:282..287 (`00 00 00 40 2f`) -> 402, s21.000 (`00 00 00 54 6f`) -> 546 |

## Records

Records are sequenced as follows:
1. Exactly one Header record ('H', RDW length 33).
2. Zero or more Detail records ('D', RDW length 48).
3. Exactly one Trailer record ('T', RDW length 14).

In unblocked files, records are placed consecutively. In blocked files, records are packed into blocks of up to `block_length` bytes, with blocks placed consecutively.

Field mappings to the contract shape (`salvagekit/core/contract_shapes.py`):
- `student_id`: 6-character string decoded from EBCDIC cp037 digits.
- `name`: String decoded from EBCDIC cp037, trailing whitespace stripped.
- `dob`: ISO date string `YYYY-MM-DD` decoded from the 5-byte COMP-3 packed decimal field.
- `gpa`: Float decoded from 3-byte COMP-3 packed decimal, divided by 100.0.
- `credits`: Unsigned 16-bit big-endian integer.
- `status`: 1-character string decoded from EBCDIC cp037.
- `balance`: Float decoded from 4-byte COMP-3 packed decimal (positive for signs 0x0C, 0x0F, 0x0A, 0x0E; negative for 0x0D, 0x0B), divided by 100.0.

Graded metadata keys:
- `title`: String from header payload, trailing whitespace stripped.
- `run_date`: ISO date string `YYYY-MM-DD` from 8-character header date string.
- `trailer_count`: Integer from trailer packed decimal field.
- `trailer_credits_total`: Integer from trailer packed decimal field.

## Checksums

There are no per-record checksums or CRCs in this mainframe format. Data integrity and completeness are verified via the trailer record:
1. `trailer_count` cross-check: Must equal the number of detail records decoded.
2. `trailer_credits_total` cross-check: Must equal the exact sum of `credits` across all decoded detail records.

When both trailer cross-checks pass and no records were damaged, the records are marked `Status.CONSISTENT`.

## Compression and obfuscation

None. Numbers are encoded in standard IBM System/370-390 COMP-3 (packed decimal) format: two BCD decimal digits per byte, with the least significant nibble storing the sign (0x0C, 0x0F, 0x0A, 0x0E = positive; 0x0D, 0x0B = negative).

## Damage handling

1. **Truncation:** If a file ends prematurely (e.g. `s22.000` where the 4th record is cut short at offset 210 with 33 of 48 bytes available):
   - All preceding complete records are preserved.
   - The truncated range `[offset, file_size)` is reported as `DamageKind.TRUNCATED` (lossy=True).
   - If truncation explains a missing trailer or record count difference, only `TRUNCATED` damage is reported (no duplicate `COUNT_MISMATCH`), following the s04 answer key convention.
2. **Trailer Count Mismatch:** If the trailer is reached and `trailer_count != len(records)`, `DamageKind.COUNT_MISMATCH` is reported over the trailer count field bytes.
3. **Trailer Credits Mismatch:** If `trailer_credits_total != sum(credits)`, `DamageKind.COUNT_MISMATCH` is reported over the trailer credits total field bytes. We chose `COUNT_MISMATCH` because `trailer_credits_total` represents an aggregate tally/count of credit units, directly fitting the contract's definition of declared count disagreement.
4. **Invalid Values:**
   - Invalid COMP-3 packed decimal digits (nibble > 9 in non-sign positions) or invalid sign nibbles.
   - Impossible dates (e.g. invalid month or day).
   - GPA out of the standard 0.00..4.00 range.
   When any such corruption is detected, the affected field is set to `None` (`Status.LOST`), the record is marked `Status.UNVERIFIED` with `issues: [DamageKind.INVALID_VALUE]`, and `DamageKind.INVALID_VALUE` damage is recorded over the field's file offset.
5. **Mid-stream Corruption and Resync:** If an invalid record marker or length is encountered, `salvagekit.core.resync` scans for the next valid record boundary using marker and structure checks (`RDW == \x00\x30\x00\x00` and byte +4 == `\xc4`, or `RDW == \x00\x0e\x00\x00` and byte +4 == `\xe3`). Skipped bytes are reported as `DamageKind.UNPARSED_BYTES`.

## Open questions

1. **Text encoding (cp037 vs cp500):** The 7 byte values that differ between cp037 and cp500 (0x4a, 0x4f, 0x5a, 0x5f, 0xb0, 0xba, 0xbb) do not appear in any text field across the three samples. Consequently, cp037 and cp500 decode the samples identically. cp037 was chosen as standard IBM US/Canada mainframe encoding, but whether an international variant (cp500) might be used on other files from the same generator remains inconclusive.
2. **Flags in BDW/RDW:** The 2-byte flags in the BDW and RDW (bytes 2-3) are always `00 00` in the provided samples. In IBM mainframe specifications, these can occasionally represent segment control codes (spanning records across blocks), but spanned records are not observed in these samples.
