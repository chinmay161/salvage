# Phase 4 report: decoder conformance suite

**Status:** done. Every "done when" check passed:

- `python tools/task.py conform`: STUB PASS.
- Every self-test fixture fails with its expected check ID, and "ok" passes with zero findings.
- `python tools/task.py test`: 243 tests pass on Windows (2 skipped).
- `docker-test`: 243 tests pass inside the image.
- The full suite takes 30.8 s on Windows. The limit is 90 s.

The contract files `model.py`, `plugin.py` and `reader.py` are unchanged. No files in `salvage/` changed.

## 1. Files created or changed

**New**
- `tests/conformance.py`: the engine (`run_conformance`, `DecoderReport`, `Finding`, `variants`, `static_problems`, `format_lines`) and the runner (`python -m tests.conformance`).
- `tests/core/test_conformance.py` (C-3): the merge gate. It runs the suite on the real package.
- `tests/core/test_conformance_selftest.py` (C-2): one test per fixture, plus unit tests for variants, C8 rules and discovery errors.
- `tests/fixtures/conform_formats/`: the self-test fixtures.
  - `_base.py`: the shared well-behaved CRC format.
  - `_make_cases.py`: regenerates the fixture golden cases.
  - Fixture decoders: `ok`, `greedyprobe`, `slowprobe`, `raisetrunc`, `badoffset`, `hang`, `crash`, `liar`, `badtrip`, `nondet`, `forbidden`, `slow`, `nocases`.
- `tests/fixtures/conform_cases/<module>/cases/`: one clean case plus its `.expected.json` per fixture (none for `nocases`).
- `tests/fixtures/conform_docs/{spec,log}/ok.md`: so "ok" has no C11 warnings.
- `docs/conformance.md` (D1).
- `docs/spec/stub.md` and `docs/log/stub.md`, so STUB passes C11 (task C-3).
- `docs/phase-reports/phase-4.md`: this file.

**Changed**
- `tools/task.py`: new `conform [NAME] [--verbose] [...]` command, plus its usage text.
- `Makefile`: new `make conform [NAME=...] [ARGS=--verbose]`.
- `docs/decoder-guide.md`: section 12 rewritten (D2).
- `CLAUDE.md`: adds the conform command (D3).

## 2. `python tools/task.py conform` (real package)

```
PASS  STUB  2 inputs, 82 variants, 0 warnings
conform: 1 PASS, 0 FAIL in 0.5 s
```

## 3. Self-test matrix

Run with `variant_timeout=2.0`. "Produced" lists every check ID found.

| fixture | expected | produced |
|---|---|---|
| ok | PASS, no FAIL | PASS, **no findings at all** |
| greedyprobe | C3 | C3 FAIL, C11 WARN |
| slowprobe | C2 | C2 FAIL (1.36 s on 8 MB), C11 WARN |
| raisetrunc | C4 | C4 FAIL (`IndexError ... raisetrunc.py:14 in decode`, truncate@7), C11 WARN |
| badoffset | C4 | C4 FAIL (`offset+length ... beyond file size`), C11 WARN |
| hang | C4 timeout | C4 FAIL (`timed out on append@57 (limit 2 s)`), C11 WARN |
| crash *(extra)* | C4 crash | C4 FAIL (`worker crashed ... exit code 3`), C8 FAIL (`import os`), C11 WARN |
| liar | C5 | C5 FAIL, C11 WARN |
| badtrip | C6 | C6 FAIL (offset 56, `encode gave end of data`), C11 WARN |
| nondet | C7 | C7 FAIL (`meta.tags[0]: seed 1 gave "theta", seed 2 gave "gamma"`), C11 WARN |
| forbidden | C8 (3 findings) | C8 FAIL ×3 (lines 3, 16, 20; the `open()` under `__main__` on line 24 is exempt), C11 WARN |
| slow | C9 | C9 FAIL (3.00 s), C8 FAIL (`import time`), C11 WARN |
| nocases | C10 | C10 FAIL ×2 (no cases folder; claims no input), C11 WARN ×2 |

C11 fires on every fixture except "ok" because only "ok" has fixture docs. The tests assert it for `nocases`.

## 4. `--verbose` output for "liar" and "forbidden"

Both runs used these options:
`python tools/task.py conform <name> --verbose --package tests.fixtures.conform_formats --cases-root tests/fixtures/conform_cases --samples-root tests/fixtures/__none__ --docs-root tests/fixtures/conform_docs --timeout 2`

```
FAIL  CF-LIAR  1 inputs, 41 variants, 2 warnings
      FAIL  C5 honesty: field "text" @0xe verified but bytes changed (bitflip@16.3 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@28.1 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@32.6 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@33.0 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@33.1 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@33.4 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@35.4 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@36.5 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x1b verified but bytes changed (bitflip@38.4 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x30 verified but bytes changed (bitflip@51.3 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "text" @0x30 verified but bytes changed (bitflip@51.4 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      FAIL  C5 honesty: field "blob" @0x1b verified but bytes changed (overwrite@32 of tests/fixtures/conform_cases/liar/cases/clean.cflr)
      WARN  C11 docs: tests/fixtures/conform_docs/spec/liar.md is missing: write down what you know about the format
      WARN  C11 docs: tests/fixtures/conform_docs/log/liar.md is missing: keep a research log (docs/decoder-guide.md section 11)
conform: 0 PASS, 1 FAIL in 0.5 s
```

```
FAIL  CF-FORBIDDEN  1 inputs, 41 variants, 2 warnings
      FAIL  C8 static rules: tests/fixtures/conform_formats/forbidden.py:3: forbidden import socket
      FAIL  C8 static rules: tests/fixtures/conform_formats/forbidden.py:16: forbidden call open()
      FAIL  C8 static rules: tests/fixtures/conform_formats/forbidden.py:20: fromtimestamp() without a timezone (local time differs between machines; pass tz=datetime.timezone.utc)
      WARN  C11 docs: tests/fixtures/conform_docs/spec/forbidden.md is missing: write down what you know about the format
      WARN  C11 docs: tests/fixtures/conform_docs/log/forbidden.md is missing: keep a research log (docs/decoder-guide.md section 11)
conform: 0 PASS, 1 FAIL in 0.5 s
```

Both runs exited with code 1.

## 5. Runtimes

| what | time |
|---|---|
| `conform` on the real package (STUB) | 0.5 s (0.8 s wall, with interpreter start-up) |
| `conform` on the fixture package (13 decoders, 4 at a time) | about 10 s |
| `task.py test` on Windows | 30.8 s for 243 tests (Phase 3: 19.2 s for 220) |
| `docker-test` | 39.1 s for 243 tests |

## 6. Deviations

1. **C6 only runs on clean decodes that are undamaged and non-empty.** STUB has `encode()`, and its golden case `truncated.stub` cannot round-trip byte for byte: the file is damaged and STUB rightly reports it. Under the literal rule STUB could never pass. An empty result means "not my format", so there is nothing to round-trip either. Without this rule, greedyprobe drew a spurious C6 FAIL on foreign files. A test now guards against that.
2. **The clean decode's timeout is max(variant_timeout, 4 s)**, which is twice the C9 limit, so C9 can actually measure a slow clean decode. Otherwise a 3 s decode under `variant_timeout=2` would show up as a C4 timeout. C6 encodes the clean decode's own result and does not decode again.
3. **Timeouts and crashes are reported under the check whose step was running.**
   - During probing: C2.
   - During `encode()`: C6.
   - While the worker starts, if the decoder cannot be imported or created: C1. Discovery errors (import failure, duplicate name) are C1 too.
   - Variant, clean and synthetic decodes: C4, as the spec says. A clean decode that times out also gets C9.

   The spec only named C4 for variant timeouts.
4. **Extra keyword-only parameters** on `run_conformance`:
   - `docs_root` (default `docs`), so the fixtures can have their own docs.
   - `jobs` (default: up to 4 decoders checked at once, in threads; each decoder still has its own single worker). With `--jobs 1` the fixture run takes 17.5 s instead of 10.5 s.

   Relative roots resolve against the repository root, not the working directory. The CLI flags `--cases-root` etc. resolve against the working directory.
5. **C8 private helpers are `<package>._*`, not only `salvage.formats._*`.** The fixtures live in another package. C8 also scans the private helpers a decoder imports, so a rule cannot be dodged by moving the code into `_helpers.py`.
   - Forbidden calls are bare names and `builtins.<name>`, so `re.compile` stays allowed.
   - `fromtimestamp(**kw)` counts as having a time zone, because it cannot be checked statically.
6. **Changed ranges for zero and overwrite variants list only the bytes that really changed.** Otherwise a zero block over bytes that were already zero would give a false C5 FAIL. Variants identical to the input or to an earlier variant are skipped, so a small input can get fewer than 43 variants (the fixtures get 41, STUB's two cases 82 together).
7. **C7 compares `json.dumps(to_dict(), sort_keys=True)`**, because the pipeline writes with `sort_keys`. Changing list order is caught. Dict key order is not, since it never reaches the output.
8. **C3 leaves out** golden cases of the decoder's own module and case folders that match no decoder module (owner unknown).
9. **Findings are capped at 20 per check per decoder**, followed by one line "... and N more Cx findings like these". The counts are defined as follows: `inputs` = claimed corpus inputs, `variants` = mutated variants decoded.
10. **Extra:** a `crash` fixture, which tests the worker-crash path the spec says is handled "the same way", and unit tests for variants, C8 and discovery errors. A corpus file that cannot be read is a C2 WARN.
11. **The fixture `.expected.json` files are real pipeline output**, generated by `_make_cases.py`. `tests/test_golden.py` does not check them (it only scans `tests/*/cases/`); C10 only needs them to exist. The `nondet` expectation is order-random on purpose.

## 7. Not done / to watch

- `docker-smoke` was not re-run. Nothing it covers changed: no core, CLI or image files were touched.
- **The merge-gate test gets slower as `samples/` grows.** It runs the suite on the real package, which includes `samples/` (empty today), and every claimed sample gets about 43 variants. If samples get large, Core may want a smaller corpus for `task.py test` and the full one for `conform`.
- **C2 and C9 measure wall-clock time in the worker.** Up to 4 decoders run at once, so a heavily loaded CI machine could push a decoder that is close to a limit over it. The fixtures are far from the limits on both sides: slowprobe takes 1.4 s against the 0.5 s limit, and ok's decodes take milliseconds against 2 s.
- Nothing is committed.
