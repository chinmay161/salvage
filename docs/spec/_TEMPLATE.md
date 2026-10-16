# <FORMAT NAME>

<!--
Template. Copy this file to docs/spec/<module>.md (e.g. docs/spec/libra98.md)
and replace every part in <angle brackets>. The first line must be
"# <decoder name>", exactly the decoder's `name` (e.g. "# LIBRA-98").
Keep all eight "##" sections, in this order; write "None" or "Unknown"
rather than deleting one. tools/build_docs.py assembles these files into
FORMAT-SPEC.md and warns about missing sections. Files starting with "_"
(like this one) are never assembled. Delete this comment in your copy.
-->

## Summary

<What the format is, the context hint that came with it, and which samples you studied.>

Example: LIBRA-98 is a record-based library catalogue export (context hint:
"Municipal library circulation desk PC, about 1998"). Studied:
`kit/samples/s01.dat` (289 bytes) and `kit/samples/s04.dat` (truncated, 259 bytes).

## Identification

<The magic bytes or probe logic, with offsets, and what probe() scores.>

Example: bytes 0-3 are `4C 42 39 38` ("LB98") → probe 0.9; plus header
CRC at 0x0E matching → 1.0. The extension is a tie-break hint only.

## Layout

<Every known field. Offsets are from the file start unless the Field says otherwise; Evidence says how you know.>

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 4 | bytes | — | magic | `LB98` | identical in all 12 samples |
| 0x04 | 2 | u16 | LE | version | format version (seen: 3) | log 2026-10-16 14:05 |
| 0x06 | 2 | u16 | LE | count | number of records | equals records found in 12/12 samples |

## Records

<Record structure, how many there are, how each record is found, and how
its bytes map to the contract's record fields (salvagekit/core/contract_shapes.py).>

Example: `count` records follow the 16-byte header back to back. Each is
`A5 5A`, u16be length n, n bytes of Latin-1 text, u16le CRC. Found by
walking lengths; after damage, by resync on `A5 5A` + sane length + CRC.

## Checksums

<Algorithm, the byte range it covers, and where it is stored.>

Example: CRC-16/XMODEM over the record's text bytes (not the marker or
length), stored u16le right after the text. Found with
`checksums.find_checksum` on 40 records, 40/40 matches.

## Compression and obfuscation

<"None" if none; otherwise the algorithm, what it covers and how you undo it.>

Example: None.

## Damage handling

<What damage the decoder detects, how it recovers, and what it reports as lost.>

Example: a CRC mismatch marks the record `unverified` (output:
`"verified": false`, `"issues": ["crc_mismatch"]`) with CRC_MISMATCH damage
over its text, not lossy since the text is kept; a truncated record's
missing fields are `lost` (null) with TRUNCATED damage to the end of the
file; junk between records is skipped by resync and reported as
UNPARSED_BYTES.

## Open questions

<What is still unknown or unverified; link the log entries.>

Example: the meaning of header bytes 0x08-0x0B (always zero in our
samples) is unknown; they are labelled `header.reserved`, not padding.
