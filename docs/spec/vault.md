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
| 0x07 | 1 | u8 | — | flags | Container flags: bit 0 (0x01) = name lengths XORed | log 2026-10-16 15:30, 16:05 |
| 0x08 | 4 | u32 | LE | index_offset | Absolute file offset to start of index table | log 2026-10-16 15:33 |
| 0x0C | 4 | u32 | LE | string_table_offset | Absolute file offset to start of string table | log 2026-10-16 15:33 |

### Payload Chunk Structure (0x10 to `string_table_offset`)

Payloads are stored consecutively from file offset 16 (0x10) to `string_table_offset`. Each chunk has the following layout:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 2 | bytes | — | marker | ASCII `BL` (`42 4C`) chunk marker | log 2026-10-16 15:45 |
| +0x02 | 2 | u16 | LE | chunk_id | Record ID matching index entry | log 2026-10-16 15:45 |
| +0x04 | stored_sz - 4 | bytes | — | payload_data | Stored payload (optionally XOR-obfuscated and/or RLE-compressed) | log 2026-10-16 15:45, 16:35 |
| +stored_sz | 4 | u32 | LE | crc32 | CRC-32 (IEEE 802.3) of decoded payload | log 2026-10-16 15:45, 16:40 |

Chunk sizing semantics:
- `stored_sz`: 4-byte chunk header (`BL` + ID) plus stored payload bytes (`stored_sz = 4 + len(payload_data)`). Excludes the CRC-32 trailer.
- Stored payload length: `len(payload_data) = stored_sz - 4`.
- Chunk on-disk span: `stored_sz + 4` bytes.
- Next chunk offset: `data_offset + stored_sz + 4`.
- The final chunk ends exactly at `string_table_offset`.

### Filename String Table (`string_table_offset` to `index_offset`)

The string table contains Pascal-style strings indexed by relative byte offset `name_offset`:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 1 | u8 | — | name_len | Character length (XORed with `xor_key` if `header.flags & 1`) | log 2026-10-16 15:40, 16:05 |
| +0x01 | name_len | bytes | — | name_chars | Character bytes, each XORed with `(xor_key + j) & 0xFF` | log 2026-10-16 15:42, 16:00 |

Filename string decoding algorithm:
1. `raw_len = data[string_table_offset + name_offset]`
2. `name_len = raw_len ^ header.xor_key` if `(header.flags & 0x01)` else `raw_len`
3. For character index `j` from `0` to `name_len - 1`:
   `char[j] = raw_chars[j] ^ ((header.xor_key + j) & 0xFF)`
4. The rolling key strictly resets to `header.xor_key` at the start of every string descriptor (`j = 0`).

### Index Table (`index_offset` to EOF)

An array of `entry_count` fixed 16-byte descriptors:

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| +0x00 | 2 | u16 | LE | id | Unique record identifier | log 2026-10-16 15:36 |
| +0x02 | 1 | u8 | — | type | Record type: 1 = text, 2 = bitmap, 3 = binary | log 2026-10-16 15:38 |
| +0x03 | 1 | u8 | — | flags | Record flags: bit 0 (0x01) = compressed, bit 1 (0x02) = XOR-obfuscated | log 2026-10-16 15:48, 16:15 |
| +0x04 | 4 | u32 | LE | name_offset | Offset relative to `string_table_offset` | log 2026-10-16 15:40 |
| +0x08 | 4 | u32 | LE | data_offset | Absolute file offset to payload chunk | log 2026-10-16 15:45 |
| +0x0C | 2 | u16 | LE | stored_sz | Stored chunk size (4-byte header + data, excluding CRC) | log 2026-10-16 15:45, 16:35 |
| +0x0E | 2 | u16 | LE | decoded_sz | Size of payload after decompression | log 2026-10-16 15:36, 16:40 |

## Records

Each index table entry maps to one contract record:
- `id`: Index entry `id` (integer).
- `name`: Decoded string from string table at `string_table_offset + name_offset` (string).
- `type`: Enum string derived from `type` byte:
  - `1` → `"text"`
  - `2` → `"bitmap"`
  - `3` → `"binary"`
- `size`: Index entry `decoded_sz` (integer).
- `sha256`: Hexadecimal SHA-256 hash of the fully decoded payload (64 lowercase hex characters).
- `compressed`: Boolean indicating whether compression flag is set (`bool(flags & 0x01)`).
- `text`: Conditional field present only when `type == "text"`. Decoded UTF-8 text string (fallback Latin-1).
- `width`: Conditional field present only when `type == "bitmap"`. First byte (u8) of decoded payload.
- `height`: Conditional field present only when `type == "bitmap"`. Second byte (u8) of decoded payload.

Container metadata maps directly to contract metadata:
- `entry_count`: `header.entry_count` (int)
- `xor_key`: `header.xor_key` (int)
- `flags`: `header.flags` (int)

## Decoding Pipeline

For each record, the payload decoding pipeline executes in strict sequential order:

```text
Stored Chunk Bytes in [data_offset + 4, data_offset + stored_sz)
       │
       ▼
[Step 1: XOR De-obfuscation] (if index flags & 0x02 != 0)
  p_xor[j] = stored[j] ^ ((header.xor_key + j) & 0xFF) for j in 0..stored_sz - 5
  (Key resets to header.xor_key at byte index 0 of stored payload)
       │
       ▼
[Step 2: ARC RLE Decompression] (if index flags & 0x01 != 0)
  Escape byte 0x90:
    0x90 0x00      --> emits literal 0x90
    0x90 <cnt>     --> emits preceding byte (cnt - 1) additional times
    other byte     --> emits byte literally
       │
       ▼
Decoded Payload (length must equal decoded_sz)
       │
       ├─────────────────────────────────────────┐
       ▼                                         ▼
[Step 3: CRC-32 Verification]           [Step 4: SHA-256 Computation]
  crc = zlib.crc32(decoded_payload)        sha = hashlib.sha256(decoded_payload)
  Compare against u32le trailer            Emitted in contract record
  at data_offset + stored_sz
```

Rationale for pipeline ordering: The archive encoder compresses raw data first using ARC RLE and obfuscates the compressed stream with rolling XOR last. During decoding, de-obfuscation must precede RLE decompression to restore the literal `0x90` escape markers.

## Checksums

- **Algorithm:** CRC-32 (standard IEEE 802.3 polynomial `0xEDB88320`, as computed by `zlib.crc32`).
- **Location:** Stored as a 4-byte little-endian unsigned integer immediately after each chunk's payload data at offset `data_offset + stored_sz`.
- **Coverage:** Covers the complete DECODED payload (after XOR de-obfuscation and RLE decompression). For bitmap records, the CRC-32 covers the entire `decoded_sz` bytes (including the 2-byte width and height header). Framing bytes (`BL` marker, record ID, and CRC trailer) are strictly excluded.
- **Verification:** 8 of 9 records across the sample suite match their stored CRC-32:
  - `s08.dat`: Rec 0 (0x1D8949DA), Rec 1 (0x0AC1B211), Rec 2 (0x8A303553) — 3/3 MATCH.
  - `s09.dat`: Rec 0 (0xD5EAD680), Rec 1 (0x6EFB0868), Rec 2 (0x3E998E58) — 3/3 MATCH.
  - `s10.dat`: Rec 0 (0xF3606645), Rec 2 (0xB507A8D4) — 2/3 MATCH.
  - `s10.dat` Rec 1 (`sensor.bin`) fails CRC verification (`0x5CA76CA9` vs stored `0xF55026E8`), representing intentional test damage.
- **SHA-256 Semantics:** The contract `sha256` value is computed over the fully decoded payload (100% verified against `kit/expected_outputs/s08.dat.json`). It does NOT cover raw stored bytes or partially decoded intermediate buffers.

## Compression and Obfuscation Rules

### 1. Obfuscation (Rolling XOR)
- Applies to string table entries unconditionally, and to payload data when index entry `flags & 0x02 != 0`.
- Filename characters: byte `j` (0-indexed) is XORed with `(xor_key + j) & 0xFF`.
- Filename length prefix: plain byte when `header.flags & 0x01 == 0`; XORed with `xor_key` when `header.flags & 0x01 == 1`.
- Payload data: byte `j` (0-indexed from `data_offset + 4`) is XORed with `(xor_key + j) & 0xFF`.
- The key sequence strictly resets to `header.xor_key` at the start of each payload and at the start of each string descriptor.

### 2. Compression (ARC RLE)
- Applies to payload data when index entry `flags & 0x01 != 0`.
- Byte-oriented Run-Length Encoding using escape byte `0x90`:
  - Byte `0x90` followed by `0x00`: emits literal byte `0x90`. Valid even when no preceding byte exists.
  - Byte `0x90` followed by count `cnt > 0`: repeats the immediately preceding emitted byte `cnt - 1` additional times (total `cnt` copies in output).
  - Any other byte: emitted literally.
- Run chunking: Runs exceeding 255 bytes are encoded by repeating the byte, followed by `90 ff` (255 total copies), followed by subsequent literal + repeat pairs.
- Uncompressed runs: Short runs (<= 3 bytes) are stored uncompressed as literal bytes without escape sequences.

## Decoder Safety Requirements

To prevent crashes, infinite loops, and memory exhaustion when decoding untrusted or corrupted archives, the decoder implementation must enforce:

1. **Truncated escape sequences:** If stored payload ends with a lone `0x90` escape byte with no subsequent byte, the decompressor must stop immediately and report `DamageKind.BAD_LENGTH`.
2. **Invalid zero-history repeats:** If an escape sequence `0x90 <cnt>` with `cnt > 0` occurs before any literal byte has been emitted, the decompressor must treat the sequence as malformed (`DamageKind.BAD_LENGTH` or `DamageKind.INVALID_VALUE`) rather than raising an `IndexError`.
3. **Decompression expansion limit:** The decompressor must track total emitted bytes and reject expansions exceeding `decoded_sz` or `MAX_DECOMPRESSED` (zip-bomb guard).
4. **Decoded size mismatch:** If the decompressed payload size does not match `index.decoded_sz`, the decoder must report `DamageKind.BAD_LENGTH` and mark the record unverified.
5. **Pointer and offset bounding:** All offsets (`data_offset`, `stored_sz`, `name_offset`, `index_offset`, `string_table_offset`) must be bounds-checked against `len(file_bytes)` before slicing.
6. **No uncaught exceptions:** `probe()` and `decode()` must never raise exceptions on truncated, malformed, or hostile inputs.

## Damage Handling

- **CRC mismatch:** When `crc32(decoded_payload) != stored_crc`, the record is emitted with `"verified": false` and `"issues": ["crc_mismatch"]`, accompanied by a `Damage` entry with kind `crc_mismatch` over `[data_offset + 4, data_offset + stored_sz)`. Observed in `s10.dat` Rec 1 (`sensor.bin`).
- **Out of bounds pointers:** If `data_offset`, `stored_sz`, or `name_offset` point past file boundaries, report `oob_pointer` damage.
- **Bad length:** If `stored_sz < 4`, or if RLE stream is malformed, or if decompressed payload length does not match `decoded_sz`, report `bad_length` damage.
- **Truncation:** If the file ends before declared index entries or payload bytes, report `truncated` damage from the truncation point to `file_size`.
- **Missing or corrupted index:** If `index_offset` is damaged, report `index_missing` and attempt resync by scanning payload regions for `BL` markers (`42 4C`) followed by valid record IDs.

## Open Questions and Unexercised Variants

- **Header flag bits:** Bit 0 (0x01) was confirmed active in `s09.dat` (signifying XOR-obfuscated Pascal length prefixes). Higher bits (0x02, 0x04, etc.) are unexercised in the available sample suite.
- **Text character encoding:** Text in `s08` and `s10` is plain ASCII, while `s09` contains UTF-8 sequences ("Müller – Zürich ✓ room 12"). Decoders should decode UTF-8 with Latin-1 fallback.
