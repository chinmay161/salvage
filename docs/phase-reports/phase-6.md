# Phase 6 report: Phase 5 follow-ups, templates, docs assembly, README, precheck

Branch `phase-6`: 3 commits on top of `main` 3b0dee7 (eb88496, 6b09a1d,
f612074), plus a 4th commit with this report. Per-file outputs are
byte-identical to Phase 5. I ran both versions on samples/ plus the golden
inputs (34 files), and all 35 output files matched, report.json included.
The golden tests pass unchanged. The contract (model.py, plugin.py,
reader.py) was not touched.

## 1. Files created or changed

| file | change |
|---|---|
| `salvage/core/pipeline.py` | A1: too-large files are hashed. A2: new `folders_overlap()`; the overwrite guard runs only when the folders overlap |
| `tests/core/test_pipeline.py` | too-large test updated; new: 1 MiB chunk streaming test, `OverwriteGuardTests` (overlap rules, input inside output, disjoint folders resolve only 2 paths) |
| `tests/core/test_hardening.py` | too-large via `SALVAGE_LIMITS`: hashed, never sent to a worker |
| `docs/output-format.md` | sha256 and "too large" wording |
| `docs/spec/_TEMPLATE.md`, `docs/log/_TEMPLATE.md` | new templates (B1, B2) |
| `docs/spec/stub.md`, `docs/log/stub.md` | rewritten in template format (the old spec had a raw NUL byte in it) |
| `docs/decoder-guide.md` | section 11 rewritten ("Format spec and FIELD-LOG entries"); section 1 table points at the templates |
| `docs/conformance.md` | C11 fix text points at the templates |
| `tools/build_docs.py`, `tools/build_docs_intro.md` | new docs assembler and the hand-written intro (C1-C3) |
| `tools/task.py` | new: `docs`, `check-outputs`, `lint-docker`, `save-base`, `load-base`, `precheck` |
| `tests/core/test_build_docs.py`, `tests/fixtures/build_docs/**` | C4 tests (22) and a miniature repo fixture |
| `tests/core/test_task_tools.py` | Dockerfile lint and check-outputs tests (7) |
| `FORMAT-SPEC.md`, `FIELD-LOG.md` | generated |
| `README.md` | rewritten (D), with the formats markers |
| `CLAUDE.md`, `Makefile`, `.gitignore` | new commands and the "never edit generated docs" rule; make targets; `/dist/` |
| `docs/phase-reports/phase-6.md` | this report |

## 2. Part A

**A1 test change.** `test_too_large_is_failed_without_reading` became
`test_too_large_is_hashed_but_never_decoded`. Before, it asserted that
`sha256_file` was never called and that `sha256` was null. Now it asserts
that `Worker` is never created, that `sha256_file` is called once, and that
`sha256` in the report and in `source.sha256` equals the real
`hashlib.sha256`.

The hardening test (`..._is_hashed_never_decoded`, real CLI with
`SALVAGE_LIMITS`) now expects the call list `[big.bin, small.stub,
small.stub]`: big.bin is hashed only, and small.stub is hashed and then
decoded. It also expects the correct digest. A new test checks that
`sha256_file` reads in exactly 1 MiB chunks.

One side effect: a too-large file that disappears before hashing is now
reported as `file disappeared`.

**A2.** The input and output roots are resolved once (`realpath`). If
neither folder contains the other, the `protected` set is empty and no
per-target `realpath` runs. A test checks that a disjoint run calls `_key`
exactly twice. The existing same-folder test still passes, and a new
input-inside-output test checks that the guard still refuses to overwrite
an input.

`bench --docker` (525 files, salvage:dev, 12 CPUs). I ran it twice each
way; "before" was rebuilt from HEAD in the same session:

| run | jobs 1 s | jobs 1 files/s | auto(4) s | auto(4) files/s |
|---|---:|---:|---:|---:|
| before, run 1 | 22.09 | 23.8 | 13.34 | 39.4 |
| before, run 2 | 17.52 | 30.0 | 13.03 | 40.3 |
| after, run 1 | 14.11 | 37.2 | 9.78 | 53.7 |
| after, run 2 | 13.43 | 39.1 | 9.30 | 56.4 |
| (Phase 5 report, before) | 14.84 | 35.4 | 11.10 | 47.3 |

With `--jobs auto` the gain is about 40% (about 40 → 55 files/s). The
`--jobs 1` and `--jobs auto` outputs were byte-identical in every run.

## 3. The two templates, in full

`docs/spec/_TEMPLATE.md`:

````markdown
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
"card catalogue, 1998"). Studied: `samples/libra98/a.lb9` (4,112 bytes),
`samples/libra98/b.lb9` (truncated, 1,020 bytes).

## Identification

<The magic bytes or probe logic, with offsets, and what probe() scores.>

Example: bytes 0-3 are `4C 42 39 38` ("LB98") → probe 0.9; plus header
CRC at 0x0E matching → 1.0. Extension `.lb9` is a tie-break hint only.

## Layout

<Every known field. Offsets are from the file start unless the Field says otherwise; Evidence says how you know.>

| Offset | Size | Type | Endian | Field | Meaning | Evidence |
|--------|------|------|--------|-------|---------|----------|
| 0x00 | 4 | bytes | — | magic | `LB98` | identical in all 12 samples |
| 0x04 | 2 | u16 | LE | version | format version (seen: 3) | log 2026-10-16 14:05 |
| 0x06 | 2 | u16 | LE | count | number of records | equals records found in 12/12 samples |

## Records

<Record structure, how many there are, and how each record is found.>

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

Example: a CRC mismatch marks the record `unverified` with CHECKSUM damage
over its text; a truncated record's missing fields are `lost` with
TRUNCATED damage to the end of the file; junk between records is skipped
by resync and reported as UNPARSED.

## Open questions

<What is still unknown or unverified; link the log entries.>

Example: the meaning of header bytes 0x08-0x0B (always zero in our
samples) is unknown; they are labelled `header.reserved`, not padding.
````

`docs/log/_TEMPLATE.md`:

````markdown
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
optionally followed by a short explanation. tools/build_docs.py merges all
logs into FIELD-LOG.md, sorted by date and time; a heading with a bad date
or time fails `python tools/task.py docs`.
-->

### 2026-10-16 14:05 — Record length is u16 big-endian?

**Hypothesis:** bytes 2-3 of each record are its length, u16 big-endian.

**Tried:** read them as u16be in `samples/libra98/a.lb9` and jumped that far.

**Evidence:** the jump lands exactly on the next `A5 5A` marker 41/41
times; read as u16le it never does.

**Result:** CONFIRMED. The length excludes the 4-byte record header.
````

## 4. Generated now

FORMAT-SPEC.md table of contents. The only spec file is STUB's, which is
excluded, so the file holds the intro, this TOC, the line "No format
specifications have been written yet." and the demoted output format:

```markdown
## Contents

- [Output format — PROVISIONAL](#output-format--provisional)
```

FIELD-LOG.md summary table:

```markdown
| Format | Entries | Confirmed | Rejected | Inconclusive |
|--------|--------:|----------:|---------:|-------------:|
| **Total** | **0** | **0** | **0** | **0** |
```

## 5. README

Section headings: `# Salvage` (the 3-line pitch), `## Quick start`,
`## What you get`, `## Damaged files and our honesty policy`,
`## Supported formats`, `## Specs and research log`,
`## Offline / air-gapped use`, `## Development`,
`## Project layout and team`.

Generated formats table (between the markers):

```markdown
<!-- formats:start -->
No format decoders merged yet.
<!-- formats:end -->
```

## 6. precheck

Run on HEAD f612074 from a committed tree. Five untracked organizer paths
were noted (see section 9).

```text
precheck summary (HEAD f612074)
| # | step | result | seconds |
|---|------|--------|--------:|
| 1 | test | PASS | 35.1 |
| 2 | conform (full) | PASS | 0.7 |
| 3 | docs --check | PASS | 0.2 |
| 4 | lint-docker | PASS | 0.1 |
| 5 | build --no-cache --network none | PASS | 2.2 |
| 6 | docker run on samples/ + golden inputs | PASS | 1.2 |
| 7 | docker-smoke | PASS | 2.1 |
precheck: 7 PASS, 0 FAIL; total time 42.0 s
```

Step 6 covered 34 inputs: 30 samples, 1 sample in a subfolder and 3
golden inputs.

Offline proof, done by hand:

1. `save-base`
2. `docker rmi python:3.12-slim` (the base image was gone afterwards)
3. `load-base`
4. `docker build --no-cache --network none`

The build succeeded, and the base image tag was restored.

## 7. Test totals and times

| run | tests | skipped | time |
|---|---:|---:|---:|
| Windows `task.py test` | 301 | 5 | 35.5 s (Phase 5: 268 in 32.6 s) |
| `task.py docker-test` (Linux) | 301 | 0 | 50.1 s |

Also: `docs --check` passes, `golden` passes (unchanged), and `conform`
(full) gives STUB PASS.

## 8. Deviations

1. **Committed on branch `phase-6`, not `main`.** The repo rules say to
   branch before committing on the default branch. Precheck clones HEAD,
   so it is unaffected. Merge when you are happy with it.
2. **Errors write nothing.** When `docs` hits an error (bad log date,
   missing README markers), it writes no files and exits 1. A
   half-generated FIELD-LOG is worse than a stale one.
3. **Spec links are rebased.** Relative links in spec files and the intro
   are rewritten to be relative to the repo root, so they still work
   inside FORMAT-SPEC.md. Log entry bodies are copied unchanged, as
   specified.
4. **Spec column.** The README "Spec" column is
   `[yes](FORMAT-SPEC.md#anchor)` or `no`. The Log column is `yes`/`no`.
5. **Extra warnings.** These are warnings, not errors: a decoder with no
   spec or log, and a spec file with no matching decoder. A `###` heading
   in a log that is not `### <date> — <title>` at all is treated like a
   bad date (error with file:line). Result words must be in capitals, so
   `confirmed` gives a warning and is not counted.
6. **lint-docker also checks ADD.** An `ADD` with a URL is flagged as well
   (it downloads at build time). Tool names match as whole words, so
   `digit` does not match `git`.
7. **save-base saves by tag.** It saves `python:3.12-slim` (after checking
   that the tag is the pinned digest) so that `docker load` restores the
   tag. An image saved by digest loads untagged. The presence check also
   accepts an untagged image whose ID is the pinned digest (containerd
   image store).
8. **samples/ is not committed.** Precheck uses the working tree's
   samples/ (read-only) when the clone has none, for conform (full) and
   step 6, and says so in its output.
9. **New `check-outputs IN OUT` command.** Precheck step 6 runs the
   clone's copy, so outputs are validated with HEAD's code and schemas.
10. **Steps 6 and 7 depend on the build.** If step 5 fails, they FAIL with
    "not run: the build failed" rather than testing a stale `salvage:dev`
    image.
11. **README build command.** It uses `docker build -t salvage .` as
    specified. The task.py docker commands still use `salvage:dev`.

## 9. Not done / to watch

- **The organizer contract has arrived and does not match our output.**
  New untracked files appeared in the working tree during this phase:
  `docs/OUTPUT-CONTRACT.md`, `docs/HINTS.md`, `docs/README.md`, `samples/`
  (31 files) and `expected_outputs/`. The contract has a different shape:
  - statuses `ok|partial|unsupported|unrecognized|failed`;
  - a `source_file` field;
  - damage kinds such as `crc_mismatch`;
  - a non-recursive walk;
  - a different `report.json`;
  - a format list that includes `EBCDIC-DUMP`.

  This phase required byte-identical output, so I changed nothing. Moving
  `emit.py`/`report.py` and the schemas to this contract should be the
  next core task. I did not commit or edit any of these files.
- When the EBCDIC-DUMP decoder lands, its module sorts after the listed
  formats, alphabetically. Add it to `FORMAT_ORDER` in
  `tools/build_docs.py` if you want it elsewhere.
- **A2 symlink gap.** The guard is skipped when the folders do not overlap
  by `realpath`. A symlinked subfolder created inside the output folder
  before the run and pointing into the input folder is therefore no longer
  guarded. This is an unusual setup, but the gap is new.
- **Untested precheck failure paths.** Missing base image and git clone
  failure were checked by reading the code, not by forcing a failure.
- `--strict` exists but nothing uses it yet. The Phase 7 precheck can
  switch to it.
