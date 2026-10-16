# VAULT

## Summary

VAULT is a container archive format used by school-office applications to package notes, scans, and documents into a single file (context hint: "School-office archive utility; keeps notes and scans in one container file"). It supports multiple payload types (`text`, `bitmap`, `binary`), byte-oriented run-length compression (ARC RLE), rolling XOR string and payload obfuscation, and per-record CRC-32 payload verification.

Studied samples:
- `kit/samples/s08.dat` (307 bytes, 3 entries: `report.txt`, `notes.txt`, `logo.bin`)
- `kit/samples/s09.dat` (230 bytes, 3 entries: `edge.bin`, `icon.bmp8`, `unicode.txt`)
- `kit/samples/s10.dat` (322 bytes, 3 entries: `report.txt`, `sensor.bin`, `icon.bmp8`)

Reference output: `kit/expected_outputs/s08.dat.json`.

## Identification

The format begins with a 4-byte ASCII magic signature:
- Bytes 0x00–0x03: `56 4C 54 31` ("VLT1"). Exact match gives `probe()` score 0.9.

To achieve confidence 1.0, verify structural consistency:
- `entry_count = u16le(0x04) > 0`
- `index_offset = u32le(0x08)`
- `string_table_offset = u32le(0x0C)`
- `16 <= string_table_offset <= index_offset`
- `index_offset + entry_count * 16 == file_size`

File extension `.dat` is a tie-break hint only.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 4 | bytes | — | magic | ASCII signature `VLT1` | `56 4C 54 31` in all samples |
| 0x04 | 2 | u16 | LE | entry_count | Number of entries in archive (3 in all samples) | log 2026-10-16 15:27 |
| 0x06 | 1 | u8 | — | xor_key | Base XOR key for string & payload obfuscation | log 2026-10-16 15:30 |
| 0x07 | 1 | u8 | — | flags | Container flags: bit 0 (0x01) = name lengths XORed | log 2026-10-16 15:30 |
| 0x08 | 4 | u32 | LE | index_offset | Absolute file offset to start of index table | log 2026-10-16 15:33 |
| 0x0C | 4 | u32 | LE | string_table_offset | Absolute file offset to start of string table | log 2026-10-16 15:33 |

### Payload Chunk Structure (0x10 to `string_table_offset`)

Payloads are stored consecutively from offset 16 (0x10) to `string_table_offset`. Each chunk has the following layout:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 2 | bytes | — | marker | ASCII `BL` (`42 4C`) chunk marker | log 2026-10-16 15:45 |
| +0x02 | 2 | u16 | LE | chunk_id | Record ID matching index entry | log 2026-10-16 15:45 |
| +0x04 | stored_sz - 4 | bytes | — | payload_data | Stored payload (optionally XOR-obfuscated and/or RLE-compressed) | log 2026-10-16 15:45 |
| +stored_sz | 4 | u32 | LE | crc32 | CRC-32 (IEEE 802.3) of decoded payload | log 2026-10-16 15:45 |

Total span of one chunk in file is `stored_sz + 4` bytes.

### Filename String Table (`string_table_offset` to `index_offset`)

The string table contains Pascal-style strings indexed by relative byte offset:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 1 | u8 | — | name_len | Character length (XORed with xor_key if `header.flags & 1`) | log 2026-10-16 15:40 |
| +0x01 | name_len | bytes | — | name_chars | Character bytes, each XORed with `(xor_key + i) & 0xFF` | log 2026-10-16 15:42 |

### Index Table (`index_offset` to EOF)

An array of `entry_count` fixed 16-byte descriptors:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 2 | u16 | LE | id | Unique record identifier | log 2026-10-16 15:36 |
| +0x02 | 1 | u8 | — | type | Record type: 1 = text, 2 = bitmap, 3 = binary | log 2026-10-16 15:38 |
| +0x03 | 1 | u8 | — | flags | Record flags: bit 0 (0x01) = compressed, bit 1 (0x02) = XOR-obfuscated | log 2026-10-16 15:48 |
| +0x04 | 4 | u32 | LE | name_offset | Offset relative to `string_table_offset` | log 2026-10-16 15:40 |
| +0x08 | 4 | u32 | LE | data_offset | Absolute file offset to payload chunk | log 2026-10-16 15:45 |
| +0x0C | 2 | u16 | LE | stored_sz | Stored chunk size (4-byte header + data, excluding CRC) | log 2026-10-16 15:45 |
| +0x0E | 2 | u16 | LE | decoded_sz | Size of payload after decompression | log 2026-10-16 15:36 |

## Records

Each index table entry maps to one contract record:
- `id`: Index entry `id` (integer).
- `name`: Decoded string from string table at `string_table_offset + name_offset` (string).
- `type`: Enum string derived from `type` byte:
  - `1` → `"text"`
  - `2` → `"bitmap"`
  - `3` → `"binary"`
- `size`: Index entry `decoded_sz` (integer).
- `sha256`: Hexadecimal SHA-256 hash of the decoded payload (64 hex characters).
- `compressed`: Boolean indicating whether compression flag is set (`bool(flags & 0x01)`).
- `text`: Conditional field present only when `type == "text"`. Decoded UTF-8 / Latin-1 text.
- `width`: Conditional field present only when `type == "bitmap"`. First byte (u8) of decoded payload.
- `height`: Conditional field present only when `type == "bitmap"`. Second byte (u8) of decoded payload.

Container metadata maps directly to contract metadata:
- `entry_count`: `header.entry_count` (int)
- `xor_key`: `header.xor_key` (int)
- `flags`: `header.flags` (int)

## Checksums

- **Algorithm:** CRC-32 (standard IEEE 802.3 polynomial `0xEDB88320`, as computed by `zlib.crc32`).
- **Location:** Stored as a 4-byte little-endian unsigned integer immediately after each chunk's payload data at offset `data_offset + stored_sz`.
- **Coverage:** Covers the complete DECODED payload (after XOR de-obfuscation and RLE decompression). For bitmap records, the CRC-32 covers the entire `decoded_sz` bytes (including width and height header bytes).
- **Verification:** 8 of 9 records across the sample suite match their stored CRC-32:
  - `s08.dat`: Rec 0 (0x1D8949DA), Rec 1 (0x0AC1B211), Rec 2 (0x8A303553) — 3/3 MATCH.
  - `s09.dat`: Rec 0 (0xD5EAD680), Rec 1 (0x6EFB0868), Rec 2 (0x3E998E58) — 3/3 MATCH.
  - `s10.dat`: Rec 0 (0xF3606645), Rec 2 (0xB507A8D4) — 2/3 MATCH.
  - `s10.dat` Rec 1 (`sensor.bin`) fails CRC verification (`0x5CA76CA9` vs stored `0xF55026E8`), representing intentional test damage.

## Compression and obfuscation

1. **Obfuscation (XOR):**
   - Applies to strings in the string table and to payload data when index entry `flags & 0x02 != 0`.
   - String characters: byte `i` (0-indexed) is XORed with `(xor_key + i) & 0xFF`.
   - String length prefix: plain byte when `header.flags & 0x01 == 0`; XORed with `xor_key` when `header.flags & 0x01 == 1`.
   - Payload data: byte `i` (0-indexed) of stored payload bytes (excluding 4-byte `BL`+ID header) is XORed with `(xor_key + i) & 0xFF`.
2. **Compression (RLE):**
   - Applies to payload data when index entry `flags & 0x01 != 0`.
   - Compression is byte-oriented Run-Length Encoding using escape byte `0x90` (classic ARC RLE):
     - Byte `0x90` followed by `0x00`: emits literal byte `0x90`.
     - Byte `0x90` followed by count `c > 0`: repeats the immediately preceding emitted byte `c - 1` additional times (total `c` copies).
     - Any other byte: emitted literally.
   - De-obfuscation must be performed before RLE decompression when both flags are active (`flags == 0x03`).

## Damage handling

- **CRC mismatch:** When `crc32(decoded_payload) != stored_crc`, the record is emitted with `"verified": false` and `"issues": ["crc_mismatch"]`, accompanied by a `Damage` entry with kind `CRC_MISMATCH` over `[data_offset + 4, data_offset + stored_sz)`. Observed in `s10.dat` Rec 1 (`sensor.bin`).
- **Out of bounds pointers:** If `data_offset`, `stored_sz`, or `name_offset` point past file boundaries, report `OOB_POINTER` damage.
- **Bad length:** If `stored_sz < 4` or decompressed payload length does not match `decoded_sz` (or exceeds `MAX_DECOMPRESSED`), report `BAD_LENGTH`.
- **Truncation:** If the file ends before declared index entries or payload bytes, report `TRUNCATED` damage from the truncation point to `file_size`.
- **Missing or corrupted index:** If `index_offset` is damaged, report `INDEX_MISSING` and attempt resync by scanning payload regions for `BL` markers (`42 4C`) followed by valid record IDs.

## Open questions

- **Header flag bits:** Only bit 0 (0x01) was observed active in `s09.dat` (signifying XOR-obfuscated Pascal length prefixes). Higher bits (0x02, 0x04, etc.) are unexercised in the available sample suite.
- **Text character encoding:** Text in `s08` and `s10` is plain ASCII, while `s09` contains UTF-8 sequences. Whether other historical code pages (e.g. CP437 or ISO-8859-1) can appear is unconfirmed; decoders should decode UTF-8 with Latin-1 fallback.
