# WPD

## Summary

WPD is the document format of WordPerfect 5.x for DOS and Windows (context hint: "Word-processor document from a government office, early 1990s; some files are password-protected"). Files contain a 16-byte fixed file identification header, followed by document metadata/prefix packets, and a document text stream beginning at a designated text pointer offset. Studied samples: `kit/samples/s14.wpd` (288 bytes, valid document with formatting codes and document summary), `kit/samples/s15.wpd` (136 bytes, truncated document ending mid-sentence).

## Identification

Files begin with a 4-byte signature:
- Bytes 0..3: `FF 57 50 43` (`\xFFWPC`).
- Offset 0x08: Document file type `0x01` (WordPerfect document file).
- Offset 0x09: Major version `0x0A` (WordPerfect 5.0/5.1).
- Probing:
  - Exact match of `\xFFWPC` with document type 1 and major version 10 yields probe score 1.0.
  - `\xFFWPC` alone yields probe score 0.7.
  - Extension `.wpd` is a tie-breaker hint only.

## Layout

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 4 | bytes | — | magic | Header signature (`\xFFWPC`) | s14.wpd, s15.wpd |
| 0x04 | 4 | u32 | LE | doc_pointer | Pointer to start of document body text | 0x00000030 (48) in s14, s15 |
| 0x08 | 1 | u8 | — | product_type | Product type (1 = WordPerfect) | s14.wpd, s15.wpd |
| 0x09 | 1 | u8 | — | file_type | File type / major version (10 = WP 5.x) | s14.wpd, s15.wpd |
| 0x0A | 1 | u8 | — | minor_version | Minor version (2) | s14.wpd, s15.wpd |
| 0x0B | 2 | u16 | LE | encrypt_key | Encryption key (0 = unencrypted) | 0x0000 in s14, s15 |
| 0x0D | 3 | bytes | — | reserved | Header padding/reserved bytes | zeroed in samples |
| 0x10 | variable | bytes | — | prefix_area | Prefix packets (styles, summary) | up to doc_pointer |
| doc_ptr | variable | bytes | — | body | Document text and function code stream | extends to EOF |

## Records

Per `OUTPUT-CONTRACT.md`, the output consists of:
- `records`: List of objects:
  - `index`: 0-based integer indicating record sequence.
  - `type`: String, either `"paragraph"` or `"page_break"`.
  - `text`: String containing the recovered paragraph text (or empty string for page breaks).

Structural rules:
- Hard return `0x0A` terminates a paragraph.
- Soft return `0x0D` represents soft line wraps and is converted to space.
- Page break codes (`0x0B`, `0x0C`) emit a separate record with `type: "page_break"` and `text: ""`.
- Function codes: Fixed 3-byte codes (`0xC0`..`0xC7`) and variable-length multibyte codes (`0xD0`..`0xFF`) are stripped from output text.
- Special character encodings: Hard space `0xA0` decodes to `' '`, tab `0x09` decodes to `'\t'`, soft hyphen `0xAA` is stripped.

## Checksums

None. WordPerfect 5.x headers and text streams do not use CRC or checksum fields.

## Compression and obfuscation

- Standard files are uncompressed.
- Password-protected documents use an encryption key stored at offset 0x0B. When `encrypt_key != 0`, the file is encrypted. Per project requirements, no password cracking is attempted; the file is reported as `unsupported=True` with damage kind `encrypted`.

## Damage handling

- **Encryption:** Detected via non-zero encryption key at offset 0x0B. Handled cleanly with status `unsupported` and damage kind `encrypted`.
- **Out-of-bounds text pointer:** If `doc_pointer` exceeds file size, reported as `bounds` damage; status becomes `failed`.
- **Truncation:** If document text ends without a closing paragraph delimiter (as in `s15.wpd`), all preceding text is recovered, status is set to `partial`, and `truncated` damage is reported at the break point.
- **Malformed function codes:** If variable-length function code boundaries are invalid, resynchronization skips damaged bytes to the next valid text or return delimiter, reporting `unparsed_bytes`.

## Open questions

- Extended character sets: WordPerfect multi-character character sets (e.g. math, box drawing, Cyrillic) use extended multi-byte escapes; standard ASCII and Latin-1 ranges are confirmed.
