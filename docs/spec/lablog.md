# LABLOG

## Summary

LABLOG is a binary analytical-instrument data logger format (context hint: "Benchtop analytical-instrument data logger, chemistry lab, early 1990s"). Studied: `kit/samples/s05.dat` (229 bytes, clean 2-channel log from THERMO LOGGER), `kit/samples/s06.dat` (313 bytes, clean 3-channel log from FLOWCELL-2 containing dropouts), and `kit/samples/s07.dat` (334 bytes, 3-channel log from FLOWCELL-2 containing localized bit corruption in Block 5).

## Identification

Files begin with ASCII `LLOG` (`4C 4C 4F 47`) at offset 0x00 followed by major version 1 at 0x04. `probe()` requires at least 32 bytes, magic `LLOG`, version 1, and non-zero channel count. If the 16-bit CRC-16-CCITT at 0x1E matches bytes 0x00..0x1D, probe scores 1.0; if magic matches but header CRC is mismatched, probe scores 0.8. Extensions `.dat` and `.log` serve as hints.

## Layout

### Header (32 bytes fixed)

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|---|---|---|---|---|---|---|
| 0x00 | 4 | bytes | — | magic | ASCII `LLOG` (`4C 4C 4F 47`) | all samples |
| 0x04 | 1 | u8 | — | version | Format major version (1) | all samples |
| 0x05 | 1 | u8 | — | num_channels | Number of analog channels ($\ge 1$) | all samples |
| 0x06 | 2 | u16 | LE | sample_interval | Sampling interval in centiseconds ($10\text{ ms}$ units) | all samples |
| 0x08 | 16 | bytes | — | instrument | Null-padded ASCII instrument name | all samples |
| 0x18 | 4 | u32 | LE | start_time | Start datetime as seconds since 1990-01-01 00:00:00 UTC | log 2026-10-16 15:43 |
| 0x1C | 2 | u16 | LE | declared_block_count | Total number of blocks following the header | all samples |
| 0x1E | 2 | u16 | LE | header_crc | CRC-16-CCITT over bytes 0x00..0x1D (poly 0x1021, init 0xFFFF) | log 2026-10-16 15:44 |

### Block Framing

Blocks follow the 32-byte header contiguously back-to-back:
- `+0x00` (1B): Sync marker `0xB1`
- `+0x01` (1B): Block type (`0x03` = Channel Config, `0x01` = Data, `0x02` = Event)
- `+0x02` (2B u16le): Payload length $L$
- `+0x04` ($L$ bytes): Block payload
- `+0x04 + L` (2B u16le): Trailer CRC-16-CCITT over `block[1 : 4 + L]` (type + length + payload)

### Block Types

1. **Type 0x03 (Channel Configuration, Block 1):** Length is $\text{num\_channels} \times 12$. Each 12-byte descriptor contains:
   - `+0x00` (4B ASCII): Unit name, null-padded (e.g. `mV`, `ppm`, `pH`, `kPa`, `degC`)
   - `+0x04` (4B float32le): Linear calibration scale factor
   - `+0x08` (4B float32le): Linear calibration offset value
2. **Type 0x01 (Data Records):** Contains:
   - `+0x00` (2B u16le): Start sample index
   - `+0x02` (1B u8): Sample count $N$
   - Followed by $N$ sample records, each consisting of $\text{num\_channels} \times 2$ bytes of signed 16-bit integers (`int16le`).
   - Calibrated value: $\text{round}(\text{raw} \times \text{scale} + \text{offset}, 4)$.
   - Dropout sentinel: raw `-32768` (`0x8000`) represents a dropout and maps to JSON `null`.
   - Sample timestamp: $\text{time\_ms} = \text{sample} \times (\text{sample\_interval} \times 10)$.
3. **Type 0x02 (Event Annotations):** Contains:
   - `+0x00` (2B u16le): Associated sample index
   - `+0x02` (1B u8): Severity level ($0$ = info/note, $1$ = run started, $2$ = warning/drift)
   - `+0x03` (1B u8): Message length $M$
   - `+0x04` ($M$ bytes ASCII): Event message text

## Records

Each recorded sample becomes one record containing three fields:
- `sample`: integer sample index
- `time_ms`: elapsed milliseconds since start time
- `values`: array of calibrated float values (or `null` for channel dropouts)

Records are emitted sequentially in sample index order.

## Checksums

1. **Header Checksum:** 2-byte CRC-16-CCITT (polynomial `0x1021`, initial value `0xFFFF`, no final XOR, little-endian) over bytes 0x00..0x1D (30 bytes). Stored at 0x1E..0x1F.
2. **Block Checksums:** 2-byte CRC-16-CCITT (polynomial `0x1021`, initial value `0xFFFF`, no final XOR, little-endian) over bytes 1 through $4 + L$ of each block (type, length, and payload; excluding the marker `0xB1`). Stored at the final two bytes of each block.

## Compression and obfuscation

None. Strings are plaintext ASCII, timestamps and integers are little-endian binary, and analog values are linear 16-bit ADC counts.

## Damage handling

- **CRC Mismatch:** If a block fails its CRC check (e.g. Block 5 in `s07.dat`), `DamageKind.CHECKSUM` is reported over the block range, the block's records are marked `Status.UNVERIFIED`, and the file status drops to `partial`.
- **Truncation:** If the file ends before declared blocks finish, or cuts short inside a header or block payload, `DamageKind.TRUNCATED` is recorded over the missing or incomplete range.
- **Lost Synchronization:** If marker `0xB1` is not found where expected, `salvage.core.resync` searches forward for `0xB1` followed by a valid block type, in-bounds length, and matching CRC-16-CCITT. Skipped corrupted bytes are reported as `DamageKind.UNPARSED`.
- **Invalid Structure:** Unknown block types, mismatched block lengths, or zero-channel headers produce `DamageKind.BOUNDS` or `DamageKind.UNPARSED`.

## Open questions

None. All fields, timestamps, block structures, checksum algorithms, and sample values across `s05.dat`–`s07.dat` are confirmed and fully explained.
