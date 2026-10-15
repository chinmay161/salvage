# Phase 2 report: Phase 1 fixes, Docker, task runner, golden tests

**Status:** done. Every "done when" check passed:

- `python tools/task.py test` passes 138 tests on Windows (2 skipped).
- `build` and `build-offline` succeed. A cold build with `--no-cache --network none` also succeeds.
- `docker-test` passes 138 tests inside the image (0 skipped).
- `docker-smoke` passes all 8 checks. The host and container outputs are byte-identical.

The contract files `model.py`, `plugin.py` and `reader.py` are unchanged.

## 1. Files created or changed

**Part A: Phase 1 fixes**
- `.gitignore`: rewritten (section 2).
- `salvage/core/isolate.py`:
  - The worker now sends two messages: `("identified", info)` and then `("done", payload)`.
  - New functions `identified_info()` and `identity()`.
  - `process_file(..., on_identified=None)`.
  - `failed_payload(..., info=None)` keeps the identification when one exists.
  - `run_isolated` uses one deadline for both messages and returns `(payload, reason, info)`.
  - Timeout and crash reasons name the stage the worker reached.
- `salvage/core/pipeline.py`: `_process` passes the child's identification on to `failed_payload`.
- `salvage/core/fallback.py`:
  - New `entropy_sample()` and `entropy_is_sampled()`. Over 4 MB, entropy is measured on 1 MB + 2 MB + 1 MB of the file.
  - New meta key `entropy_sampled`.
- `docs/output-format.md`:
  - New section "`format` and `confidence` = identification".
  - `status` is now described as the decoding outcome.
  - `failed` files keep their identification.
  - Stage suffixes and `entropy_sampled` are documented.
- `tests/core/test_pipeline.py`:
  - hang.t, crash.t, raise.t and bad.t now expect their own format with status `failed`, confidence 1.0 and their candidates.
  - The timeout and crash tests check the exact reason text.
  - New `SlowProbeTests`.
  - New checks that `unknown` still means "no candidate", and for `entropy_sampled`.
- `tests/core/test_identify.py`:
  - The test unpacks the 3-tuple and checks the `identified` info.
  - New tests: the entropy sample layout, 64 MB in under 1 s with identical results on two runs, and the `entropy_sampled` flag.
- `tests/fixtures/slowprobe_formats/__init__.py` and `slowprobe.py`: new. Contain T-SLOWPROBE, whose probe never returns.

**Part B: Docker**
- `docker/salvage`, `docker/entrypoint.sh`, `Dockerfile` and `.dockerignore`: all new. All use LF line endings.

**Part C: task runner**
- `tools/task.py`: new commands `build`, `build-offline`, `docker-run IN OUT`, `docker-test`, `docker-smoke`, `golden [FORMAT]` and `golden-update FORMAT`.
- `Makefile`: a wrapper target for each new command.

**Part D: golden tests**
- `tests/golden.py`: new helper library, not a test module. It finds cases, runs them, computes JSON-path diffs and updates expectations.
- `tests/test_golden.py`: new. Contains `GoldenTests` (one subTest per case) and `GoldenSelfTests`.
- `tests/stub/cases/`: new. Contains `clean.stub`, `truncated.stub` and `wrong_magic.bin`, each with its `.expected.json`. I checked all three expectations by hand against the file bytes.

**Part E: docs**
- `CLAUDE.md`: lists the new commands. New "Golden tests" section with the golden-update rules.
- `README.md`: new.
- `docs/phase-reports/phase-2.md`: this file.

## 2. Final `.gitignore` and the cause

```
__pycache__/
*.pyc
.venv/
/out/
/out-*/
```

**Cause:** the repo's own `.gitignore`. There is no global excludes file (`core.excludesfile` is unset, there is no `~/.config/git/ignore`, and `.git/info/exclude` has only comments). So no `!` exceptions were needed.

- Line 5 was `CLAUDE.md`. `git check-ignore -v` reported `.gitignore:5:CLAUDE.md`.
- Line 6 was `docs//out-test/`. A missing newline had joined a `docs/` rule and the Phase 1 `/out-test/` rule into one line. That pattern matched nothing, so `docs/` was not actually ignored, but the `/out-test/` rule was lost as well. `/out-*/` now covers it.

After the fix, `git check-ignore` matches none of `CLAUDE.md`, `docs/output-format.md` or `README.md` (exit 1), and `out-test/x` is ignored by `/out-*/`.

## 3. report.json entries after A2

These come from the fixture decoders with a 20 s timeout. The `candidates` lists are shortened here: the other five decoders each scored 0.0.

```json
{"input": "hang.t", "output": "hang.t.json", "size": 14,
 "sha256": "fb59d5b4e027e771c6f209118c9c399b7add74f0f5fe02e65e1cc782056d642b",
 "status": "failed", "format": "T-HANG", "confidence": 1.0,
 "candidates": [{"format": "T-HANG", "score": 1.0}, {"format": "STUB", "score": 0.0}, "..."],
 "attempts": [],
 "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0},
 "fields_by_status":  {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0},
 "members": 0, "damage": [], "warnings": [],
 "errors": ["timeout after 20s (during decode)"]}

{"input": "crash.t", "output": "crash.t.json", "size": 15,
 "sha256": "f202a12388f3ee67adef2c28d097c46ecb7200a90fb208e4ed2e85d580a695e7",
 "status": "failed", "format": "T-CRASH", "confidence": 1.0,
 "candidates": [{"format": "T-CRASH", "score": 1.0}, {"format": "STUB", "score": 0.0}, "..."],
 "attempts": [],
 "records_by_status": {...all 0}, "fields_by_status": {...all 0},
 "members": 0, "damage": [], "warnings": [],
 "errors": ["worker crashed with exit code 3 (during decode)"]}

{"input": "raise.t", "output": "raise.t.json", "size": 15,
 "sha256": "0466c2c9eb0c634e3ec67df94cd53341a66a0012faa8a14e61bb9be70abac641",
 "status": "failed", "format": "T-RAISE", "confidence": 1.0,
 "candidates": [{"format": "T-RAISE", "score": 1.0}, {"format": "STUB", "score": 0.0}, "..."],
 "attempts": [{"format": "T-RAISE", "outcome": "error: ValueError: raised on purpose"}],
 "records_by_status": {...all 0}, "fields_by_status": {...all 0},
 "members": 0, "damage": [], "warnings": [],
 "errors": ["no candidate decoder produced a valid result"]}
```

bad.t gives `"format": "T-BAD"` with status `failed`. A file run with the T-SLOWPROBE decoder gives `"format": "unknown"`, status `failed`, `"candidates": []` and `"errors": ["timeout after 2s (during probe)"]`. Tests cover all of these.

## 4. Dockerfile and base image digest

Base image: `python:3.12-slim` = `python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` (pulled 2026-10-15).

```dockerfile
# Salvage: offline legacy-format recovery. No network is used at build time.
# Base image pinned by digest (tag: python:3.12-slim).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY salvage/ /app/salvage/
COPY vendor/ /app/vendor/
COPY docker/salvage /salvage
COPY docker/entrypoint.sh /usr/local/bin/salvage-entrypoint
RUN chmod 755 /salvage /usr/local/bin/salvage-entrypoint \
    && python3 -m compileall -q /app

# Runs as root on purpose: an output folder that Docker creates for a bind
# mount on a Linux host is owned by root, and a non-root user could not
# write to it. Pass --user "$(id -u):$(id -g)" for host-owned output files.
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/salvage-entrypoint"]
```

`.dockerignore` contains `*`, `!salvage/`, `!vendor/`, `!docker/`, `**/__pycache__` and `**/*.pyc`.

I checked all three run styles: `IMAGE /salvage --version`, `IMAGE --version`, and `IMAGE` with no arguments (prints help). A missing input directory exits 0.

## 5. build-offline (last 15 lines) and image size

```
#12 exporting to image
#12 exporting layers
#12 exporting layers 0.4s done
#12 exporting manifest sha256:de7cd7bc6cecd528182c88e4a17b6159139dd72b5ee106faf0997604bbdd05fd 0.1s done
#12 exporting config sha256:657b91eb88ed3b0cc0c306e8078f73ab9f098c554d7a05804c21127014019d85 0.1s done
#12 exporting attestation manifest sha256:62afe3098d411dc3be6034b17734b4ec883bd318b004675c38c5ef33b82ca2b3 0.1s done
#12 exporting manifest list sha256:ee1513be4d73f720b1adecd9ff096f4a78a5c819be485525eb91ba8a06fcfd9f
#12 exporting manifest list sha256:ee1513be4d73f720b1adecd9ff096f4a78a5c819be485525eb91ba8a06fcfd9f 0.1s done
#12 naming to docker.io/library/salvage:dev 0.0s done
#12 unpacking to docker.io/library/salvage:dev
#12 unpacking to docker.io/library/salvage:dev 0.2s done
#12 DONE 1.1s

View build details: docker-desktop://dashboard/build/desktop-linux/desktop-linux/gdt882egff6d6n369q1jglrie
```

This run reused cached layers. `docker build --no-cache --network none -t salvage:dev .` also exited 0, which shows that every step works without a network.

```
IMAGE         ID             DISK USAGE   CONTENT SIZE
salvage:dev   ee1513be4d73        178MB         43.4MB
```

For comparison, the base image `python:3.12-slim` is 179MB / 45.4MB, so Salvage adds almost nothing.

## 6. docker-smoke output

```
PASS  host run exits 0  (exit 0)
PASS  docker run (--network none) exits 0  (exit 0)
PASS  host: report.json present
PASS  host: one JSON per input (7 inputs)  (7 outputs)
PASS  docker: report.json present
PASS  docker: one JSON per input (7 inputs)  (7 outputs)
PASS  host and docker outputs byte-identical  (8 files compared)
PASS  docker run on a missing input dir exits 0  (exit 0)
docker-smoke: 8 PASS, 0 FAIL
```

The inputs were:

- `clean1.stub` and `clean2.stub`
- `truncated.stub`
- `sub/nested.stub`
- `empty.bin`
- `random.bin` (64 KB, seed 1234)
- a file named `report`, which maps to `report~2.json`

I also tested what happens when Docker is unavailable:

- Docker not on PATH: the command prints `error: docker is not installed (no 'docker' on PATH)` and exits 1.
- Daemon unreachable (`DOCKER_HOST=tcp://127.0.0.1:1`): it prints `error: the docker daemon is not running ...` and exits 1 after 0.13 s.

The daemon check uses a 30 s timeout, and container runs time out after 1 h.

## 7. Test totals

| where | command | result |
|---|---|---|
| Windows (host, Python 3.12.2) | `python tools/task.py test` | `Ran 138 tests in 16.4s`, `OK (skipped=2)` |
| Linux (image, python:3.12-slim) | `python tools/task.py docker-test` | `Ran 138 tests in 17.1s`, `OK` |

The 2 Windows skips are `test_fifo_skipped` (no FIFOs on Windows) and `test_symlinks_skipped` (creating symlinks needs a privilege this account lacks). Both run and pass on Linux.

Phase 1 had 127 tests; Phase 2 adds 11.

## 8. Golden tests

**Cases found:** one folder, `tests/stub/cases/`, with 3 cases:

| case | status | notes |
|---|---|---|
| `clean.stub` | decoded | STUB, 4 values |
| `truncated.stub` | partial | count 5, 2 values, then 2 stray bytes; damage [23, 25) |
| `wrong_magic.bin` | unknown | `entropy_sampled: false` |

**Results:**
- All 3 cases pass on Windows (`python tools/task.py golden stub`) and on Linux inside `docker-test`. The expectations were generated on Windows, so this also checks that output is the same on both OSes.
- `golden-update stub` run a second time reports all 3 files `unchanged`.
- `golden-update` with no FORMAT, with `nope`, or with `../tests` is refused.

**Self-tests** (`GoldenSelfTests`, built in a temp folder):
- a wrong expectation fails with a path diff;
- a correct expectation passes;
- an input with no expectation fails with "missing expectation";
- an expectation with no input fails with "orphan expectation";
- the diff stops at 20 lines;
- `1 == 1.0`, but `1 != true`.

Sample diff from the self-test. The expectation had value 21 instead of 20, status `partial`, and no `meta.decoded_count`:

```
3 difference(s):
  meta.decoded_count: expected nothing (unexpected key), got 3
  records[2].fields[0].value: expected 21, got 20
  status: expected "partial", got "decoded"
```

## 9. Deviations

1. **A1: `docs/` was not really ignored.** The `docs/` rule had been merged into `docs//out-test/` (section 2). I replaced that line rather than adding exceptions. The `/out-test/` rule it contained is now covered by `/out-*/`.
2. **A2: which candidate is "chosen".**
   - For `decoded`/`partial` files, it is the decoder whose result is written. This can be the second candidate if the first one errored or returned nothing.
   - For `failed` files, it is the first candidate tried (best score, then the extension hint, then the name).
3. **A2: decoded files now take confidence from the probe.** The spec says "for every status", so `decoded`/`partial` files now get the probe score as `confidence` and the decoder name as `format`. Before, these came from the decoder's own `DecodeResult.confidence` and `.format`. For STUB the values are the same (1.0, "STUB"), so no current output changed.
   - **Lead decision needed:** a decoder's self-reported confidence or sub-format no longer appears in the output.
4. **A2: what "during probe" covers.** It means anything before the "identified" message arrives: worker start-up, reading the file, importing decoders and probing.
   - If identification finishes with no candidate (an `unknown` file) and the entropy fallback then times out, the reason says "(during decode)". I kept only the two labels in the spec rather than adding a third. With A3 this case is very unlikely.
5. **A2: crash and bad-payload reasons name the stage too.** Example: `worker crashed with exit code 3 (during decode)`. It was `worker crashed (exit code 3)`.
6. **A2: timeout and crash entries have `"attempts": []`.** The worker sends its attempt list only in the final message, so it is lost if the worker dies. `candidates` are kept as specified.
7. **A2: `run_isolated` returns 3 values.** It now returns `(payload, reason, info)`. It is not part of the contract. One test was updated.
8. **A2: T-SLOWPROBE has its own fixture package.** It lives in `tests/fixtures/slowprobe_formats/`. Every decoder probes every file, so putting it in `pipeline_formats` would make every pipeline test time out.
9. **B3: one RUN step.** `chmod` and `compileall` share one RUN step, which gives one layer.
10. **B4: `.dockerignore` also drops bytecode.** It excludes `__pycache__` and `*.pyc` inside the allowed folders, so bytecode compiled on the host never enters the image.
11. **C: `docker-test` uses no temp working copy.** The tests write only to `tempfile` folders under `/tmp`, and the image sets `PYTHONDONTWRITEBYTECODE`. The read-only `/src` mount was enough: all 138 tests pass.
12. **C: `docker-run` path format.** On Windows, paths are made absolute with forward slashes (`C:/Users/...`). I tested a relative path with spaces (`out-test/in dir`).
13. **C: `docker-smoke` keeps its temp folder on failure** and prints the path, for inspection.
14. **C: `golden` scope.**
    - `golden [FORMAT]` runs only `GoldenTests`. The self-tests run in `task.py test`.
    - `golden-update` with no FORMAT exits 2 (usage). A FORMAT that contains a path part is refused.
    - `golden-update` exits 1 if any output could not be written.
15. **D: golden logic lives in `tests/golden.py`.** Both the test module and `task.py golden-update` use it, so the logic exists once. `GoldenTests` is a single test with one subTest per case, so `Ran N tests` counts it as 1.
16. **E2: extra `salvage` tag.** While checking the README commands literally, I built the image under the tag `salvage`. That image is still there; `docker rmi salvage` removes it.

## 10. Not done

- **The Makefile targets are untested.** `make` is not installed on this machine. Each target is a one-line call to the `task.py` command that was tested.
- **The README's Linux-host examples are untested.** These are `$PWD` with `--user "$(id -u):$(id -g)"`, and the root-owned output case. Only Windows/Docker Desktop was available. The PowerShell example and `docker build -t salvage .` were run and work.
- **The `docker save` / `docker load` offline-machine steps were not run.** The equivalent was tested: a no-cache build with `--network none`.
- **Nothing was committed.** The repository still has no commits, and committing was not part of the task.
