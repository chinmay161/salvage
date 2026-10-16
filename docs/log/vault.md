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
