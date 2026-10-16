# LABLOG research log

All times are local time (IST, UTC+05:30).

### 2026-10-16 15:42 — Magic bytes, header structure, and instrument identification

**Hypothesis:** LABLOG files begin with a 4-byte ASCII magic and a 32-byte fixed header.

**Tried:** Examined initial bytes of `kit/samples/s05.dat`, `s06.dat`, and `s07.dat`.

**Evidence:** Bytes 0-3 are `4C 4C 4F 47` (`LLOG`) in all three files. Byte 4 is version `0x01`. Byte 5 is channel count (2 in s05, 3 in s06/s07). Bytes 6-7 are sample interval in centiseconds. Bytes 8-23 are a 16-byte null-padded ASCII instrument string (`THERMO LOGGER` in s05, `FLOWCELL-2` in s06/s07). Bytes 24-27 are start timestamp. Bytes 28-29 are declared block count (7 in s05, 8 in s06/s07). Bytes 30-31 are header checksum. Total header size is exactly 32 bytes (0x00–0x1F).

**Result:** CONFIRMED

### 2026-10-16 15:43 — Start timestamp epoch representation

**Hypothesis:** Bytes 24-27 represent start datetime as standard 32-bit Unix epoch (seconds since 1970).

**Tried:** Unpacked bytes 24-27 of `s05.dat` (`1f 19 39 05`) as u32le and converted from 1970 Unix epoch.

**Evidence:** 1970 epoch gave datetime 1972-10-11, whereas official expected output `s05.dat.json` states `"1992-10-11T05:07:43Z"`. Testing offset epoch 1990-01-01 00:00:00 UTC ($631,152,000$ Unix timestamp) plus stored value $87,628,063$ yields exactly $718,780,063$, which converts to `1992-10-11T05:07:43Z`. Applied to `s06.dat` this yields `1993-09-01T20:06:50Z` and to `s07.dat` yields `1994-04-02T21:02:06Z`.

**Result:** REJECTED for 1970 Unix epoch; CONFIRMED as seconds since 1990-01-01 00:00:00 UTC (u32le).

### 2026-10-16 15:44 — Sample interval unit

**Hypothesis:** Bytes 6-7 store the sample interval directly in milliseconds.

**Tried:** Unpacked bytes 6-7 as u16le across s05, s06, and s07.

**Evidence:** In `s05.dat`, stored value is 50 (`0x0032`), but `s05.dat.json` specifies `"sample_interval_ms": 500`. Stored value is in centiseconds ($10\text{ ms}$ units): $50 \times 10 = 500\text{ ms}$. In `s06.dat`, stored value is 100 ($1000\text{ ms} = 1.0\text{ s}$). In `s07.dat`, stored value is 25 ($250\text{ ms} = 0.25\text{ s}$).

**Result:** REJECTED for direct milliseconds; CONFIRMED as centiseconds (multiply by 10 to obtain milliseconds).

### 2026-10-16 15:44 — Header checksum algorithm

**Hypothesis:** Bytes 30-31 store a 16-bit CRC or sum over the header.

**Tried:** Tested sum16, CRC-16-IBM, and CRC-16-CCITT across bytes 0-29 of s05, s06, and s07.

**Evidence:** CRC-16-CCITT (polynomial `0x1021`, initial value `0xFFFF`, little-endian) over bytes 0x00–0x1D (30 bytes) matches the stored u16le at 0x1E–0x1F in all three samples: `0xef52` in s05, `0x0268` in s06, and `0x193a` in s07.

**Result:** CONFIRMED as CRC-16-CCITT (poly 0x1021, init 0xFFFF) over bytes 0..29.

### 2026-10-16 15:45 — Block framing and block types

**Hypothesis:** Blocks follow the header back to back, prefixed with sync marker `0xB1`.

**Tried:** Parsed file streams looking for sync marker `0xB1` and length fields.

**Evidence:** Every block begins with sync byte `0xB1`, followed by 1-byte block type, 2-byte u16le payload length $L$, $L$ payload bytes, and a 2-byte u16le trailer CRC. Total block length is $4 + L + 2$ bytes. In `s05.dat`, 7 blocks exactly span offsets 0x0020 to 0x00E5 (229 bytes, EOF). In `s06.dat`, 8 blocks span 0x0020 to 0x0139 (313 bytes, EOF). In `s07.dat`, 8 blocks span 0x0020 to 0x014E (334 bytes, EOF). Three block types were observed: Type 3 (channel configuration), Type 1 (data records), and Type 2 (events).

**Result:** CONFIRMED

### 2026-10-16 15:45 — Block trailer checksum algorithm and coverage

**Hypothesis:** The 2-byte block trailer is a CRC-16-CCITT over the block payload only.

**Tried:** Tested CRC-16-CCITT over payload only vs full block vs block without sync marker.

**Evidence:** CRC-16-CCITT (poly `0x1021`, init `0xFFFF`) over `type + length + payload` (excluding marker `0xB1`) matched the stored 2-byte trailer across all 7 blocks in `s05.dat`, all 8 blocks in `s06.dat`, and 7 of 8 blocks in `s07.dat`. Calculating over payload only failed to match.

**Result:** CONFIRMED as CRC-16-CCITT over `block[1 : 4 + payload_len]`.

### 2026-10-16 15:46 — Channel configuration block (Type 3)

**Hypothesis:** Type 3 blocks describe sensor channels with calibration parameters.

**Tried:** Unpacked payload of Block 1 in s05, s06, and s07 as arrays of 12-byte structs.

**Evidence:** Block 1 payload length is $12 \times \text{num\_channels}$ (24 bytes in s05, 36 bytes in s06/s07). Each 12-byte entry consists of: 4-byte ASCII null-padded unit string (e.g. `mV`, `ppm`, `pH`, `kPa`, `degC`), 4-byte float32le scale factor, and 4-byte float32le offset. In `s05.dat`: ch0 has unit `mV`, scale 0.5, offset 100.0; ch1 has unit `ppm`, scale 0.5, offset 20.5.

**Result:** CONFIRMED

### 2026-10-16 15:46 — Linear calibration formula and data record decoding (Type 1)

**Hypothesis:** Type 1 blocks contain raw ADC integer measurements that map linearly to calibrated floats.

**Tried:** Unpacked Type 1 payloads across all samples and applied calibration formula $\text{calibrated} = \text{raw} \times \text{scale} + \text{offset}$.

**Evidence:** Type 1 payload begins with 2-byte u16le starting sample index and 1-byte u8 sample count $N$. Then $N$ sample records follow, each containing $\text{num\_channels} \times 2$ bytes of int16le raw values. In `s05.dat`, applying the formula to all 22 samples produced floating-point values identical to `kit/expected_outputs/s05.dat.json` (e.g. sample 0: $177 \times 0.5 + 100.0 = 188.5\text{ mV}$, $1160 \times 0.5 + 20.5 = 600.5\text{ ppm}$).

**Result:** CONFIRMED

### 2026-10-16 15:47 — Event block structure (Type 2)

**Hypothesis:** Type 2 blocks record timestamped log events and operator annotations.

**Tried:** Parsed Type 2 blocks in s05, s06, and s07.

**Evidence:** Type 2 payload layout is: 2-byte u16le sample index, 1-byte u8 severity level, 1-byte u8 message length $M$, followed by $M$ ASCII message bytes. In `s05.dat`, Block 4 gave `sample: 9, severity: 2, message: 'Sensor drift'` and Block 7 gave `sample: 21, severity: 1, message: 'Run started'`, matching `s05.dat.json` exactly.

**Result:** CONFIRMED

### 2026-10-16 15:47 — Dropout sentinel value in raw data

**Hypothesis:** Sensor dropouts or disconnected channels are represented by a dedicated int16 sentinel.

**Tried:** Scanned raw int16 readings for boundary values across all data blocks.

**Evidence:** In `s06.dat`, samples 0, 6, 11, 12, 19, and 23 contain raw value `-32768` (`0x8000`). According to `kit/OUTPUT-CONTRACT.md`, dropouts are reported as `null`. `-32768` represents the minimum signed 16-bit integer and serves as the dropout indicator.

**Result:** CONFIRMED as `-32768` (`0x8000`).

### 2026-10-16 15:48 — Corruption and damage in s07.dat

**Hypothesis:** Block 5 in `s07.dat` fails its CRC check due to localized bit corruption.

**Tried:** Evaluated stored vs calculated CRC in `s07.dat` Block 5 and tested single-byte mutations.

**Evidence:** Stored CRC is `0x97b2`, while calculated CRC is `0xc4cb`. A single-byte mutation test over the 42-byte block slice revealed that changing byte offset 0x00B2 from `0xF0` to `0xE0` (a single bit flip, bit 4) produces exactly the stored CRC `0x97b2`. This confirms `s07.dat` has an intentional single-bit corruption in sample 9 of Block 5, which must be reported with `DamageKind.CRC_MISMATCH` and `status: "unverified"` on affected records.

**Result:** CONFIRMED
