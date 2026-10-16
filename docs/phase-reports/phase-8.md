# Phase 8 report: EBCDIC-DUMP decoder (Core's format)

Branch `core/ebcdic_dump`: implementation of `salvagekit/formats/ebcdic_dump.py`, tests in `tests/ebcdic_dump/`, research log in `docs/log/ebcdic_dump.md`, and specification in `docs/spec/ebcdic_dump.md`. `salvagekit/core/` was not touched.

## 1. Final layout

The format supports both unblocked variable-length records (RECFM=V) and blocked variable-length records (RECFM=VB) from an IBM mainframe environment (OS/390 or MVS, 1999). Text is encoded in EBCDIC cp037, and numbers are packed decimal (COMP-3) or big-endian binary integers.

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

---

## 2. Hypotheses tried, confirmed and rejected

**Total hypotheses tested:** 10 (8 CONFIRMED, 1 REJECTED, 1 INCONCLUSIVE).

### The 3 hypotheses that mattered most:

1. **Mainframe variable-length records (RDW) vs fixed-length card images:**
   - *Hypothesis:* Records were initially suspected to possibly be 80-byte or 100-byte punched card images.
   - *Test & Result:* File sizes (287, 303, 210) were not multiples of 80 or 100 (REJECTED). Inspecting file offsets confirmed standard IBM 4-byte Record Descriptor Words (`u16be length` including RDW + `\x00\x00` flags) stepping through records of lengths 33 (header), 48 (detail), and 14 (trailer) in s20.000 (CONFIRMED).
2. **Blocked tape structure (RECFM=VB) in s21.000:**
   - *Hypothesis:* s21.000 begins with `00 55 00 00` rather than the header RDW `00 21 00 00`. Tested whether s21.000 is a blocked mainframe dataset (RECFM=VB) where 4-byte Block Descriptor Words (BDW) wrap multiple records.
   - *Test & Result:* Offset 0 has BDW length 85 containing 4-byte BDW + 33-byte header RDW + 48-byte detail RDW (4 + 33 + 48 = 85). Block 2 has length 100 (4 + 48 + 48 = 100). Block 3 has length 100 (4 + 48 + 48 = 100). Block 4 has length 18 (4 + 14 = 18). Sum of block lengths is 85 + 100 + 100 + 18 = 303 bytes, accounting for 100% of s21.000 with 0 unparsed bytes (CONFIRMED).
3. **COMP-3 packed decimal encodings and negative signs:**
   - *Hypothesis:* Numeric values (`dob`, `gpa`, `balance`, `trailer_count`, `trailer_credits_total`) are stored as BCD packed decimal numbers with sign nibbles.
   - *Test & Result:* Validated 5-byte `dob` (`01 97 81 01 1f` -> 1978-10-11), 3-byte `gpa` (`00 26 3c` -> 2.63), and 4-byte `balance` (`00 69 83 6c` -> 698.36) against `s20.000.json`. Crucially confirmed negative balance representation using sign nibble 0x0D (e.g. `00 12 55 0d` -> -125.50 in s21.000), and distinguished binary `credits` (2-byte u16be integer) from packed decimal numbers (CONFIRMED).

### Additional tested hypotheses:
4. **Text encoding (cp037 vs cp500 vs cp1047):** Tested cp037, cp500, and cp1047. cp1047 is not supported in the Python standard library. Across all 256 byte values, only 7 code points differ between cp037 and cp500 (0x4a, 0x4f, 0x5a, 0x5f, 0xb0, 0xba, 0xbb); none of these 7 bytes occur in any text field across the three samples. All actual text bytes (0x40, 0x6b, 0x7d, 0xc1..0xc9, 0xd1..0xd9, 0xe2..0xe9, 0xf0..0xf9) decode identically in both cp037 and cp500 (INCONCLUSIVE: cp037 chosen; cp500 decodes identically).
5. **Credits field as packed decimal vs u16be:** Parsing `credits` as packed decimal fails (e.g. `00 28` has invalid sign 8; `00 4a` has non-decimal nibble 0x0A). Parsing as u16 big-endian yields 40, 74, 82, 84, 122 summing to 402, matching `trailer_credits_total` (402) in s20 and 546 in s21 (REJECTED for packed decimal, CONFIRMED for u16be).
6. **Damaged-header recognition via detail record chain:** A file whose header is corrupted is recognized by probe (score 0.75) if followed by a chain of at least 2 valid detail records (RDW length 48, flags 00 00, type 'D', 6 EBCDIC digits) at offset 0, 33, 4, or 37. Foreign samples in kit/samples/ all score 0.0 (CONFIRMED).

---

## 3. Calibrate output for s20.000

```
s20.000  MATCH
calibrate: 1/1 files match
```

---

## 4. Decoded output of s21.000 and s22.000

### Sample `s21.000`
- **Status:** `ok`
- **Metadata:**
  - `title`: `"STUDENT EXTRACT"`
  - `run_date`: `"1999-06-24"`
  - `trailer_count`: `5`
  - `trailer_credits_total`: `546`
- **Record count:** 5 records

**First record in full:**
```json
{
  "student_id": "328015",
  "name": "SHAH, DEV",
  "dob": "1975-11-25",
  "gpa": 3.08,
  "credits": 154,
  "status": "G",
  "balance": 549.29
}
```

**Last record in full:**
```json
{
  "student_id": "108001",
  "name": "O'NEIL, KEVIN",
  "dob": "1981-05-01",
  "gpa": 2.62,
  "credits": 100,
  "status": "W",
  "balance": -12.07
}
```

### Sample `s22.000`
- **Status:** `partial`
- **Metadata:**
  - `title`: `"STUDENT EXTRACT"`
  - `run_date`: `"1999-06-05"`
  - `trailer_count`: `null`
  - `trailer_credits_total`: `null`
- **Record count:** 3 complete records (Record 4 truncated at byte 177)
- **Damage:**
  ```json
  [
    {
      "kind": "truncated",
      "offset": 177,
      "detail": "record of length 48 truncated by end of file",
      "lossy": true
    }
  ]
  ```

**First record in full:**
```json
{
  "student_id": "750841",
  "name": "IYER, KAVYA",
  "dob": "1983-09-14",
  "gpa": 2.3,
  "credits": 129,
  "status": "W",
  "balance": 764.8
}
```

**Last record in full:**
```json
{
  "student_id": "608029",
  "name": "ADAMS, PRIYA",
  "dob": "1983-11-15",
  "gpa": 3.04,
  "credits": 85,
  "status": "W",
  "balance": -270.12
}
```

### Why we trust these outputs without answer keys:
1. **Mathematical cross-checks:** In `s21.000`, the sum of credits across all five records is `154 + 71 + 115 + 106 + 100 = 546`, which precisely matches `trailer_credits_total` (546). The record count of 5 matches `trailer_count` (5).
2. **Structural framing:** The BDWs in `s21.000` partition the 303-byte file into four blocks (85 + 100 + 100 + 18 bytes) with zero unparsed bytes and zero coverage gaps.
3. **Semantic coherence:** All dates are valid calendar dates (1975 to 1986). All GPAs fall within the valid collegiate 0.00..4.00 range. Status codes ("G", "W", "A") align with standard academic terminology. Negative balances with sign 0x0D cleanly indicate credit balances.
4. **Clean truncation isolation:** In `s22.000`, the file length is 210 bytes. Three full records are preserved, and record 4 begins at offset 177 declaring length 48 (which would end at 225). It has 33 valid bytes present (student_id "210121", name "SHAH, DEV", and initial dob bytes `01 98`), ending exactly inside dob.

---

## 5. Damaged golden cases

| Case | Status | Damage list |
|------|--------|-------------|
| `truncated_mid_record.000` | `partial` | `[{"kind": "truncated", "offset": 81, "detail": "record of length 48 truncated by end of file", "lossy": true}]` |
| `corrupted_packed.000` | `partial` | `[{"kind": "invalid_value", "offset": 69, "detail": "record 0: invalid high nibble 0xf in byte 1", "lossy": true}]` |
| `trailer_count_off.000` | `partial` | `[{"kind": "count_mismatch", "offset": 278, "detail": "trailer count 6 != 5 records found", "lossy": true}]` |
| `corrupted_header_type.000` | `partial` | `[{"kind": "unparsed_bytes", "offset": 0, "detail": "invalid record header at 0; scanning for next record", "lossy": true}]` |

- In `corrupted_packed.000`, record 0's GPA field becomes `null`, and the record carries `"verified": false` and `"issues": ["invalid_value"]`.
- In `trailer_count_off.000`, all 5 records are decoded with valid values; the trailer count discrepancy is isolated as a file-level `COUNT_MISMATCH` damage.
- In `truncated_mid_record.000`, the single complete record prior to the truncation offset is preserved.
- In `corrupted_header_type.000`, the 33-byte corrupted header is skipped and reported as `UNPARSED_BYTES` damage, `title` and `run_date` are set to `null`, and all 5 detail records plus the trailer are decoded cleanly.

---

## 6. Conformance and test results

- `python tools/task.py conform ebcdic_dump`:
  ```
  PASS  EBCDIC-DUMP  10 inputs, 430 variants, 0 warnings
  conform (full mode): 1 PASS, 0 FAIL in 1.1 s
  ```
  (All checks C1 through C12 pass cleanly without warnings across 10 inputs and 430 variants).
- `python tools/task.py golden ebcdic_dump`: PASS (all 7 golden cases match expectations).
- `python tools/task.py test`: Ran 339 tests in 35.1s: OK (skipped=26). `s20.000`, `s21.000`, and `s22.000` are active in `SampleRunTests` and pass validation.

---

## 7. Open questions & uncertainties

1. **Text encoding (cp037 vs cp500):** The 7 byte values that differ between cp037 and cp500 (0x4a, 0x4f, 0x5a, 0x5f, 0xb0, 0xba, 0xbb) do not appear in any text field across the three samples. Consequently, cp037 and cp500 decode the samples identically. cp037 was chosen as standard IBM US/Canada mainframe encoding, but whether an international variant (cp500) might be used on other files from the same generator remains inconclusive.
2. **BDW and RDW flags:** In all samples, bytes 2-3 of the BDW and RDW are `\x00\x00`. In IBM mainframe MVS/OS/390 specifications, these can occasionally indicate spanned record segment codes (e.g. first segment, middle segment, last segment). Spanned records were not observed in the samples; the decoder assumes complete records within blocks.
3. **Status codes:** Observed statuses include 'G' (Graduated), 'W' (Withdrawn), and 'A' (Active). The decoder validates `status` as an alphabetic character rather than restricting to a hardcoded set, ensuring compatibility with other standard academic codes (e.g. 'E' for Enrolled, 'F' for Freshman).
4. **Choice of `COUNT_MISMATCH` for trailer credits total:** Between `count_mismatch` and `invalid_value`, we selected `count_mismatch` because `trailer_credits_total` is an aggregate tally of credits, directly corresponding to the contract definition of a declared count/total disagreeing with decoded records.
