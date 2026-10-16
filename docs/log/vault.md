# VAULT research log

All times are local time (IST, UTC+05:30).

### 2026-10-16 15:25 — Container magic bytes identification

**Hypothesis:** The first 4 bytes of the file are a fixed ASCII magic signature `VLT1` identifying the VAULT container version 1.

**Tried:** Inspected bytes 0x00–0x03 across all three assigned samples (`kit/samples/s08.dat`, `kit/samples/s09.dat`, `kit/samples/s10.dat`).

**Evidence:** In all three samples, bytes 0x00–0x03 are exactly `56 4C 54 31` (ASCII "VLT1"). Decimal offsets 0..3 (hex 0x00..0x03).

**Result:** CONFIRMED. The 4-byte signature `VLT1` uniquely identifies the VAULT archive format.

### 2026-10-16 15:27 — Header bytes 0x04–0x05 are format version?

**Hypothesis:** Bytes 0x04–0x05 (u16 little-endian) indicate the format sub-version or revision (e.g. revision 3).

**Tried:** Read bytes 0x04–0x05 as u16le across s08, s09, and s10, and compared with reference metadata in `kit/expected_outputs/s08.dat.json`.

**Evidence:** The value is 0x0003 (3) in all three samples. However, `kit/expected_outputs/s08.dat.json` specifies `"metadata": {"entry_count": 3}`, and each sample contains exactly 3 records. If bytes 0x04–0x05 were a format revision, the archive entry count would have no representation in the header.

**Result:** REJECTED. Bytes 0x04–0x05 represent `entry_count` (u16le, value 3 in all samples), not a format revision.

### 2026-10-16 15:30 — Header bytes 0x06–0x07 represent XOR key and flags

**Hypothesis:** Byte 0x06 is the base `xor_key` (u8) and byte 0x07 is a container-level `flags` bitfield (u8).

**Tried:** Compared byte 0x06 and byte 0x07 across samples with `kit/expected_outputs/s08.dat.json` metadata fields `xor_key` and `flags`.

**Evidence:** In `s08.dat`, byte 0x06 is 0x20 (decimal 32) and byte 0x07 is 0x00 (decimal 0), exactly matching `xor_key: 32` and `flags: 0` in `s08.dat.json`. In `s09.dat`, byte 0x06 is 0xFC (252) and byte 0x07 is 0x01 (1). In `s10.dat`, byte 0x06 is 0xF8 (248) and byte 0x07 is 0x00 (0).

**Result:** CONFIRMED. Offset 0x06 is `xor_key` (u8) and offset 0x07 is `flags` (u8).

### 2026-10-16 15:33 — Header bytes 0x08–0x0F are table offsets

**Hypothesis:** Bytes 0x08–0x0B (u32le) point to the index table start, and bytes 0x0C–0x0F (u32le) point to the string table start / payload data end.

**Tried:** Parsed both fields as u32le across all three samples and compared against total file sizes and payload layout.

**Evidence:**
- `s08.dat` (size 307): `u32(0x08)` = 259 (0x103), `u32(0x0C)` = 229 (0x0E5). File size minus 259 is exactly 48 bytes (3 entries × 16 bytes).
- `s09.dat` (size 230): `u32(0x08)` = 182 (0x0B6), `u32(0x0C)` = 151 (0x097). File size minus 182 is exactly 48 bytes (3 entries × 16 bytes).
- `s10.dat` (size 322): `u32(0x08)` = 274 (0x112), `u32(0x0C)` = 242 (0x0F2). File size minus 274 is exactly 48 bytes (3 entries × 16 bytes).
In all samples, payloads run from offset 16 (0x10) to `u32(0x0C)`, the filename string table runs from `u32(0x0C)` to `u32(0x08)`, and the index table runs from `u32(0x08)` to EOF.

**Result:** CONFIRMED. Offset 0x08 is `index_offset` (u32le) and offset 0x0C is `string_table_offset` (u32le).

### 2026-10-16 15:36 — Index table entry stride and record ID mapping

**Hypothesis:** The index table consists of fixed 16-byte record descriptors, with the first 2 bytes (u16le) storing the unique record ID.

**Tried:** Read consecutive 16-byte slices from `index_offset` across all three samples and correlated with `s08.dat.json`.

**Evidence:** In `s08.dat`, index entries start at decimal offset 259 (hex 0x103):
- Entry 0 (259..274): ID bytes `6E 77` = 30574 (matches `s08.dat.json` record 0 ID 30574).
- Entry 1 (275..290): ID bytes `71 77` = 30577 (matches `s08.dat.json` record 1 ID 30577).
- Entry 2 (291..306): ID bytes `74 77` = 30580 (matches `s08.dat.json` record 2 ID 30580).
In `s09.dat` (starts at 182 / 0x0B6): IDs are 37327 (`CF 91`), 37330 (`D2 91`), 37333 (`D5 91`).
In `s10.dat` (starts at 274 / 0x112): IDs are 6146 (`02 18`), 6149 (`05 18`), 6152 (`08 18`).
Stride is strictly 16 bytes across all 9 observed records.

**Result:** CONFIRMED. Index entries have a 16-byte fixed stride and start with `id` (u16le).

### 2026-10-16 15:38 — Index entry byte 2 indicates record type

**Hypothesis:** Byte 0x02 of each index entry is an enum specifying the record payload type: 1 = "text", 2 = "bitmap", 3 = "binary".

**Tried:** Checked byte 0x02 across all entries against known types from `s08.dat.json` and decoded file extensions.

**Evidence:**
- In `s08.dat`: Entry 0 has byte 0x01 ("report.txt", type text); Entry 1 has 0x01 ("notes.txt", type text); Entry 2 has 0x03 ("logo.bin", type binary). Matches reference output exactly.
- In `s09.dat`: Entry 0 has 0x03 ("edge.bin", binary); Entry 1 has 0x02 ("icon.bmp8", bitmap); Entry 2 has 0x01 ("unicode.txt", text).
- In `s10.dat`: Entry 0 has 0x01 ("report.txt", text); Entry 1 has 0x03 ("sensor.bin", binary); Entry 2 has 0x02 ("icon.bmp8", bitmap).

**Result:** CONFIRMED. Byte 0x02 is `type` (1 = text, 2 = bitmap, 3 = binary).

### 2026-10-16 15:40 — Filename strings are null-terminated C-strings?

**Hypothesis:** The string table stores filename strings as null-terminated (C-style) ASCII strings.

**Tried:** Examined strings starting at `string_table_offset + name_offset` in `s08.dat` for trailing `0x00` null bytes.

**Evidence:** In `s08.dat`, name offsets from index entries are 0, 11, and 21. If strings were null-terminated, lengths of "report.txt" (10), "notes.txt" (9), and "logo.bin" (8) would take 11, 10, and 9 bytes with null terminators. However, the first byte at each offset is the exact character count (`0x0A` = 10, `0x09` = 9, `0x08` = 8), immediately followed by the string characters without a trailing null byte.

**Result:** REJECTED. Strings are Pascal-style (1-byte length prefix followed by character bytes), not null-terminated C-strings.

### 2026-10-16 15:42 — Filename strings use a rolling XOR key

**Hypothesis:** Filename characters are obfuscated with a rolling XOR key starting at `header.xor_key` where character `i` is XORed with `(xor_key + i) & 0xFF`.

**Tried:** Decoded Pascal string characters using `(xor_key + i) & 0xFF` for `i` in `0..length-1`.

**Evidence:**
- In `s08.dat` (xor_key = 32): strings decode cleanly to "report.txt", "notes.txt", and "logo.bin".
- In `s10.dat` (xor_key = 248): strings decode cleanly to "report.txt", "sensor.bin", and "icon.bmp8".
- In `s09.dat` (xor_key = 252, flags = 1): header flag bit 0 indicates that the Pascal length byte itself is also obfuscated with `xor_key` (`0xF4 ^ 252 = 8`, `0xF5 ^ 252 = 9`, `0xF7 ^ 252 = 11`). The characters then decode cleanly to "edge.bin", "icon.bmp8", and "unicode.txt".

**Result:** CONFIRMED. Filename characters are obfuscated using a rolling XOR key starting at `xor_key`.

### 2026-10-16 15:45 — Payload chunk framing and CRC-32 trailer

**Hypothesis:** Each payload chunk in the payload region has a 4-byte header (`42 4C` + u16le ID), followed by stored data, followed by a 4-byte trailer storing the little-endian CRC-32 of the decoded payload.

**Tried:** Inspected chunk at `data_offset` with length `stored_sz`, read 4-byte trailer at `data_offset + stored_sz`, and computed `zlib.crc32` over decoded payloads.

**Evidence:**
- Every chunk begins with magic `42 4C` ("BL") and a 2-byte little-endian ID matching the index entry.
- Stored size `stored_sz` in the index table equals `4 + len(stored_payload_data)`.
- The 4 bytes following the stored chunk (`data_offset + stored_sz`) store a u32le checksum.
- In `s08.dat`: Rec 0 CRC `0x1D8949DA`, Rec 1 CRC `0x0AC1B211`, Rec 2 CRC `0x8A303553` all match `zlib.crc32(decoded_payload)` exactly.
- In `s09.dat`: Rec 0 CRC `0xD5EAD680`, Rec 1 CRC `0x6EFB0868`, Rec 2 CRC `0x3E998E58` all match `zlib.crc32(decoded_payload)` exactly.
- In `s10.dat`: Rec 0 CRC `0xF3606645` and Rec 2 CRC `0xB507A8D4` match `zlib.crc32(decoded_payload)` exactly.

**Result:** CONFIRMED. Payload chunks are framed with `BL` + ID header, and terminated by a u32le CRC-32 of the decoded payload.

### 2026-10-16 15:48 — Index entry byte 3 flags control compression and XOR

**Hypothesis:** Byte 0x03 of each index entry is a bitfield where bit 0 (0x01) indicates compression and bit 1 (0x02) indicates XOR obfuscation of the payload data.

**Tried:** Correlated bit 0 and bit 1 across all records with `compressed` status in `s08.dat.json` and payload byte properties.

**Evidence:**
- In `s08.dat`: Rec 0 has flags = 0x03 (`comp=True`, `xor=True`), Rec 1 has flags = 0x02 (`comp=False`, `xor=True`), Rec 2 has flags = 0x00 (`comp=False`, `xor=False`). Matches `s08.dat.json` (`compressed: true` only on Rec 0).
- When bit 1 is set, the payload data is XOR-obfuscated with a rolling key starting at `header.xor_key`. De-XORing `notes.txt` (Rec 1) with rolling key from 32 yields "Remember: buy chalk." directly.
- When bit 0 is set, the payload is run-length compressed.

**Result:** CONFIRMED. Index entry byte 0x03 bits are: bit 0 = `compressed`, bit 1 = `xor_obfuscated`.

### 2026-10-16 15:50 — Compression algorithm is ARC-style Run-Length Encoding (RLE)

**Hypothesis:** Compressed payloads (bit 0 of flags set) use classic ARC-style RLE with escape byte `0x90`.

**Tried:** Decompressed payloads using ARC RLE: byte `0x90` followed by `0x00` emits literal `0x90`; byte `0x90` followed by repeat count `c > 0` repeats the preceding byte `c - 1` times.

**Evidence:**
- `s09.dat` Rec 0 ("edge.bin"): 27 stored data bytes decompress to 822 bytes. Decoded CRC `0xD5EAD680` matches trailer CRC `0xD5EAD680` exactly.
- `s09.dat` Rec 1 ("icon.bmp8"): 53 stored data bytes decompress to 130 bytes. Decoded CRC `0x6EFB0868` matches trailer CRC `0x6EFB0868` exactly.
- `s10.dat` Rec 2 ("icon.bmp8"): 31 stored data bytes decompress to 66 bytes. Decoded CRC `0xB507A8D4` matches trailer CRC `0xB507A8D4` exactly.

**Result:** CONFIRMED. The compression scheme is byte-oriented ARC RLE with escape byte `0x90`.

### 2026-10-16 15:52 — Bitmap width and height representation

**Hypothesis:** For `type: bitmap` records (type 2), the first 2 bytes of the decoded payload are width (u8) and height (u8), followed by `width * height` pixel bytes.

**Tried:** Inspected decoded payloads of `icon.bmp8` in `s09.dat` and `s10.dat`.

**Evidence:**
- In `s09.dat` Rec 1 (`icon.bmp8`), decoded length is 130 bytes: byte 0 is 16 (width), byte 1 is 8 (height). `2 + 16 × 8 = 130`.
- In `s10.dat` Rec 2 (`icon.bmp8`), decoded length is 66 bytes: byte 0 is 8 (width), byte 1 is 8 (height). `2 + 8 × 8 = 66`.
Pixel dimensions match file dimensions perfectly.

**Result:** CONFIRMED. Bitmap payloads begin with 1-byte width and 1-byte height.


### 2026-10-16 15:55 — s10 Record 1 checksum failure is an unknown compression algorithm?

**Hypothesis:** `s10.dat` Record 1 (`sensor.bin`) fails CRC verification because it uses an unidentified compression or encoding scheme.

**Tried:** Evaluated flags, stored size, and candidate XOR/RLE variations on `s10.dat` Record 1. Tested brute-force search with `find_checksum` across common algorithms.

**Evidence:** Record 1 index entry has `flags = 0x00` (uncompressed, plain raw binary), `stored_sz = 28` (4 header + 24 data), `decoded_sz = 24`. Stored CRC-32 is `0xF55026E8`, but calculated CRC-32 of the 24 payload bytes is `0x5CA76CA9`. The payload is raw binary bytes with no valid checksum match under any transformation.

**Result:** REJECTED. The format parser correctly interprets the record as uncompressed raw binary; the failure is intentional archive damage (`crc_mismatch`), which must be flagged as `"verified": false` and `issues: ["crc_mismatch"]`.

### 2026-10-16 16:00 — Filename rolling XOR key resets per string

**Hypothesis:** The rolling XOR transformation key does not accumulate across consecutive strings in the string table, but strictly resets to `header.xor_key` at the first character byte of every string descriptor.

**Tried:** Tested two decoding models on `s08.dat` (xor_key = 32), `s09.dat` (xor_key = 252), and `s10.dat` (xor_key = 248):
1. Reset model: byte `j` of each string uses key `(xor_key + j) & 0xFF` with `j = 0..name_len - 1`.
2. Continuous stream model: key accumulates across strings without resetting.

**Evidence:** In `s08.dat`, String 0 is "report.txt" (len 10). Under the reset model, String 1 at offset 11 decodes cleanly to "notes.txt" and String 2 at offset 21 decodes cleanly to "logo.bin". Under the continuous stream model (key starting at 32 + 10 = 42 for String 1), String 1 decodes to corrupted binary `dezky$bnn`. Across all 9 strings in `s08.dat`, `s09.dat`, and `s10.dat`, the reset model produces 100% valid ASCII filenames without replacement characters.

**Result:** CONFIRMED. Filename rolling XOR strictly resets to `(xor_key + j) & 0xFF` for each string entry (`j = 0..name_len - 1`).

### 2026-10-16 16:05 — Header flag bit 0 obfuscates Pascal length prefix

**Hypothesis:** Header byte 0x07 (`flags`) bit 0 (0x01) governs whether Pascal string length prefix bytes in the string table are XORed with `header.xor_key`.

**Tried:** Compared string table length bytes across samples with `header.flags`:
- `s08.dat`: `flags = 0x00`, `xor_key = 32`.
- `s09.dat`: `flags = 0x01`, `xor_key = 252`.
- `s10.dat`: `flags = 0x00`, `xor_key = 248`.

**Evidence:**
- In `s08.dat` (flags = 0), raw length bytes at name offsets 0, 11, 21 are `0x0A` (10), `0x09` (9), `0x08` (8). If XORed with 32, lengths would be 42, 41, 40, which immediately overrun the 30-byte string table. Unmodified bytes match expected lengths for "report.txt", "notes.txt", "logo.bin".
- In `s09.dat` (flags = 1), raw length bytes at name offsets 0, 9, 19 are `0xF4`, `0xF5`, `0xF7`. If un-XORed, they specify lengths of 244, 245, 247, which wildly exceed the 31-byte string table. XORed with `xor_key = 252` (`0xFC`), they evaluate to `0xF4 ^ 0xFC = 8`, `0xF5 ^ 0xFC = 9`, `0xF7 ^ 0xFC = 11`. Sum of entries: `(1+8) + (1+9) + (1+11) = 31` bytes, perfectly spanning `182 - 151 = 31` bytes.
- In `s10.dat` (flags = 0), raw length bytes are `0x0A` (10), `0x0A` (10), `0x09` (9). Sum of entries: `(1+10) + (1+10) + (1+9) = 32` bytes, perfectly spanning `274 - 242 = 32` bytes.

**Result:** CONFIRMED. When `header.flags & 0x01 == 1`, `name_len = raw_byte ^ header.xor_key`. When `header.flags & 0x01 == 0`, `name_len = raw_byte`.

### 2026-10-16 16:10 — Payload XOR key starts at index 0 of stored payload bytes

**Hypothesis:** When payload XOR is enabled (`flags & 0x02`), the rolling XOR key begins with `header.xor_key` applied to the first stored payload byte (offset `data_offset + 4`), strictly excluding the 4-byte chunk header (`BL` marker and chunk ID) and 4-byte CRC trailer.

**Tried:** Tested 3 candidate start offsets on `s08.dat` Record 1 (`notes.txt`, `data_offset = 173`, `stored_sz = 24`, payload bytes at 177..197):
1. Reset at payload start (byte `j` of payload uses `(xor_key + j) & 0xFF` for `j = 0..19`).
2. Offset including chunk header (byte `j` uses `(xor_key + 4 + j) & 0xFF`).
3. Offset from file start (byte `j` uses `(xor_key + 177 + j) & 0xFF`).

**Evidence:**
- Model 1 (reset at payload start): Decodes to `Remember: buy chalk.` (20 bytes). Matches `s08.dat.json` record 1 text and CRC-32 `0x0AC1B211` exactly.
- Model 2 (header included): Decodes to corrupted bytes `Vaiaani~>$fqe<\x7fteho*`. CRC-32 fails.
- Model 3 (file offset): Decodes to arbitrary non-ASCII bytes `\xa3\x96\x9c...`. CRC-32 fails.

**Result:** CONFIRMED. Payload XOR is applied exclusively to the `stored_sz - 4` payload bytes from `data_offset + 4` to `data_offset + stored_sz`, with rolling key resetting to `header.xor_key` at index 0 of the payload.

### 2026-10-16 16:15 — Record XOR applicability matches index flag bit 1

**Hypothesis:** Bit 1 (0x02) of index entry byte 0x03 (`flags`) strictly controls whether payload XOR de-obfuscation must be performed.

**Tried:** Evaluated bit 1 across all 9 records in `s08.dat`, `s09.dat`, and `s10.dat`. Applied XOR de-obfuscation only when `flags & 0x02 != 0`.

**Evidence:**
The complete record-level XOR validation matrix:

#### Sample `kit/samples/s08.dat` (header: xor_key=32, flags=0)
| ID | Decoded Filename | Type | Flags | XOR Enabled | Stored Payload Range | Candidate XOR Rule | Validation Result | Unresolved Ambiguity |
|---|---|---|---|---|---|---|---|---|
| 30574 | `report.txt` | 1 (text) | 0x03 | Yes (bit 1) | [20, 169) (149 B) | `raw[j] ^ ((32+j) & 0xFF)` | CONFIRMED (matches reference JSON & CRC 0x1D8949DA) | None |
| 30577 | `notes.txt` | 1 (text) | 0x02 | Yes (bit 1) | [177, 197) (20 B) | `raw[j] ^ ((32+j) & 0xFF)` | CONFIRMED (matches reference JSON & CRC 0x0AC1B211) | None |
| 30580 | `logo.bin` | 3 (binary) | 0x00 | No (bit 1=0) | [205, 225) (20 B) | No XOR (raw payload) | CONFIRMED (matches reference JSON & CRC 0x8A303553) | None |

#### Sample `kit/samples/s09.dat` (header: xor_key=252, flags=1)
| ID | Decoded Filename | Type | Flags | XOR Enabled | Stored Payload Range | Candidate XOR Rule | Validation Result | Unresolved Ambiguity |
|---|---|---|---|---|---|---|---|---|
| 37327 | `edge.bin` | 3 (binary) | 0x01 | No (bit 1=0) | [20, 47) (27 B) | No XOR (RLE compressed) | CONFIRMED (RLE produces 822 B, matches CRC 0xD5EAD680) | None |
| 37330 | `icon.bmp8` | 2 (bitmap) | 0x01 | No (bit 1=0) | [55, 108) (53 B) | No XOR (RLE compressed) | CONFIRMED (RLE produces 130 B, matches CRC 0x6EFB0868) | None |
| 37333 | `unicode.txt` | 1 (text) | 0x02 | Yes (bit 1) | [116, 147) (31 B) | `raw[j] ^ ((252+j) & 0xFF)` | CONFIRMED (UTF-8 "Müller – Zürich ✓ room 12", CRC 0x3E998E58) | None |

#### Sample `kit/samples/s10.dat` (header: xor_key=248, flags=0)
| ID | Decoded Filename | Type | Flags | XOR Enabled | Stored Payload Range | Candidate XOR Rule | Validation Result | Unresolved Ambiguity |
|---|---|---|---|---|---|---|---|---|
| 6146 | `report.txt` | 1 (text) | 0x03 | Yes (bit 1) | [20, 167) (147 B) | `raw[j] ^ ((248+j) & 0xFF)` | CONFIRMED (plain text, matches CRC 0xF3606645) | None |
| 6149 | `sensor.bin` | 3 (binary) | 0x00 | No (bit 1=0) | [175, 199) (24 B) | No XOR (raw binary) | CONFIRMED (raw bytes framing valid; CRC mismatch intentional damage) | None |
| 6152 | `icon.bmp8` | 2 (bitmap) | 0x01 | No (bit 1=0) | [207, 238) (31 B) | No XOR (RLE compressed) | CONFIRMED (RLE produces 66 B, matches CRC 0xB507A8D4) | None |

**Result:** CONFIRMED. Bit 1 of index entry `flags` strictly determines XOR obfuscation. When bit 1 is 0, stored bytes are not XORed; when bit 1 is 1, rolling XOR de-obfuscation with `(xor_key + j) & 0xFF` is required.

### 2026-10-16 16:20 — ARC RLE escape semantics and count interpretation

**Hypothesis:** In ARC-style RLE compression (escape byte `0x90`), an escape sequence `0x90 0x00` encodes a literal `0x90` without needing a preceding byte, whereas `0x90 <cnt>` with `cnt > 0` repeats the immediately preceding emitted byte `cnt - 1` additional times (total `cnt` copies in output).

**Tried:** Tested candidate decompressors across all compressed records in the corpus:
- Model A: `cnt - 1` additional copies (total output count = `cnt`).
- Model B: `cnt` additional copies (total output count = `cnt + 1`).
Evaluated on `s09.dat` Rec 0 (`edge.bin`, 27 stored bytes, declared `decoded_sz = 822`), `s09.dat` Rec 1 (`icon.bmp8`, 53 stored bytes, declared `decoded_sz = 130`), and `s10.dat` Rec 2 (`icon.bmp8`, 31 stored bytes, declared `decoded_sz = 66`).

**Evidence:**
- In `s09.dat` Rec 0 (`edge.bin`), byte 0 is `0x90 0x00`. No preceding byte exists. Under Model A and B, `0x90 0x00` emits literal `0x90`.
- For repeat sequences (e.g., `42 90 04`, `00 90 ff`, `43 90 ff`, `44 90 ff`, `44 90 2d`):
  - Model A (`cnt - 1` additional copies): produces exactly 822 bytes. CRC-32 is `0xD5EAD680`, exactly matching stored trailer `0xD5EAD680`.
  - Model B (`cnt` additional copies): produces 827 bytes (+5 bytes across 5 repeat sequences). CRC-32 is `0xF62F0AD8`, failing trailer verification.
- In `s09.dat` Rec 1 (`icon.bmp8`): Model A produces 130 bytes; CRC-32 `0x6EFB0868` matches trailer `0x6EFB0868` (100% match).
- In `s10.dat` Rec 2 (`icon.bmp8`): Model A produces 66 bytes; CRC-32 `0xB507A8D4` matches trailer `0xB507A8D4` (100% match).
- In `s08.dat` Rec 0 (`report.txt`) and `s10.dat` Rec 0 (`report.txt`), `compressed` bit 0 is set, but payload contains no `0x90` escapes; Model A emits the 149 and 147 bytes literally, matching decoded lengths and CRCs `0x1D8949DA` and `0xF3606645`.

**Result:** CONFIRMED. `0x90 0x00` emits literal `0x90`. For `cnt > 0`, `0x90 <cnt>` repeats the previous byte `cnt - 1` times (yielding `cnt` total copies of that byte).

### 2026-10-16 16:25 — ARC RLE long runs and uncompressed run boundaries

**Hypothesis:** Runs of repeated bytes longer than 255 bytes are chunked into multiple consecutive repeat descriptors, and short runs (<= 3 bytes) are stored uncompressed as literal bytes.

**Tried:** Analyzed literal and escape patterns in `kit/samples/s09.dat` Rec 0 (`edge.bin`).

**Evidence:**
- Short run: Bytes at offset 2..4 are literal `41 41 41` (three 'A's). Stored as 3 literal bytes rather than `41 90 03` (which would also take 3 bytes). The encoder avoids escaping runs where no byte savings occur.
- Consecutive escapes: Bytes at offset 5..8 are `90 00 90 00`. Emits two consecutive literal `0x90` bytes (`b'\x90\x90'`).
- Long run chunking: Bytes at offset 18..24 encode 300 consecutive copies of `0x44` ('D'):
  - `44 90 ff`: emits initial 'D' plus `255 - 1 = 254` copies = 255 bytes of 'D'.
  - `44 90 2d`: emits initial 'D' plus `45 - 1 = 44` copies = 45 bytes of 'D'.
  - Combined run: `255 + 45 = 300` bytes of 'D'.

**Result:** CONFIRMED. Runs longer than 255 bytes are encoded by repeating the literal byte followed by `90 ff` and subsequent partial run descriptors.

### 2026-10-16 16:30 — Decompression safeguards and error boundaries

**Hypothesis:** ARC RLE decoding requires defensive boundary checks against truncated escapes, invalid zero-history repeats, and decompression bombs to prevent crashes.

**Tried:** Synthesized edge cases against the decompressor logic:
1. Stream ends with lone `0x90` byte.
2. Stream starts with `0x90 <cnt>` where `cnt > 0` before any literal byte is emitted.
3. Stream contains malicious count attempting to expand beyond `decoded_sz` or `MAX_DECOMPRESSED`.

**Evidence:**
- Case 1: Reading `count` on a trailing `0x90` causes `IndexError` unless checked. Safe handling must break / report `DamageKind.BAD_LENGTH` or `DamageKind.TRUNCATED`.
- Case 2: Attempting `out[-1]` when `len(out) == 0` causes `IndexError`. Must be treated as malformed RLE (`DamageKind.BAD_LENGTH` / `DamageKind.INVALID_VALUE`).
- Case 3: An unconstrained loop extending `[prev] * (cnt - 1)` could allocate gigabytes if chained. Bounding expansion against `min(decoded_sz, MAX_DECOMPRESSED)` prevents memory exhaustion.

**Result:** CONFIRMED. Production decoder implementation must enforce: buffer bounds checking on escape reads, non-empty history validation for positive counts, and strict output length clamping.
