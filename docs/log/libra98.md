# LIBRA-98 research log

All times are local time (IST, UTC+05:30).

### 2026-10-16 13:43 — Magic bytes and header structure

**Hypothesis:** The file begins with a 4-byte ASCII magic and 16-byte fixed header.

**Tried:** Examined initial bytes of `kit/samples/s01.dat`–`s04.dat` and `s29_almost_libra.dat`.

**Evidence:** Bytes 0-3 are `4C 42 39 38` (`LB98`) in all five files. In s01-s04, offset 4 is version `0x02`, offset 6 is declared count, offset 12 is data offset (16 in s01/s02/s04, 40 in s03), and offset 14 is branch ID. `s29_almost_libra.dat` is only 7 bytes long and cut short mid-count.

**Result:** CONFIRMED

### 2026-10-16 13:44 — Created timestamp representation

**Hypothesis:** Bytes 8-11 represent created datetime as a 32-bit Unix epoch.

**Tried:** Parsed bytes 8-11 of `s01.dat` (`43 25 8b 5a`) as Unix timestamp.

**Evidence:** Produced year 2018, which conflicts with expected output `"1998-10-03T11:20:22"`. Tested DOS FAT date/time bit-packing: `0x2543` yields 1998-10-03 and `0x5A8B` yields 11:20:22. Verified identical packing in `s02`, `s03`, and `s04`.

**Result:** REJECTED for Unix epoch; CONFIRMED as DOS FAT datetime (u16le date, u16le time).

### 2026-10-16 13:47 — Record framing and length field

**Hypothesis:** Each record starts with marker `0xA5` followed by a u16 length field.

**Tried:** Checked bytes following marker `0xA5` across all records in `s01.dat`.

**Evidence:** In record 0, byte 1 was 43 and byte 2 was 0. In record 1 (checked out), byte 1 was 62 and byte 2 was 1. Byte 1 is an 8-bit payload length, and byte 2 is an 8-bit flag field where bit 0 is `checked_out`, bit 1 is `reference_only`, and bit 2 is `deleted`. Total record length is exactly `2 + payload_len`.

**Result:** CONFIRMED

### 2026-10-16 13:50 — Publication year representation

**Hypothesis:** Year is stored as a direct 16-bit integer.

**Tried:** Unpacked year field as u16le in `s01.dat`.

**Evidence:** Stored values were 397 (for 1897), 366 (for 1866), 425 (for 1925), 318 (for 1818), 422 (for 1922). Each value is offset from epoch 1500 (`year = stored + 1500`).

**Result:** CONFIRMED

### 2026-10-16 13:52 — Record checksum algorithm

**Hypothesis:** The final byte of each record is a CRC-8 or XOR-8 checksum.

**Tried:** Tested CRC-8 presets, XOR-8, and SUM-8 over candidate payload spans.

**Evidence:** `sum(payload[2:-1]) & 0xFF` exactly matches the final byte for all 22 complete records across `s01.dat`–`s04.dat`. Start offset must be 2 to include the flags byte.

**Result:** CONFIRMED as 8-bit byte sum mod 256.

### 2026-10-16 13:54 — File trailer structure and checksum

**Hypothesis:** The file ends with an ASCII `END!` marker and 16-bit CRC.

**Tried:** Located `END!` in clean samples `s01`, `s02`, `s03` and tested 16-bit checksums over the preceding file data.

**Evidence:** `b"END!"` is located at the end of records, followed by a 2-byte little-endian integer. `sum(file_data[:trailer_idx]) & 0xFFFF` matched the stored integer in all three clean files. In `s04.dat`, the trailer is absent due to truncation.

**Result:** CONFIRMED as `b"END!"` followed by u16le sum16 over all preceding bytes.
