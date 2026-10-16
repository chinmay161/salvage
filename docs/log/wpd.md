# WPD research log

### 2026-10-16 14:03 — File header signature and document pointer layout

**Hypothesis:** WordPerfect documents begin with 4-byte signature `FF 57 50 43` (`\xFFWPC`) followed by a 4-byte pointer to document text at offset 0x04.

**Tried:** Unpacked header fields of `kit/samples/s14.wpd` (288 bytes) and `kit/samples/s15.wpd` (136 bytes).

**Evidence:** Both files begin with `ff 57 50 43`. Bytes 4..7 unpack as uint32le `0x00000030` (48). Reading document text at offset 48 yields `"MEMORANDUM\n..."` in both samples.

**Result:** CONFIRMED. Header magic is `\xFFWPC` and document text starts at uint32le offset stored at 0x04.

### 2026-10-16 14:06 — Header metadata: file type, version, and encryption key

**Hypothesis:** Header offsets 0x08..0x0C store document type, version numbers, and encryption key.

**Tried:** Unpacked bytes 8..12 across `s14.wpd` and `s15.wpd`.

**Evidence:** Byte 8 is `0x01` (WordPerfect document type). Byte 9 is `0x0a` (10, indicating WordPerfect 5.0/5.1 architecture). Byte 10 is `0x02` (minor version). Bytes 11..12 are `0x0000` (uint16le encryption key). When non-zero, this key signifies password protection.

**Result:** CONFIRMED. Key at offset 0x0b-0x0c detects encryption without cracking.

### 2026-10-16 14:10 — Hard returns vs soft returns in paragraph reconstruction

**Hypothesis:** Hard return `0x0A` marks paragraph boundaries, while soft return `0x0D` represents wrapped lines within a paragraph.

**Tried:** Analyzed line endings in paragraph 3 of `s14.wpd`: `"The quarterly returns are due on the\r15th. Late submissions will be\rreturned unprocessed.\n"`.

**Evidence:** The sentence wraps across lines using `0x0D` after `"the"` and `"be"`. Replacing `0x0D` with space produces a coherent paragraph: `"The quarterly returns are due on the 15th. Late submissions will be returned unprocessed."`. Hard return `0x0A` cleanly terminates the paragraph.

**Result:** CONFIRMED. Hard return `0x0A` defines paragraph boundaries; soft return `0x0D` is a soft line wrap.

### 2026-10-16 14:13 — WordPerfect function codes filtering

**Hypothesis:** Function codes beginning in `0xC0..0xFF` (such as `\xc3\x0c\xc3` and `\xc4\x0c\xc4`) are formatting instructions and must be stripped from recovered plain text.

**Tried:** Inspected `"Subject: Revised \xc3\x0c\xc3filing deadline\xc4\x0c\xc4\n"` in `s14.wpd`.

**Evidence:** `\xc3\x0c\xc3` is Font Attribute On (Underline) and `\xc4\x0c\xc4` is Font Attribute Off. Stripping these 3-byte codes yields `"Subject: Revised filing deadline"`.

**Result:** CONFIRMED. Fixed and variable function codes are stripped to yield clean text.

### 2026-10-16 14:16 — Special character codes: hard space and soft hyphen

**Hypothesis:** Byte `0xA0` represents a non-breaking space and `0xAA` represents a soft hyphen.

**Tried:** Analyzed `"Ref:\tMr.\xa0Smith, co\xaaoperation notes attached.\n"` in `s14.wpd`.

**Evidence:** `0xA0` separates `"Mr."` and `"Smith"`, functioning as a hard space. `0xAA` occurs inside `"co-operation"` / `"cooperation"`, functioning as a discretionary soft hyphen that is omitted when unhyphenated.

**Result:** CONFIRMED. `0xA0` decodes to space `' '` and `0xAA` is stripped.

### 2026-10-16 14:19 — Detecting file truncation in s15.wpd

**Hypothesis:** `s15.wpd` is a truncated version of `s14.wpd` that ends abruptly during the 4th paragraph.

**Tried:** Checked EOF state and ending byte sequence of `s15.wpd` (136 bytes).

**Evidence:** `s15.wpd` ends at offset 136 with `"Please note: \xc3\x0c\xc3deadline"`. It lacks a terminating `0x0A`, closing attribute code, or full text sentence. The decoder emits recovered paragraphs 0..3 and marks file as `partial` with `truncated` damage at offset 136.

**Result:** CONFIRMED. `s15.wpd` is truncated.
