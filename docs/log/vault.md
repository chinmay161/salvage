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
