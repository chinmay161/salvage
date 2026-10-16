# STUB

## Summary

Synthetic test format made up by Core to exercise the pipeline. No
samples exist; `salvagekit/formats/stub.py` defines it. Test-only: it is
excluded from FORMAT-SPEC.md.

## Identification

Bytes 0x00-0x0C are `53 41 4C 56 41 47 45 2D 53 54 55 42 00`
("SALVAGE-STUB" plus a zero byte, 13 bytes). Exact match → probe 1.0,
otherwise 0.0. Extension `.stub` is a tie-break hint only.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 13 | bytes | — | magic | `SALVAGE-STUB` + `00` | defined in `stub.py` |
| 0x0D | 2 | u16 | LE | count | number of values | defined in `stub.py` |
| 0x0F | 4 × count | u32 | LE | value[i] | the values | defined in `stub.py` |

## Records

A header record (magic, count), then one record per value: `count` u32le
values back to back after the header.

## Checksums

None. The magic is `verified` by exact match; `count` is `consistent`
when the values it announces fit in the file.

## Compression and obfuscation

None.

## Damage handling

A file that ends inside the count or the values gets TRUNCATED damage from
the first missing byte to the end of the file; the values read before it
are kept. A wrong magic gives an empty result (not STUB).

## Open questions

None: the format is defined by its code.
