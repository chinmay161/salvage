# Decoder conformance suite

```sh
python tools/task.py conform <your format>            # one decoder, e.g. "conform libra98"
python tools/task.py conform <your format> --verbose  # every finding
python tools/task.py conform                          # all decoders
python tools/task.py conform --quick                  # the merge gate's smaller run
```

Every decoder in `salvagekit/formats/` is checked automatically against the
contract in [decoder-guide.md](decoder-guide.md). It **must PASS before you
open a pull request**. `python tools/task.py test` runs it too (the merge
gate, in quick mode: see below), so a failing decoder breaks the build.

Output, one line per decoder:

```
PASS  STUB      2 inputs, 82 variants, 0 warnings
FAIL  LIBRA-98  C5 honesty: field "id" @0x40 verified but bytes changed (bitflip@66.2 of kit/samples/s01.dat)
                (+3 more findings; --verbose lists them)
```

`inputs` are the files your probe claims (score >= 0.5); `variants` are the
damaged copies of them that were decoded. FAIL findings fail the decoder;
WARN findings do not, but read them. The exit code is 1 if any decoder
FAILs. The last line says which mode ran:
`conform (full mode): 1 PASS, 0 FAIL in 0.4 s`.

## What the suite feeds your decoder

- **Corpus:** every file under `kit/samples/` and every input in
  `tests/*/cases/`. Your **claimed inputs** are the corpus files your probe
  scores at least 0.5. Your module name (`libra98` for
  `salvagekit/formats/libra98.py`) names your folders:
  `tests/libra98/cases/`, `docs/spec/libra98.md`, `docs/log/libra98.md`.
- **Synthetic inputs:** empty, one zero byte, 64 KB of 0x00, 64 KB of
  0xFF, 64 KB of random bytes.
- **Variants** of each claimed input: 16 truncations, 20 single-bit
  flips, 3 blocks of 64 zero bytes, 3 blocks of 16 random bytes, and
  100 random bytes appended (fewer truncations and flips for files over
  1 MB). Names say what was done: `truncate@37` (file cut to 37 bytes),
  `bitflip@1204.3` (bit 3 of byte 1204), `zero@512`, `overwrite@40`,
  `append@57`. All randomness is seeded from the input bytes and your
  decoder name, so a failure reproduces exactly on every run and machine.

**Quick mode** (`conform --quick`, and the merge gate in `task.py test`)
keeps the test suite fast as `kit/samples/` grows. Every check still runs,
with the same IDs and messages, but:

- the corpus is the golden case inputs plus the synthetic inputs
  (`kit/samples/` is not read);
- each claimed input gets 8 truncations, 8 bit flips, 2 zero blocks
  (start and middle), 2 random blocks and 1 append;
- C7 decodes only the first claimed input (that decoded cleanly).

`conform` without `--quick` is the full run. Run it before a pull request.

To reproduce a variant by hand, build it in a Python shell and decode it:

```python
from tests.conformance import variants
from salvagekit.core.reader import SafeReader
from salvagekit.formats.libra98 import Libra98Decoder
data = open("kit/samples/s01.dat", "rb").read()
v = next(v for v in variants(data, "LIBRA-98") if v.name == "bitflip@66.2")
print(Libra98Decoder().decode(SafeReader(v.data)).to_dict())
```

Your decoder runs in a separate worker process. A hang or crash ends the
checks for your decoder, never the suite. Each variant gets 5 seconds and
the clean decode of each claimed input gets 5 seconds; after a timeout or
crash the remaining checks are skipped.

---

## C1 metadata (FAIL)

**Checks:** `name` is non-empty, at most 32 characters, only uppercase
letters, digits, space and `. - _`, and, in `salvagekit/formats/`, one of
the contract's format names: `LIBRA-98`, `LABLOG`, `VAULT`, `WKS`, `WPD`,
`BRAVO`, `CVT`, `EBCDIC-DUMP`, `WAD`, `PAK` (the test-only `STUB` keeps
its name; fixture packages are exempt). `extensions` is a tuple of
lowercase strings starting with `.`. Also reported here: your module
cannot be imported, the decoder cannot be created, or two decoders share a
name.

**Why:** the name is the `format` in every output; the graders expect the
contract's names exactly. Extensions break ties between candidates.

**Typical failures:**
- `C1 metadata: name 'Libra98' may only use uppercase letters, digits, space and . - _`
- `C1 metadata: name 'LIBRA98' is not a contract format name (one of LIBRA-98, LABLOG, ...); it is the output's "format"`

**Fix:** `name = "LIBRA-98"`, `extensions = (".dat",)` (a tuple, so note
the comma for a single entry).

## C2 probe safety (FAIL)

**Checks:** `probe()` is called directly (not through core's safety net) on
every synthetic input and every corpus file, twice. It must not raise, and
must return an `int` or `float` (not `bool`) that is finite and within
[0, 1], the same value both times. `probe()` on 8 MB of random bytes must
take at most 0.5 s.

**Why:** every probe runs on every input file. A raising, hanging or slow
probe slows down or breaks identification for all formats.

**Typical failures:**
- `C2 probe safety: probe raised struct.error: unpack_from requires a buffer of at least 4 bytes (at salvagekit/formats/libra98.py:41 in probe) (<1 zero byte>)`
- `C2 probe safety: probe on 8 MB of random bytes took 1.25 s, and 1.22 s when re-measured alone (limit 0.5 s): look at the header, do not scan the whole file`

**Timing is measured twice before it fails.** Up to 4 decoders are
checked at once, so a busy machine can slow one down. If a probe (C2) or a
clean decode (C9) is over its limit, the suite times it again in the same
worker after every other decoder has finished, with nothing else running.
It FAILs only if the re-measure is over the limit too; the message shows
both timings. A pass on the re-measure is a WARN that shows both (for
example a one-time warm-up such as building a lookup table on first use).

**Fix:** wrap the probe body in `try: ... except Exception: return 0.0`,
check `len(data)` before unpacking, look only at the first few hundred
bytes, return a plain float.

## C3 probe precision (FAIL)

**Checks:** your probe scores below 0.5 on every synthetic input and on
every golden case input of **another** decoder (`tests/<their
module>/cases/`). Samples whose format is not known are not used.

**Why:** a probe that claims foreign files makes core try your decoder on
them. That gives wrong formats, "ambiguous" warnings and wasted time.

**Typical failure:** `C3 probe precision: probe gives 0.6 to a golden case of STUB (must be < 0.5) (tests/stub/cases/clean.stub)`

**Fix:** require your exact magic bytes and plausible header values before
returning >= 0.5. An extension or "it's binary" is no evidence.

## C4 decode safety (FAIL)

**Checks:** for every claimed input, every variant and every synthetic
input, `decode(SafeReader(data))` is called directly and:
- must not raise (the message gives the exception and its last traceback line);
- must return a `DecodeResult`;
- `result.validate(len(data))` must be empty (offsets/lengths inside the
  file, statuses are `Status` members, damage ranges valid, confidence in [0, 1]);
- `json.dumps(result.to_dict(), allow_nan=False)` must work;
- the full per-file output, built exactly as the pipeline builds it, must
  pass the official output schema (`salvagekit/core/schemas/official/`),
  including its status rules (an `ok` file has no damage and no
  `"verified": false` record);
- it must finish within the time limit (`timed out on <variant>`), without
  crashing the worker process.

**Why:** a decoder that raises, hangs or returns an invalid result on a
damaged file loses the whole file in the real run. Damaged files are the
point of this project.

**Typical failures:**
- `C4 decode safety: decode raised IndexError: index out of range (at salvagekit/formats/libra98.py:88 in decode) (truncate@7 of tests/libra98/cases/clean.lb9)`
- `C4 decode safety: result.validate() reports: records[2].fields[0]: offset+length 40 beyond file size 29 (truncate@29 of ...)`
- `C4 decode safety: timed out on append@57 (limit 5 s); remaining checks skipped (append@57 of ...)`

**Fix:** read only through `SafeReader` and check every `None` and short
read. Never index into bytes without checking the length. Clamp lengths
taken from the file to `reader.size` and report the rest as `Damage`. Make
every loop move forward (see "resync" in the decoder guide).

## C5 honesty (FAIL, two WARNs)

**Checks:** each variant's result is compared with the clean input's
result. Fields are matched by (field name, offset), in records and in
archive members.
- FAIL: a `verified` field whose bytes `[offset, offset+length)` include
  a changed byte. Damaged bytes cannot be verified.
- FAIL: a `verified` field with the same name and offset as a clean field
  but a different value.
- WARN: a variant has more verified fields than the clean file.
- WARN: a truncated variant returns records but reports no damage and
  nothing `lost` ("truncation not reported").

**Why:** `verified` is a promise that the value is proven (checksum, round
trip, exact magic). If damage cannot change a verified value's status,
the promise means nothing.

**Typical failure:** `C5 honesty: field "id" @0x40 verified but bytes changed (bitflip@66.2 of kit/samples/s01.dat)`

**Fix:** mark a field `verified` only when a checksum (or exact magic, or
round trip) covers exactly those bytes and matched. Make the field's
`offset`/`length` cover the bytes the evidence covers. When the file ends
early, add a `TRUNCATED` damage (also when it ends cleanly between
records but the header promised more).

## C6 round trip (FAIL, only if you implement `encode()`)

**Checks:** `encode(decode(clean))` equals the clean file byte for byte,
for every claimed input that your decoder decodes as undamaged (no damage,
nothing `lost`). Inputs you report as damaged are skipped, and so are
empty results (no records, no members: "not my format"). `encode()`
raising is a FAIL.

**Why:** round-trip evidence is only worth something if the round trip is exact.

**Typical failure:** `C6 round trip: encode(decode(file)) differs from the file at offset 56 (0x38): file has 0x96, encode gave end of data (lengths 57 vs 56) (tests/libra98/cases/clean.lb9)`

**Fix:** look at the named offset in the file and in `encode()`'s output.
Usually a padding field, a length or a checksum is rebuilt wrongly or left
out. Keep what `encode()` needs (version, flags, padding) in `meta` or in fields.

## C7 determinism (FAIL)

**Checks:** each clean claimed input is decoded in two fresh Python
processes started with `PYTHONHASHSEED=1` and `PYTHONHASHSEED=2`. The JSON of
`to_dict()` (keys sorted) must be identical.

**Why:** output must be byte-identical on every run and machine. Set and
dict ordering of strings changes with the hash seed. Randomness and the
clock change every run.

**Typical failure:** `C7 determinism: to_dict() differs between PYTHONHASHSEED=1 and 2: meta.tags[0]: seed 1 gave "theta", seed 2 gave "gamma" (tests/libra98/cases/clean.lb9)`

**Fix:** never iterate a `set` (or `frozenset`) to build output. Use
`sorted(...)` or a list. Do not use `random`, `time`, `id()` or `hash()`.

## C8 static rules (FAIL)

**Checks:** your module's source (and the private helper modules it
imports) is parsed with `ast`, without running it:
- imports allowed: the standard library, `salvagekit.core` and its
  submodules, and private helpers `salvagekit.formats._*` (not other
  decoders' modules, not third-party packages);
- imports forbidden: `socket ssl http urllib ftplib smtplib subprocess
  multiprocessing threading asyncio ctypes os shutil pathlib tempfile glob
  random secrets time uuid locale`;
- calls forbidden: `open eval exec compile __import__ input hash id
  breakpoint`, and the attributes `.now`, `.today`, `.utcnow`;
- `fromtimestamp(...)` must be given a time zone (second argument or `tz=`).

Everything under `if __name__ == "__main__":` is exempt (that is where
`run_standalone` lives). Each violation gives the file, line and rule.

**Why:** no network, no file access outside `SafeReader`, no hidden
nondeterminism (time, randomness, local time zone, memory addresses).

**Typical failure:** `C8 static rules: salvagekit/formats/libra98.py:12: forbidden import os`

**Fix:** remove the import or call. `os.path` work is not needed (you get
bytes). For timestamps use
`datetime.fromtimestamp(t, tz=timezone.utc)`. `re.compile` is fine (only
the builtin `compile()` is forbidden).

## C9 speed (FAIL)

**Checks:** decoding each clean claimed input takes at most 2 s (measured
in the worker; over the limit, it is re-measured alone before it fails,
see C2).

**Why:** the real run has a hard per-file limit, and the test suite has to
stay fast.

**Typical failure:** `C9 speed: decode took 3.00 s, and 3.01 s when re-measured alone (limit 2 s) (tests/libra98/cases/clean.lb9)`

**Fix:** avoid per-byte Python loops over whole files where a slice,
`bytes.find`, `struct.iter_unpack` or `zlib` does the job. Do not re-read or
re-decode the same data. Keep resync checks cheap.

## C10 tests (FAIL)

**Checks:** `tests/<module>/cases/` exists and holds at least one input with
a matching `.expected.json`, and your probe claims at least one corpus
file.

**Why:** golden cases are how the team notices when your output changes,
and they are part of the corpus the other checks run on.

**Typical failure:** `C10 tests: no golden cases: create tests/libra98/cases/ with at least one input file, then run `python tools/task.py golden-update libra98` and check every .expected.json by hand (docs/decoder-guide.md section 12)`

**Fix:** follow the message. Small hand-made inputs are best: one clean,
one truncated, one with a bad checksum.

## C11 docs (WARN)

**Checks:** `docs/spec/<module>.md` and `docs/log/<module>.md` exist, and
the log has at least one entry heading `### YYYY-MM-DD HH:MM — <title>`.

**Why:** the next person to touch your format needs what you found out, and
what did not work.

**Typical failure:** `C11 docs: docs/log/libra98.md is missing: keep a research log (docs/decoder-guide.md section 14)`

**Fix:** copy `docs/spec/_TEMPLATE.md` and `docs/log/_TEMPLATE.md` to
`docs/spec/<module>.md` and `docs/log/<module>.md` and fill them in
(decoder guide section 14).

## C12 record shape (FAIL)

**Checks:** only for a decoder whose `name` is a contract format. Each
clean claimed input is run through the pipeline exactly as in a real run,
and every record of the per-file output is checked against that format's
shape in `salvagekit/core/contract_shapes.py`:
- every required graded field is present (a conditional one, such as VAULT
  `text` or WKS `alignment`, only where it applies);
- no field outside the format's list, apart from `verified` and `issues`;
- enum fields (VAULT/WKS/WPD `type`, WKS `alignment`) use allowed values;
- `null` only in a nullable field (LIBRA-98 `due_date`, WPD `text`) or in
  a record marked `"verified": false` (a lost value);
- for LABLOG, CVT and EBCDIC-DUMP, every graded `metadata` key is present
  (CVT `structure` is `seq` or `vlir`); extra metadata keys are fine.

Each distinct problem is reported once, with the first record that has it
and how many more do.

**Why:** the graders compare records field by field with the contract's
names; a misspelled or missing field scores nothing, however good the
decoding.

**Typical failure:** `C12 record shape: records[0]: missing graded field 'price_cents' (and 4 more records) (kit/samples/s01.dat)`

**Fix:** name each `Field` exactly as the contract does and give every
record all of its format's fields (`None` with `Status.LOST` when lost);
see [decoder-guide.md section 8](decoder-guide.md#8-records-and-metadata-the-contract-shapes).
Header values belong in `result.meta`, not in a record.

---

For Core: the engine is `tests/conformance.py`. Its self-tests
(`tests/core/test_conformance_selftest.py`) run one deliberately broken
decoder per check from `tests/fixtures/conform_formats/`.
`tests/core/test_conformance.py` runs the suite on the real package, in
quick mode (`run_conformance(quick=True)`).
