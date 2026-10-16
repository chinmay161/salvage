# Decoder guide

Read this instead of the core code. It covers everything a format decoder
needs. A complete, tested decoder to copy from is
[`docs/decoder-template.py`](decoder-template.py) (made-up format
"EXAMPLE"). The output shape is the organizers' contract
([kit/OUTPUT-CONTRACT.md](../kit/OUTPUT-CONTRACT.md)), described with our
decisions in [`docs/output-format.md`](output-format.md).

Contents:

1. [Where your files go](#1-where-your-files-go)
2. [The Decoder class](#2-the-decoder-class)
3. [SafeReader](#3-safereader)
4. [Statuses](#4-statuses-verified--consistent--unverified--lost)
5. [Damage](#5-damage)
6. [Recovering from damage with resync](#6-recovering-from-damage-with-resync)
7. [Archives](#7-archives)
8. [Records and metadata: the contract shapes](#8-records-and-metadata-the-contract-shapes)
9. [Unsupported files](#9-unsupported-files)
10. [variant and confidence](#10-variant-and-confidence)
11. [Running your decoder alone](#11-running-your-decoder-alone)
12. [Golden tests](#12-golden-tests)
13. [Calibrating against the expected outputs](#13-calibrating-against-the-expected-outputs)
14. [Format spec and FIELD-LOG entries](#14-format-spec-and-field-log-entries)
15. [Before opening a pull request](#15-before-opening-a-pull-request)

## 1. Where your files go

For a format, the module name is the contract name in lowercase with `-`
dropped or turned into `_` (`libra98`, `lablog`, `vault`, `wks`, `wpd`,
`bravo`, `cvt`, `ebcdic_dump`, `wad`, `pak`):

| what | where |
|------|-------|
| the decoder | `salvagekit/formats/<module>.py` |
| golden test cases | `tests/<module>/cases/` |
| other tests | `tests/<module>/test_*.py` (add an empty `tests/<module>/__init__.py`) |
| what you found out about the format | `docs/spec/<module>.md`, copied from [`docs/spec/_TEMPLATE.md`](spec/_TEMPLATE.md) (section 14) |
| your research log | `docs/log/<module>.md`, copied from [`docs/log/_TEMPLATE.md`](log/_TEMPLATE.md) (section 14) |

Do not edit, without asking the lead: `salvagekit/core/`, `salvagekit/cli.py`,
`salvagekit/formats/stub.py`, `tests/core/`, `tests/fixtures/`, `tools/`,
`salvage`, `salvage.cmd`, `Dockerfile`, `Makefile`, `README.md`,
`CLAUDE.md`. Never edit `kit/` (the organizers' samples, hints and
expected outputs) or `schema/`. Never edit another teammate's format files.

Hard rules: standard library only, no network; the code must run on
Python 3.10 or newer (we develop on 3.12). Decoder files must not start
with `_` (those are skipped by discovery).

## 2. The Decoder class

```python
from salvagekit.core.plugin import Decoder

class Libra98Decoder(Decoder):
    name = "LIBRA-98"            # a contract format name; it is "format" in the output
    extensions = (".dat",)       # weak hint only: breaks ties, never decides

    def probe(self, data: bytes) -> float: ...
    def decode(self, reader: SafeReader) -> DecodeResult: ...
    def encode(self, result: DecodeResult) -> bytes: ...   # optional
```

- **`name`** must be exactly one of the contract's format names:
  `LIBRA-98`, `LABLOG`, `VAULT`, `WKS`, `WPD`, `BRAVO`, `CVT`,
  `EBCDIC-DUMP`, `WAD`, `PAK` (conformance check C1 fails otherwise).
- **`probe(data)`** gets the whole file as bytes and returns 0.0-1.0: how
  sure you are the file is yours. Look at magic bytes and header sanity.
  Decoders scoring at least 0.5 are tried, best first. Keep it fast (every
  probe runs on every file).
- **`decode(reader)`** reads the file only through the given `SafeReader`
  and returns a `DecodeResult` (from `salvagekit.core.model`): `records`
  (each a `Record` holding `Field`s; one record = one contract record),
  `meta` (the contract's `metadata`), `damage`, `warnings`, `members`
  (archives) and `unsupported`. Return the best partial result you can. A
  result with no records and no members counts as "empty": core then tries
  the next candidate.
- **`encode(result)`** is optional. Implement it if you can rebuild the
  exact bytes; that makes round-trip evidence possible.
- **`probe` and `decode` NEVER raise.** Wrap risky code. A raise, a hang
  (20 s limit) or a crash makes the file `failed`, and your output is lost.
- Core checks your result before using it: offsets and lengths inside the
  file, statuses are `Status` members, damage ranges satisfy
  `0 <= start <= end <= size`, confidence in [0, 1], field names unique
  within a record and never `verified`/`issues`, `issues` and damage kinds
  are `DamageKind` members, `lossy`/`unsupported` are bools. A result that
  breaks these is discarded ("invalid").
- Every Field/Record `offset` and `length` is an **absolute file offset**
  of the source bytes. For values from transformed data (decompressed,
  XOR-ed), point at the source bytes in the file and say so in `evidence`.

## 3. SafeReader

```python
magic = reader.bytes(4, "magic")      # short read at EOF, never raises
count = reader.u16le("count")         # None if truncated
with reader.at(0x40) as ok:           # jump, then come back
    ...
reader.peek(4)                        # look without moving or claiming
```

- Reads return **None when truncated** (fixed-size reads and `unpack`) or a
  **short result** (`bytes`). Always check: `if count is None: ...`.
- **Label every read.** The label names what the bytes are
  (`"header.version"`, `f"record[{i}].crc"`). Labels feed byte coverage in
  report.json: bytes you never read show up as "unexplained".
- **Label padding `"padding"`**, exactly. Padding counts as accounted for,
  not as explained data. Only call bytes padding if they really are
  (e.g. checked zero); otherwise give them a real label.
- Offsets are absolute file offsets: `reader.tell()` gives the current
  one. Record it before reading a field so the `Field` points at the right
  bytes.
- Reading the same bytes twice is fine (coverage counts each byte once).
- `peek` does not claim bytes, so peeking does not count as coverage.

## 4. Statuses: verified / consistent / unverified / lost

Every Field and Record has a `Status`. Pick the weakest one that is true.
The `evidence` string says why; for `verified` it must name the evidence.

| status | when | example | in the output |
|--------|------|---------|---------------|
| `verified` | proven by real evidence: a checksum/CRC match, an exact round trip, an exact magic match | `Field("text", "Hello", 20, 5, Status.VERIFIED, "CRC-16/XMODEM 0x31c3 matches the stored value")` | nothing extra |
| `consistent` | parsed cleanly and agrees with the rest of the file (lengths, counts, ranges, trailer totals), but no checksum proves it | `Field("count", 3, 6, 2, Status.CONSISTENT, "matches the 3 records found")` | nothing extra |
| `unverified` | recovered, but cannot be trusted: it fails a check, or comes from damaged or resynced data | `Field("value", 100, 15, 4, Status.UNVERIFIED, "CRC mismatch")` | `"verified": false` |
| `lost` | the value should exist but cannot be recovered | `Field("value", None, 23, 2, Status.LOST, "file ends inside this field")` | `"verified": false`, value `null` |

- A record gets `"verified": false` in the output if the record or any of
  its fields is `unverified` or `lost`. Any such record (or any damage)
  makes the file `partial`; a clean file must be `ok`.
- **A clean file of a format without checksums is `consistent`, not
  `unverified`.** The expected outputs show no `"verified"` key on any
  record of a clean file, so use `unverified` only for data that is
  actually in doubt.
- A Record's status is usually the worst of its fields:
  `Status.worst(f.status for f in rec.fields)`.
- Never upgrade without evidence: "it looks plausible" is not `verified`.
- Checksums: use `salvagekit.core.checksums` (`crc_preset("CRC-32", data)`,
  `sum16`, `adler32`, ...). `find_checksum(data, target)` brute-forces which
  algorithm and range produce a stored checksum: a research tool, not for
  use in decode.

## 5. Damage

`Damage(start, end, kind, reason, lossy=True)` marks the byte range
`[start, end)` as damaged. In the output it becomes
`{"kind", "offset": start, "detail": reason, "lossy"}`; the full range
stays in the report's diagnostics. `kind` is a `DamageKind`, exactly the
contract's vocabulary:

| kind | use for |
|------|---------|
| `TRUNCATED` | the file ends before the structure does; usually `[where it broke, size)`. Also when it ends cleanly between records but the header promised more |
| `CRC_MISMATCH` | a stored CRC does not match the data it covers |
| `CHECKSUM_MISMATCH` | another stored checksum (sum, xor, Fletcher, Adler) does not match |
| `HEADER_CHECKSUM` | the file or block header's own checksum does not match |
| `BAD_LENGTH` | a length field cannot be right (too large, below the minimum, overlaps the next structure) |
| `COUNT_MISMATCH` | a declared count disagrees with what was found, and nothing else (e.g. truncation) explains it |
| `OOB_POINTER` | an offset/pointer points outside the file or its container |
| `INDEX_MISSING` | an index or directory the format needs is missing or unreadable (entries found by scanning instead) |
| `INVALID_VALUE` | a value is outside its allowed range (a month 13, an unknown enum code) |
| `UNKNOWN_RECORD` | a record of a type you do not know (skipped or kept raw) |
| `UNPARSED_BYTES` | bytes skipped: junk, resync gaps, trailing bytes |
| `ENCRYPTED` | the data is encrypted (see [Unsupported files](#9-unsupported-files)) |

- **`lossy`**: True (the default) when data was lost; False when the data
  was still recovered in full (a CRC mismatch over text you kept, trailing
  bytes after a complete file).
- **`Record.issues`**: the damage kinds that affect a record, e.g.
  `Record(..., issues=[DamageKind.CRC_MISMATCH])`. The output adds
  `"issues": ["crc_mismatch"]` to that record. Use it whenever a damage
  belongs to a particular record.
- **Never invent values.** If a field is cut off, add it with
  `Status.LOST` and `value=None` (preferred: the record keeps every graded
  field, see section 8), or leave the record out and report the damage.
  Never fill in zeros, defaults or guesses.
- Keep everything you decoded before and after the damage.
- One cause, one damage: when truncation explains why fewer records were
  found than declared, report `TRUNCATED` only (the reference answer for
  s04.dat lists only `truncated`).
- Add a matching human-readable line to `result.warnings` when useful.

```python
off = reader.tell()
value = reader.u32le(f"value[{i}]")
if value is None:
    result.damage.append(Damage(off, reader.size, DamageKind.TRUNCATED,
                                f"expected {count} values, file ends after {i}"))
```

## 6. Recovering from damage with resync

When a record is broken, skip to the next place a valid record could start
and carry on. `salvagekit.core.resync` does the scanning:

```python
from salvagekit.core.resync import ByteView, resync, resync_damage

def looks_like_record(view: ByteView, offset: int) -> bool:
    # Be strict: marker + sane length + matching CRC. A weak test "finds"
    # records inside junk.
    if view.bytes(offset, 2) != b"\xA5\x5A":
        return False
    n = view.u16le(offset + 2)
    if n is None or n > 4096:
        return False
    stored = view.u16le(offset + 4 + n)
    return stored == crc16(view.bytes(offset + 4, n))

off = reader.tell()                       # the broken record starts here
hit = resync(reader, looks_like_record, start=off)
damage = resync_damage(hit, "no valid record here; bytes skipped")
if damage is not None:
    result.damage.append(damage)          # UNPARSED_BYTES over [off, hit.offset)
if hit.offset is None:
    ...                                   # nothing found: stop decoding records
# else the reader now sits on the next good record: continue the loop
```

- `resync(reader, is_valid_start, *, start=None, step=1, max_scan=None)`
  tries `start, start+step, ...` (default start: `reader.tell() + 1`) up
  to the end of the file or `MAX_RESYNC_SCAN` (16 MB) bytes. Found: the
  reader is moved there. Not found: the reader does not move.
- Your check gets a `ByteView`: `size`, `u8/u16le/u16be/u32le/u32be(offset)`
  and `bytes(offset, n)`, all returning None (or short bytes) out of range.
  ByteView reads claim nothing, so scanning never inflates coverage. An
  exception in your check counts as False.
- Pass `start=off` (the broken record's offset) so the skipped range starts
  where the damage starts. Use `step` for aligned formats (e.g. `step=4`).
- Make sure the loop always moves forward (resync from `off` only when the
  record at `off` is not valid), or it never ends.
- A strict check also skips a damaged-but-real record that sits inside the
  junk. That is the safe choice: those bytes are reported as
  `UNPARSED_BYTES`.
- The full worked example is the record loop in `docs/decoder-template.py`.

## 7. Archives

For VAULT, WAD and PAK the contract grades **each entry as a record**:
`name`, `offset`, `size`, `sha256` (VAULT: `id`, `name`, `type`, `size`,
`sha256` of the decoded payload, `compressed`, plus `text` or
`width`/`height`). Produce those records yourself.

You may also put a decoded entry in `result.members` as a nested
`DecodeResult` (`name` = its path inside the archive, `/` as separator):

```python
member = DecodeResult(format="VAULT", confidence=1.0, name="DOCS/README.TXT")
result.members.append(member)
```

Members' records are **not** written to the output, but their damage is,
their records count for the file's status, and the report's diagnostics
count them. Member Field/Record/Damage offsets are still **absolute offsets
in the outer file**: point at the member's (compressed) source bytes.

- **Claim the source bytes in the file reader** so coverage stays right:
  read the member's stored data with `reader.bytes(n, f"member[{i}].data")`
  and decode the decompressed copy separately (e.g. with a second
  `SafeReader(decompressed)` for the inner parsing). Reads on that second
  reader do not count for file coverage; the outer `reader.bytes` call does.
- **`MAX_DECOMPRESSED`** (`salvagekit.core.limits`, 256 MB) is the total you
  may decompress per file, all members together. Check it yourself; core
  cannot see decompression. Use `zlib.decompressobj().decompress(data,
  max_length)` so a decompression bomb never allocates more than the limit:

```python
from salvagekit.core.limits import MAX_DECOMPRESSED

budget = MAX_DECOMPRESSED - self.decompressed_so_far
d = zlib.decompressobj()
out = d.decompress(stored, budget + 1)
if len(out) > budget:
    result.damage.append(Damage(start, end, DamageKind.BAD_LENGTH,
                                "decompression limit reached; entry not decoded"))
```

- Core caps the output at `MAX_RECORDS` (1,000,000) records and
  `MAX_MEMBERS` (100,000) members per file, counted over all members. Past
  that it cuts the lists, warns and marks the file `partial`.

## 8. Records and metadata: the contract shapes

The output turns each `Record` into one flat object
`{field.name: field.value}`. So:

- **Field names are the contract's record keys, exactly** (`price_cents`,
  `due_date`, `time_ms`, `cached_value`, ...). One Field per key; no
  duplicates.
- **Values are already in their final form**: ISO dates (`"1998-12-19"`),
  timestamps in the format the contract or expected output shows
  (`"1998-10-03T11:20:22"`, `"1992-10-11T05:07:43Z"`, `"1991-11-19T18:29"`),
  money as integer cents where the contract says `*_cents`, booleans as
  `True`/`False`, strings for codes with leading zeros (`isbn`,
  `student_id`). Never round floats; compute them the way the format does.
- **`null` vs missing**: a field that always applies is always present,
  with `None` when there is no value (`due_date` of a book that is not out)
  or when it was lost (`Status.LOST`). A field that only applies to some
  records is left out where it does not apply (VAULT `text` only for
  `type` text; WKS `alignment` only for labels; formulas have
  `cached_value` and `formula_raw_hex` instead of `value`).
- **`result.meta` is the output's `metadata`**: header values in final
  form. For LABLOG, CVT and EBCDIC-DUMP the contract grades specific keys;
  extra keys are fine (the expected outputs have them).
- No other fields: no offsets, no raw bytes, no evidence in records.

The graded shape of every format (required, conditional and nullable
fields, enum values, graded metadata keys) is in
[`salvagekit/core/contract_shapes.py`](../salvagekit/core/contract_shapes.py)
(`python -m salvagekit.core.contract_shapes` prints it as a table).
Conformance check **C12** checks every record of your clean claimed inputs
against it: every required field present, no field outside the list (plus
`verified`/`issues`), enum values allowed, null only where allowed (or in a
record marked `"verified": false`), and the graded metadata keys present.

## 9. Unsupported files

If you recognize the file but cannot decode it (password-protected,
encrypted), return a result with `unsupported=True`. Core stops trying
other candidates and the file's status is `unsupported`. Records may be
empty; keep whatever metadata you could read, and add an `ENCRYPTED`
damage over the encrypted bytes when that is the reason:

```python
return DecodeResult(format=self.name, confidence=1.0, unsupported=True,
                    meta={"version": version},
                    damage=[Damage(data_start, reader.size, DamageKind.ENCRYPTED,
                                   "document is password-protected")])
```

## 10. variant and confidence

Both appear only in the report's diagnostics.

- **variant:** set `result.format` to a sub-version string when you can
  tell, e.g. `"WPD 5.1"`. If it differs from your decoder `name` it is the
  entry's `variant`; the output's `format` is always your decoder `name`.
- **confidence:** `result.confidence` is how sure you are, AFTER decoding,
  that the file really is this format (0.0-1.0). Example: magic only →
  0.6; at least one checksum-verified record → 1.0. It is not a measure of
  how much was recovered (coverage and damage say that).

## 11. Running your decoder alone

End your module with:

```python
from salvagekit.core.standalone import run_standalone

if __name__ == "__main__":
    run_standalone(Libra98Decoder)
```

Then, from the repository root:

```sh
python -m salvagekit.formats.libra98 kit/samples/s01.dat
```

It prints your `DecodeResult` as JSON (errors go to stderr). For the real
per-file output run `./salvage IN OUT` (or `python tools/task.py run IN
OUT`) on a folder and read `OUT/<file>.json` and `OUT/report.json`.

## 12. Golden tests

A golden case is an input file plus the exact output expected for it.

1. Put the input in `tests/<module>/cases/` (any file name; small files,
   preferably made by you rather than copied from `kit/samples/`).
2. Generate expectations: `python tools/task.py golden-update <module>`.
   This only ever touches `tests/<module>/cases/`. Use it only for **your**
   format.
3. **Check every new or changed `*.expected.json` by hand** against the
   input bytes before committing it. Never update an expectation just to
   make a test pass.
4. Run them: `python tools/task.py golden <module>`.

Good cases: one clean file, one truncated file, one with a bad checksum,
one with junk in the middle (resync), one wrong-format file.

## 13. Calibrating against the expected outputs

`kit/expected_outputs/` holds the organizers' reference answers for seven
samples (s01, s04, s05, s08, s11, s18, s20). Compare your output with them:

```sh
python tools/task.py calibrate            # all seven
python tools/task.py calibrate s01.dat    # one
```

Per file it prints `MATCH` or the number of differences and up to 30
JSON paths (`records[id=1009].due_date: expected "1998-12-19", got null`),
then `calibrate: N/7 files match`. Records are matched on the answer key's
`match_on` field, `optional_partial_records` may be present or not, and
damage is matched by kind (`any_of`) and `lossy`; see `tools/calibrate.py`.
It is a dev tool, not part of `test`.

## 14. Format spec and FIELD-LOG entries

Both files are merged by `python tools/task.py docs` into `FORMAT-SPEC.md`
and `FIELD-LOG.md` at the repository root (the hackathon deliverables).
Never edit those two files by hand; edit yours and run `docs`. Files whose
names start with `_` are templates and are never merged.

**Spec.** Copy [`docs/spec/_TEMPLATE.md`](spec/_TEMPLATE.md) to
`docs/spec/<module>.md`. The first line is `# <decoder name>` (exactly your
decoder's `name`, e.g. `# LIBRA-98`), followed by the eight `##` sections
in the template's order: Summary, Identification, Layout (the
`Offset | Size | Type | Endian | Field | Meaning | Evidence` table),
Records, Checksums, Compression and obfuscation, Damage handling, Open
questions. Write "None" rather than deleting a section: `docs` warns about
missing sections and a wrong first heading.

**Log.** Copy [`docs/log/_TEMPLATE.md`](log/_TEMPLATE.md) to
`docs/log/<module>.md` and add an entry for every hypothesis, **including
the ones that failed**: they stop others from trying the same thing.
Times are local time (IST).

```markdown
### 2026-10-16 14:05 — Record length is u16 big-endian?

**Hypothesis:** bytes 2-3 of each record are its length, u16 big-endian.

**Tried:** read them as u16be in `kit/samples/s01.dat` and jumped that far.

**Evidence:** the jump lands exactly on the next `A5 5A` marker 41/41
times; read as u16le it never does.

**Result:** CONFIRMED. The length excludes the 4-byte record header.
```

- Heading: `### YYYY-MM-DD HH:MM — <title>` (an em dash). A heading whose
  date or time is not valid makes `docs` fail, naming `file:line`.
- `**Result:**` is `CONFIRMED`, `REJECTED` or `INCONCLUSIVE`, optionally
  followed by an explanation; anything else (or no Result line) is a
  warning. `FIELD-LOG.md` counts them per format.
- Never rewrite an old entry; add a new one that corrects it.

## 15. Before opening a pull request

```sh
python tools/task.py conform <your module>   # must PASS
python tools/task.py test                    # must PASS
python tools/task.py calibrate               # your expected outputs should MATCH
```

`conform` runs the decoder conformance suite on your decoder: contract
name, crashes, hangs, invalid results, `verified` without evidence, round
trip, determinism, forbidden imports/calls, speed, golden cases, docs and
record shape (C12). Every check, its typical failure message and how to fix
it are in [`docs/conformance.md`](conformance.md); add `--verbose` to see
every finding. `test` runs all tests, including golden tests, schema
validation of pipeline output, the samples run and the conformance suite
for every decoder.

Also check:

- every read is labelled, and padding is labelled `"padding"`;
- nothing is `verified` without evidence named in `evidence`;
- field names and values match the contract shape (section 8);
- `docs/spec/<module>.md` and `docs/log/<module>.md` are up to date;
- you changed nothing outside your own files.
