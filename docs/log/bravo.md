# BRAVO research log

### 2026-10-16 13:58 — Paragraph separator is CR (0x0D) rather than LF (0x0A)

**Hypothesis:** Paragraphs in Xerox Alto Bravo files are delimited by ASCII carriage return `\r` (`0x0D`).

**Tried:** Examined text stream bytes before Ctrl-Z in `kit/samples/s16.bravo` and `s17.bravo`.

**Evidence:** In `s16.bravo`, lines are separated by `0x0D`: `"To: Alto users\r"`, `"From: Documentation\r"`, `"\r"`, `"The new editor supports looks...\r"`, `"End of memo.\r"`. No `0x0A` (line feed) bytes appear anywhere in the file. Similarly, in `s17.bravo`, all 5 paragraphs end with `0x0D`.

**Result:** CONFIRMED. Paragraph boundary is `\r` (0x0D).

### 2026-10-16 14:02 — Ctrl-Z (0x1A) separates document text from formatting trailer

**Hypothesis:** ASCII Ctrl-Z (`0x1A`) marks the boundary between plain paragraph text and the trailing formatting descriptor block.

**Tried:** Located `0x1A` in `s16.bravo` and `s17.bravo` and inspected preceding and following bytes.

**Evidence:** In `s16.bravo`, `0x1A` appears at offset 128 (0x80). Bytes 0..127 contain ASCII text. Bytes 129..143 contain 15 binary trailer bytes. In `s17.bravo`, `0x1A` appears at offset 127 (0x7F), followed by 17 binary trailer bytes.

**Result:** CONFIRMED. Text terminates at `0x1A`.

### 2026-10-16 14:06 — Formatting trailer ends with a carriage return

**Hypothesis:** The project brief suggests that the formatting trailer ends at a carriage return.

**Tried:** Inspected the final bytes of `s16.bravo` and `s17.bravo`.

**Evidence:** The last bytes of `s16.bravo` are `0f 06 00`. The last bytes of `s17.bravo` are `00 61 00`. Neither file has `0x0D` (`\r`) anywhere in the trailer block.

**Result:** REJECTED. The trailer consists of binary descriptor records extending to EOF without a trailing carriage return.

### 2026-10-16 14:10 — Empty paragraphs produce empty text strings

**Hypothesis:** Consecutive carriage returns (`\r\r`) represent empty paragraphs that must be preserved as records with `text: ""`.

**Tried:** Analyzed paragraph sequence in `s16.bravo` and `s17.bravo`.

**Evidence:** In `s16.bravo`, paragraph 1 is `"From: Documentation"`, followed by `\r\r`, then paragraph 3. The empty line at index 2 separates memo headers from memo body, matching standard document layout.

**Result:** CONFIRMED. Empty paragraphs are emitted as `text: ""`.

### 2026-10-16 14:14 — Formatting trailer character run offsets

**Hypothesis:** Binary trailer contains format runs with character start offsets and lengths.

**Tried:** Cross-referenced trailer uint16 values with styled words in the text.

**Evidence:** In `s16.bravo`, the word `"Bold"` starts at character index 67 (0x43). The trailer contains `43 00` (`0x0043` = 67). In `s17.bravo`, the word `"Ethernet"` starts at index 9 (`09 00`), and `"2.9 Mbps"` starts at index 42 (`2a 00`). Both appear in the trailer preceded by run descriptors.

**Result:** CONFIRMED. Trailer encodes formatting runs referencing character offsets.
