# BRAVO

## Summary

BRAVO is the document format of the Bravo editor developed at Xerox PARC for the Xerox Alto workstation in the 1970s (context hint: "Document from a 1970s research-lab workstation editor"). The format stores document text in plain ASCII up to a Ctrl-Z (`0x1A`) marker, followed by a binary formatting trailer containing style run descriptors ("looks"). Studied samples: `kit/samples/s16.bravo` (144 bytes), `kit/samples/s17.bravo` (145 bytes).

## Identification

Files are identified by:
- Plain text printable ASCII stream ending with a carriage return (`\r`) followed by Ctrl-Z (`0x1A`).
- Presence of ASCII headers or document lines with CR delimiters without line feeds (`\n`).
- Binary formatting trailer immediately following `0x1A`.
- Probing:
  - If text is valid ASCII, CR-delimited, and followed by `0x1A` and a binary trailer: probe score 0.9.
  - If `.bravo` extension matches: tie-break hint.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | variable | ASCII | — | text_stream | Paragraph text separated by `\r` (0x0D) | s16.bravo, s17.bravo |
| n | 1 | u8 | — | ctrl_z | Trailer delimiter (`0x1A`) | at offset 128 in s16, 127 in s17 |
| n + 1 | variable | bytes | LE | trailer | Binary formatting trailer ("looks") | follows 0x1A to EOF |

## Records

Per `OUTPUT-CONTRACT.md`, the output consists of:
- `records`: List of objects, one per CR-terminated paragraph:
  - `index`: 0-based integer indicating paragraph sequence.
  - `text`: String containing the paragraph content, stripped of trailing carriage return.
- Optional `metadata.format_runs`:
  - List of run objects: `start`, `length`, `looks[]` (e.g., `"bold"`, `"italic"`), `font`.

Empty paragraphs (represented by consecutive `\r` bytes) produce a record with `text: ""`.

## Checksums

None. Bravo files rely on structural delimiters (`\r`, `0x1A`) and do not contain cryptographic or CRC checksums.

## Compression and obfuscation

None. Text is uncompressed 7-bit ASCII.

## Damage handling

- **Missing Ctrl-Z delimiter:** If file contains valid CR-terminated text but lacks `0x1A`, decode text paragraphs as recovered, flag `truncated` damage, and set status to `partial`.
- **Corrupted trailer:** Malformed binary trailer bytes do not affect text recovery; parsing skips corrupted trailer entries and reports `unparsed_bytes` damage.
- **Premature EOF:** Unclosed paragraphs at EOF are recovered with trailing damage reported.

## Open questions

- Variable trailer structures: In some Alto documents, paragraph properties (margins, tabs) may accompany character looks; full catalog of Alto font IDs (e.g. Gacha, Helvetica, Times Roman) depends on workstation font configuration.
