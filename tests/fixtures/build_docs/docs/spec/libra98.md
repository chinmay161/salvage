# LIBRA-98

## Summary

Library catalogue export. See [the decoder](../../salvage/formats/libra98.py).

## Identification

Magic `LB98` at 0x00.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 4 | bytes | — | magic | `LB98` | all samples |

```text
# not a heading: inside a code fence
```

## Records

Back to back.

## Checksums

CRC-16/XMODEM.

## Compression and obfuscation

None.

## Damage handling

Resync on the marker.

## Open questions

None.
