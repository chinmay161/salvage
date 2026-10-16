# EBCDIC-DUMP research log

### 2026-10-16 15:30 — Text encoding is EBCDIC (cp037 vs cp500 vs cp1047)

**Hypothesis:** Text fields in s20.000, s21.000, and s22.000 can be distinguished between EBCDIC cp037, cp500, and cp1047.

**Tried:** Tested decoding student names, titles, and status fields across all three samples using cp037, cp500, and cp1047. Mapped all 256 code points between cp037 and cp500 in Python to identify differing characters: 0x4a (¢ vs [), 0x4f (| vs !), 0x5a (! vs ]), 0x5f (¬ vs ^), 0xb0 (^ vs ¢), 0xba ([ vs §), and 0xbb (] vs |). Tested byte 0x7d (apostrophe in O'NEIL) and 0x6b (comma).

**Evidence:** cp1047 is not included in Python's standard library codecs (`unknown encoding: cp1047`). Across all three samples, the text bytes that actually appear are: 0x40 (space), 0x6b (comma), 0x7d (apostrophe), 0xc1..0xc9 ('A'..'I'), 0xd1..0xd9 ('J'..'R'), 0xe2..0xe9 ('S'..'Z'), and 0xf0..0xf9 ('0'..'9'). None of the 7 differing byte values (0x4a, 0x4f, 0x5a, 0x5f, 0xb0, 0xba, 0xbb) appear in any text field across the three samples. Both cp037 and cp500 decode every text field across s20.000, s21.000, and s22.000 identically.

**Result:** INCONCLUSIVE (cp037 chosen; cp500 decodes the samples identically).

### 2026-10-16 15:31 — Records are fixed-length card images (80 or 100 bytes)

**Hypothesis:** The mainframe tape records are fixed-length card images, such as 80-byte or 100-byte records.

**Tried:** Checked file lengths of s20.000 (287 bytes), s21.000 (303 bytes), and s22.000 (210 bytes) for divisibility by 80, 100, or any common card image size.

**Evidence:** None of 287, 303, or 210 is divisible by 80 or 100. Inspecting the first few bytes reveals 4-byte binary prefixes (`00 21 00 00`, `00 55 00 00`), not fixed card images.

**Result:** REJECTED. The format uses variable-length records with record descriptor words (RDW), not fixed card images.

### 2026-10-16 15:32 — Variable-length records delimited by 4-byte RDWs

**Hypothesis:** Each record starts with an IBM mainframe Record Descriptor Word (RDW): 2-byte big-endian length including the 4-byte RDW, followed by 2 bytes `00 00`.

**Tried:** Read the 4-byte prefix at offset 0x0000 in s20.000 (`00 21 00 00`), giving length 33 (0x21). Stepped to offset 33 and read the next 4-byte prefix (`00 30 00 00`, length 48). Continued stepping by indicated lengths across s20.000: offsets 0 (len 33), 33 (len 48), 81 (len 48), 129 (len 48), 177 (len 48), 225 (len 48), 273 (len 14).

**Evidence:** Sum of lengths is 33 + 5*48 + 14 = 287, exactly matching the file size of s20.000 (287 bytes). Every record descriptor has flags `00 00`.

**Result:** CONFIRMED. Records are variable-length with 4-byte RDW (u16be length including RDW + `\x00\x00`).

### 2026-10-16 15:34 — Block Descriptor Words (BDW) in blocked files (RECFM=VB)

**Hypothesis:** Mainframe tape dumps can be blocked (RECFM=VB), where each block starts with a 4-byte Block Descriptor Word (BDW: 2-byte big-endian block length including BDW + `00 00`), containing multiple RDW-prefixed records.

**Tried:** Compared s20.000 (starts with `00 21 00 00` -> RDW of length 33) and s21.000 (starts with `00 55 00 00`). Analyzed s21.000 at offset 0x0000: block length is 85. Inside this block, offset 4 has RDW `00 21 00 00` (len 33), and offset 37 has RDW `00 30 00 00` (len 48); 4 + 33 + 48 = 85. Next block at offset 85 has BDW `00 64 00 00` (len 100), containing two 48-byte records (4 + 48 + 48 = 100). Next block at offset 185 has BDW `00 64 00 00` (len 100). Final block at offset 285 has BDW `00 12 00 00` (len 18), containing 4-byte BDW + 14-byte trailer record (4 + 14 = 18).

**Evidence:** 85 + 100 + 100 + 18 = 303 bytes, exactly matching the file size of s21.000. All BDWs and RDWs have `00 00` in bytes 2-3.

**Result:** CONFIRMED. s21.000 is blocked (RECFM=VB) with BDWs, while s20.000 is unblocked (RECFM=V).

### 2026-10-16 15:35 — Credits field is COMP-3 packed decimal vs u16 big-endian binary

**Hypothesis:** The 2-byte credits field at payload offset +35 in student detail records is encoded as COMP-3 packed decimal (3 digits + sign).

**Tried:** Tested parsing the 2-byte sequence across records in s20.000 (record 1: `00 28`, record 2: `00 4a`, record 3: `00 52`, record 4: `00 54`, record 5: `00 7a`) as COMP-3 packed decimal versus unsigned 16-bit big-endian binary integer.

**Evidence:** As packed decimal, `00 28` ends in low nibble 8 which is not a valid sign nibble (valid signs are 0x0C, 0x0D, 0x0F, etc.), and `00 4a` contains high nibble 0x0A which is not a valid decimal digit (0..9). Read as u16 big-endian integers, the bytes yield exactly: 0x0028 = 40, 0x004a = 74, 0x0052 = 82, 0x0054 = 84, and 0x007a = 122. These match kit/expected_outputs/s20.000.json exactly, and their sum (40 + 74 + 82 + 84 + 122 = 402) equals `trailer_credits_total` (402). Similarly, in s21.000, u16be values (154, 71, 115, 106, 100) sum to 546, matching trailer credits 546.

**Result:** REJECTED for packed decimal; CONFIRMED for u16 big-endian binary.

### 2026-10-16 15:36 — Header record structure (type 'H')

**Hypothesis:** The first record is a header record with type byte 'H' (0xc8 in EBCDIC), followed by title and run_date.

**Tried:** Decoded the 29-byte payload of the 33-byte header record (RDW len 33 - 4 = 29) using cp037 in s20.000, s21.000, and s22.000.

**Evidence:**
- Byte 0: 0xc8 ('H')
- Bytes 1..21 (20 bytes): EBCDIC text, "STUDENT EXTRACT     " (stripped: "STUDENT EXTRACT")
- Bytes 21..29 (8 bytes): EBCDIC digits, "19990314" in s20.000 -> ISO date "1999-03-14"; "19990624" in s21.000 -> "1999-06-24"; "19990605" in s22.000 -> "1999-06-05".
Matches kit/expected_outputs/s20.000.json exactly: title="STUDENT EXTRACT", run_date="1999-03-14".

**Result:** CONFIRMED. Header payload is 1-byte type 'H', 20-byte title, 8-byte date string YYYYMMDD.

### 2026-10-16 15:37 — Trailer record structure (type 'T') and packed decimal fields

**Hypothesis:** The trailer record has type byte 'T' (0xe3 in EBCDIC) and contains trailer_count and trailer_credits_total in COMP-3 packed decimal format.

**Tried:** Read the 10-byte trailer payload (RDW len 14 - 4 = 10) in s20.000 (`e3 00 00 00 5f 00 00 00 40 2f`) and s21.000 (`e3 00 00 00 5f 00 00 00 54 6f`). Tested decoding bytes 1..5 (`00 00 00 5f`) and bytes 5..10 (`00 00 00 40 2f` / `00 00 00 54 6f`) as COMP-3 packed decimal (7 digits + sign nibble 'f', and 9 digits + sign nibble 'f').

**Evidence:**
- Byte 0: 0xe3 ('T')
- Bytes 1..5 (4 bytes): `00 00 00 5f` decodes as packed decimal 5 (matching 5 student records found in s20.000 and s21.000).
- Bytes 5..10 (5 bytes): `00 00 00 40 2f` in s20.000 decodes as 402, matching `trailer_credits_total` in s20.000.json. In s21.000, `00 00 00 54 6f` decodes as 546, exactly matching the sum of credits of the 5 student records in s21.000 (154 + 71 + 115 + 106 + 100 = 546).

**Result:** CONFIRMED. Trailer contains 1-byte type 'T', 4-byte packed decimal count, 5-byte packed decimal credits sum.

### 2026-10-16 15:38 — Detail record layout and field encodings (type 'D')

**Hypothesis:** Student detail records have a 44-byte payload (48-byte RDW), starting with type byte 'D' (0xc4), followed by student_id, name, dob, gpa, credits, status, balance, and padding.

**Tried:** Mapped the 44 payload bytes against record 1 of s20.000 and tested against all 5 records of s20.000 and s21.000:
- Byte 0: 0xc4 ('D')
- Bytes 1..7 (6 bytes): EBCDIC string student_id ("909014")
- Bytes 7..27 (20 bytes): EBCDIC string name ("KHAN, IMRAN")
- Bytes 27..32 (5 bytes): COMP-3 packed decimal date of birth `01 97 81 01 1f` -> 1978-10-11
- Bytes 32..35 (3 bytes): COMP-3 packed decimal GPA `00 26 3c` -> 263 / 100 = 2.63
- Bytes 35..37 (2 bytes): u16be binary integer credits `00 28` -> 40
- Bytes 37..38 (1 byte): EBCDIC string status `c7` -> "G"
- Bytes 38..42 (4 bytes): COMP-3 packed decimal balance `00 69 83 6c` -> 69836 / 100 = 698.36
- Bytes 42..44 (2 bytes): EBCDIC spaces `40 40` (padding)

**Evidence:** Every field in all 5 records of s20.000 matches kit/expected_outputs/s20.000.json exactly. In s21.000 and s22.000, all records decode with valid ISO dates, plausible GPAs (1.85 to 3.63), plausible credit counts (71 to 154), valid status codes ("G", "W", "A"), and negative balances with sign nibble 0x0D (e.g. `00 12 55 0d` = -125.50 in s21.000).

**Result:** CONFIRMED. Detail records are exactly 48 bytes (4-byte RDW + 44-byte payload).

### 2026-10-16 15:39 — s22.000 truncation mid-record

**Hypothesis:** s22.000 is an unblocked file (RECFM=V) truncated mid-record in the 4th student detail record.

**Tried:** Inspected s22.000 (total size 210 bytes). Header record occupies 0..33 (len 33). Detail records occupy 33..81 (len 48), 81..129 (len 48), 129..177 (len 48). At offset 177, RDW declares len 48 (`00 30 00 00`), requiring bytes up to offset 225. However, the file ends at offset 210 (33 bytes available).

**Evidence:** The 4th record contains student_id "210121", name "SHAH, DEV", and terminates after two bytes of dob (`01 98`). Records 1, 2, and 3 are completely undamaged.

**Result:** CONFIRMED. s22.000 is truncated at offset 177. Per contract, the 3 complete records are retained and TRUNCATED damage is reported over [177, 210).

### 2026-10-16 16:04 — Damaged-header identification via detail record chain

**Hypothesis:** A file whose header record is corrupted can still be recognized by probe() if followed by a chain of at least 2 valid detail records (RDW length 48, flags 00 00, type 'D', 6 EBCDIC digits for student_id).

**Tried:** Added candidate starting offset scanning (offsets 0, 33, 4, 37, and offset derived from RDW length) in probe() and tested on s20.000 with corrupted header type byte, as well as against all samples in kit/samples/.

**Evidence:** `corrupted_header_type.000` scores 0.75 in probe, and decode() skips the 33-byte bad header, sets title and run_date to null, and recovers all 5 detail records. All foreign samples in kit/samples/ (including s25-s30) score 0.0 because none contain valid detail records.

**Result:** CONFIRMED.
