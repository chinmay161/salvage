# Decoder guide

Read this instead of the core code. It covers everything a format decoder
needs. A complete, tested decoder to copy from is
[`docs/decoder-template.py`](decoder-template.py) (made-up format
"EXAMPLE"). The output shape is described in
[`docs/output-format.md`](output-format.md).

Contents:

1. [Where your files go](#1-where-your-files-go)
2. [The Decoder class](#2-the-decoder-class)
3. [SafeReader](#3-safereader)
4. [Statuses](#4-statuses-verified--consistent--unverified--lost)
5. [Damage](#5-damage)
6. [Recovering from damage with resync](#6-recovering-from-damage-with-resync)
7. [Archives](#7-archives)
8. [variant and confidence](#8-variant-and-confidence)
9. [Running your decoder alone](#9-running-your-decoder-alone)
10. [Golden tests](#10-golden-tests)
11. [Format spec and FIELD-LOG entries](#11-format-spec-and-field-log-entries)
12. [Before opening a pull request](#12-before-opening-a-pull-request)

## 1. Where your files go

For a format called `<name>` (lowercase, e.g. `libra98`):

| what | where |
|------|-------|
| the decoder | `salvage/formats/<name>.py` |
| golden test cases | `tests/<name>/cases/` |
| other tests | `tests/<name>/test_*.py` (add an empty `tests/<name>/__init__.py`) |
| what you found out about the format | `docs/spec/<name>.md`, copied from [`docs/spec/_TEMPLATE.md`](spec/_TEMPLATE.md) (section 11) |
| your research log | `docs/log/<name>.md`, copied from [`docs/log/_TEMPLATE.md`](log/_TEMPLATE.md) (section 11) |

Do not edit, without asking the lead: `salvage/core/`, `salvage/cli.py`,
`salvage/formats/stub.py`, `tests/core/`, `tests/fixtures/`, `tools/`,
`Dockerfile`, `Makefile`, `README.md`, `CLAUDE.md`. Never edit `samples/`
or `schema/`. Never edit another teammate's format files.

Hard rules: Python 3.12, standard library only, no network. Decoder files
must not start with `_` (those are skipped by discovery).

## 2. The Decoder class

```python
from salvage.core.plugin import Decoder

class Libra98Decoder(Decoder):
    name = "LIBRA-98"            # unique; becomes "format" in the output
    extensions = (".lb9",)       # weak hint only: breaks ties, never decides

    def probe(self, data: bytes) -> float: ...
    def decode(self, reader: SafeReader) -> DecodeResult: ...
    def encode(self, result: DecodeResult) -> bytes: ...   # optional
```

- **`probe(data)`** gets the whole file as bytes and returns 0.0-1.0: how
  sure you are the file is yours. Look at magic bytes and header sanity.
  Decoders scoring at least 0.5 are tried, best first. Keep it fast (every
  probe runs on every file).
- **`decode(reader)`** reads the file only through the given `SafeReader`
  and returns a `DecodeResult` (from `salvage.core.model`): `records` (each
  a `Record` holding `Field`s), `damage`, `meta` (any JSON-safe dict),
  `warnings`, `members` (archives). Return the best partial result you can.
  A result with no records and no members counts as "empty": core then tries
  the next candidate.
- **`encode(result)`** is optional. Implement it if you can rebuild the
  exact bytes; that makes round-trip evidence possible.
- **`probe` and `decode` NEVER raise.** Wrap risky code. A raise, a hang
  (20 s limit) or a crash makes the file `failed`, and your output is lost.
  Core survives it, but your decode does not count.
- Core checks your result before using it: offsets and lengths must lie
  inside the file, statuses must be `Status` members, damage ranges must
  satisfy `0 <= start <= end <= size`, confidence must be in [0, 1].
  A result that breaks these is discarded ("invalid").
- Values must be JSON-safe: `None`, bool, int, finite float, str, lists,
  dicts with str keys. Bytes become hex automatically; prefer giving
  decoded text or numbers.
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

| status | when | example |
|--------|------|---------|
| `verified` | proven by real evidence: a checksum/CRC match, an exact round trip, an exact magic match | `Field("text", "Hello", 20, 5, Status.VERIFIED, "CRC-16/XMODEM 0x31c3 matches the stored value")` |
| `consistent` | agrees with something else in the file, but nothing proves it | `Field("count", 3, 6, 2, Status.CONSISTENT, "matches the 3 records found")` |
| `unverified` | read as-is, nothing to check it against (the default) | `Field("value", 100, 15, 4, Status.UNVERIFIED, "no checksum in format")` |
| `lost` | the value should exist but cannot be recovered | `Field("value", None, 23, 2, Status.LOST, "file ends inside this field")` |

- A Record's status is usually the worst of its fields:
  `Status.worst(f.status for f in rec.fields)`.
- Never upgrade without evidence: "it looks plausible" is `unverified`.
- Anything `lost` (or any damage) makes the file `partial`.
- Checksums: use `salvage.core.checksums` (`crc_preset("CRC-32", data)`,
  `sum16`, `adler32`, ...). `find_checksum(data, target)` brute-forces which
  algorithm and range produce a stored checksum: a research tool, not for
  use in decode.

## 5. Damage

`Damage(start, end, kind, reason)` marks the byte range `[start, end)` as
damaged. Kinds (`DamageKind`):

| kind | use for |
|------|---------|
| `TRUNCATED` | the file ends early; usually `[where it broke, size)` |
| `CHECKSUM` | a checksum does not match; the range it covers |
| `BOUNDS` | a length/offset points outside the file or its container |
| `UNPARSED` | bytes skipped (junk, unknown blocks, resync gaps) |
| `OTHER` | anything else; explain in `reason` |

- **Never invent values.** If a field is cut off, either leave it out and
  report the damage, or add it with `Status.LOST` and `value=None`. Never
  fill in zeros, defaults or guesses.
- Keep everything you decoded before and after the damage.
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
and carry on. `salvage.core.resync` does the scanning:

```python
from salvage.core.resync import ByteView, resync, resync_damage

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
    result.damage.append(damage)          # UNPARSED over [off, hit.offset)
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
  junk. That is the safe choice: those bytes are reported as `UNPARSED`.
- The full worked example is the record loop in `docs/decoder-template.py`.

## 7. Archives

For container formats, each entry is a nested `DecodeResult` in
`result.members`:

```python
member = DecodeResult(format="LIBRA-98", confidence=1.0, name="DOCS/README.TXT")
result.members.append(member)
```

- `name` is the member's path inside the archive, as stored (use `/` as
  the separator if the format has folders).
- Member Field/Record offsets are still **absolute offsets in the outer
  file**: point at the member's (compressed) source bytes.
- **Claim the source bytes in the file reader** so coverage stays right:
  read the member's stored data with `reader.bytes(n, f"member[{i}].data")`
  and decode the decompressed copy separately (e.g. with a second
  `SafeReader(decompressed)` for the inner parsing). Reads on that second
  reader do not count for file coverage; the outer `reader.bytes` call does.
- **`MAX_DECOMPRESSED`** (`salvage.core.limits`, 256 MB) is the total you may
  decompress per file, all members together. Check it yourself; core cannot
  see decompression. Use `zlib.decompressobj().decompress(data, max_length)`
  so a decompression bomb never allocates more than the limit:

```python
from salvage.core.limits import MAX_DECOMPRESSED

budget = MAX_DECOMPRESSED - self.decompressed_so_far
d = zlib.decompressobj()
out = d.decompress(stored, budget + 1)
if len(out) > budget:
    result.damage.append(Damage(start, end, DamageKind.OTHER,
                                "decompression limit reached; member not decoded"))
```

- Core caps the output at `MAX_RECORDS` (1,000,000) records and
  `MAX_MEMBERS` (100,000) members per file, counted over all members. Past
  that it cuts the lists, warns and marks the file `partial`. You do not need
  to check these, but stop early if you know you are past them.

## 8. variant and confidence

- **variant:** set `result.format` to a sub-version string when you can
  tell, e.g. `"WPD 5.1"`. If it differs from your decoder `name` it appears
  as `"variant"` in the output; leave `result.format = self.name` when there
  is no sub-version (`"variant": null`).
- **confidence:** `result.confidence` is how sure you are, AFTER decoding,
  that the file really is this format (0.0-1.0). For `decoded`/`partial`
  files it is the `confidence` written to the output (your probe score is
  kept separately as `probe_score` in report.json). Example: magic only →
  0.6; at least one checksum-verified record → 1.0. It is not a measure of
  how much was recovered (coverage and damage say that).

## 9. Running your decoder alone

End your module with:

```python
from salvage.core.standalone import run_standalone

if __name__ == "__main__":
    run_standalone(Libra98Decoder)
```

Then, from the repository root:

```sh
python -m salvage.formats.libra98 samples/some-file.lb9
```

It prints your `DecodeResult` as JSON (errors go to stderr). For the full
pipeline output (identification, status, coverage, validation) run
`python tools/task.py run IN OUT` on a folder and read `OUT/report.json`.

## 10. Golden tests

A golden case is an input file plus the exact output expected for it.

1. Put the input in `tests/<name>/cases/` (any file name; small files,
   preferably made by you rather than copied from `samples/`).
2. Generate expectations: `python tools/task.py golden-update <name>`. This
   only ever touches `tests/<name>/cases/`. Use it only for **your** format.
3. **Check every new or changed `*.expected.json` by hand** against the
   input bytes before committing it. Never update an expectation just to
   make a test pass.
4. Run them: `python tools/task.py golden <name>`.

Good cases: one clean file, one truncated file, one with a bad checksum,
one with junk in the middle (resync), one wrong-format file.

## 11. Format spec and FIELD-LOG entries

Both files are merged by `python tools/task.py docs` into `FORMAT-SPEC.md`
and `FIELD-LOG.md` at the repository root (the hackathon deliverables).
Never edit those two files by hand; edit yours and run `docs`. Files whose
names start with `_` are templates and are never merged.

**Spec.** Copy [`docs/spec/_TEMPLATE.md`](spec/_TEMPLATE.md) to
`docs/spec/<name>.md`. The first line is `# <decoder name>` (exactly your
decoder's `name`, e.g. `# LIBRA-98`), followed by the eight `##` sections
in the template's order: Summary, Identification, Layout (the
`Offset | Size | Type | Endian | Field | Meaning | Evidence` table),
Records, Checksums, Compression and obfuscation, Damage handling, Open
questions. Write "None" rather than deleting a section: `docs` warns about
missing sections and a wrong first heading.

**Log.** Copy [`docs/log/_TEMPLATE.md`](log/_TEMPLATE.md) to
`docs/log/<name>.md` and add an entry for every hypothesis, **including
the ones that failed**: they stop others from trying the same thing.
Times are local time (IST).

```markdown
### 2026-10-16 14:05 — Record length is u16 big-endian?

**Hypothesis:** bytes 2-3 of each record are its length, u16 big-endian.

**Tried:** read them as u16be in `samples/libra98/a.lb9` and jumped that far.

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

## 12. Before opening a pull request

```sh
python tools/task.py conform <your format>   # must PASS
python tools/task.py test                    # must PASS
```

`conform` runs the decoder conformance suite on your decoder: crashes,
hangs, invalid results, `verified` without evidence, round trip,
determinism, forbidden imports/calls, speed, golden cases and docs. Every
check, its typical failure message and how to fix it are in
[`docs/conformance.md`](conformance.md); add `--verbose` to see every
finding. `test` runs all tests, including golden tests, schema validation
of pipeline output and the conformance suite for every decoder.

Also check:

- every read is labelled, and padding is labelled `"padding"`;
- nothing is `verified` without evidence named in `evidence`;
- `docs/spec/<name>.md` and `docs/log/<name>.md` are up to date;
- you changed nothing outside your own files.
