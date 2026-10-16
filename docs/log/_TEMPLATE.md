# <FORMAT NAME> research log

<!--
Template. Copy this file to docs/log/<module>.md (e.g. docs/log/libra98.md),
set the title to "# <decoder name> research log" and delete this comment
and the example entry.

All times are local time (IST, UTC+05:30), written "YYYY-MM-DD HH:MM".

Add one entry for EVERY hypothesis you test, including the ones that
failed: they stop others from trying the same thing. Never delete or
rewrite an old entry; if a later finding changes it, add a new entry that
says so.

Every entry has exactly this shape:

  ### YYYY-MM-DD HH:MM — <short title>
  **Hypothesis:** what you thought was true.
  **Tried:** what you did to test it.
  **Evidence:** what you saw (numbers, offsets, sample names).
  **Result:** CONFIRMED | REJECTED | INCONCLUSIVE

Leave a blank line between the four lines (as in the example below) so
Markdown keeps them apart. Result is one of the three words, in capitals,
optionally followed by a short explanation. tools/build_docs.py merges all logs into FIELD-LOG.md,
sorted by date and time; a heading with a bad date or time fails
`python tools/task.py docs`.
-->

### 2026-10-16 14:05 — Record length is u16 big-endian?

**Hypothesis:** bytes 2-3 of each record are its length, u16 big-endian.

**Tried:** read them as u16be in `samples/libra98/a.lb9` and jumped that far.

**Evidence:** the jump lands exactly on the next `A5 5A` marker 41/41
times; read as u16le it never does.

**Result:** CONFIRMED. The length excludes the 4-byte record header.
