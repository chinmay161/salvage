# Phase 5 report: Phase 4 follow-ups + hardening

**Status:** done. Every "done when" check passed:

- `python tools/task.py test` on Windows: **268 tests pass in 32.6 s** (5 skipped, all POSIX-only). The budget was 30.8 s + 15 s = 45.8 s.
- `python tools/task.py docker-test`: **268 tests pass in 46.9 s, none skipped**. The POSIX tests (memory cap, SIGTERM, case-only names, FIFOs, symlinks) all ran.
- `python tools/task.py docker-smoke`: 8 PASS, 0 FAIL (re-run after the core changes, with a rebuilt image).
- Golden tests are unchanged and pass; `golden-update` was not run.
- `--jobs 1` vs `--jobs 4` byte-identical: tested on both OSes, including the hang, crash, raise and bad-result fixtures.
- Per-file outputs are byte-identical to Phase 4. I ran Phase 4's `salvage/` (from a HEAD worktree) and the new code on the smoke inputs plus 27 bench inputs: all 34 per-file outputs match. `report.json` differs only by the new `"warnings": []` key (deviation 1).
- The contract files (`model.py`, `plugin.py`, `reader.py`) are unchanged.

## 1. Files created or changed

**Core (changed)**
- `salvage/core/limits.py`: new `MAX_WORKER_MEMORY` (2 GiB). The `SALVAGE_LIMITS` override (B1) is read at import time and documented as test-only.
- `salvage/core/isolate.py`: a new non-blocking `Worker` class plus `drive()`; `run_isolated()` now uses them. Also:
  - `cap_memory()` and `memory_reason()`;
  - the `"error: memory limit"` attempt outcome;
  - `"file disappeared"`;
  - the child resets SIGTERM/SIGINT before decoding.

  A timed-out worker is now terminated at once, then killed 2 s later.
- `salvage/core/pipeline.py`:
  - a parallel scheduler (`jobs=`, `stats=`, `default_jobs()`);
  - SIGINT/SIGTERM handling;
  - the run-level `warnings` ("output dir was not empty");
  - a guard for an output path that is an existing folder;
  - too-large files are never read;
  - `_process` is split into `_start` and `_collect`.
- `salvage/core/report.py`: the report has a `warnings` list.
- `salvage/core/schemas/report.provisional.json`: `warnings` is required (a list of strings).
- `salvage/cli.py`: hand-parsed `--jobs N|auto` and `--stats`. stdout and stderr are reconfigured with `errors="replace"`. Warnings are printed to stderr.

**Tools and docs (changed)**
- `tools/task.py`: new `bench [--docker]`; `conform --quick` documented.
- `Makefile`: `make bench [ARGS=--docker]`.
- `docs/output-format.md`:
  - report `warnings`;
  - the new error strings;
  - a new "Running" section on parallel runs, the memory cap (and that Windows has none), interrupts and `SALVAGE_LIMITS`.
- `docs/conformance.md`: quick mode and the re-measure.
- `README.md`: `--jobs`, `--stats`, stopping a run, a non-empty output folder, and the new commands.
- `CLAUDE.md`: `conform --quick`, `bench`.

**Conformance (Phase 4 files, changed)**
- `tests/conformance.py`:
  - `run_conformance(..., quick=False)`, `variants(..., quick)`, `--quick`, and the mode in the summary line;
  - the C2/C9 re-measure (`_Gate`, `_remeasure`);
  - the worker pipe is duplex, so the worker can take re-measure commands.
- `tests/core/test_conformance.py`: the merge gate runs with `quick=True`.
- `tests/core/test_conformance_selftest.py`: tests for the warmup fixture, the re-measure messages and quick variant counts.
- `tests/fixtures/conform_formats/warmup.py` (new) and `_make_cases.py` (new `warmup` entry, optional module filter).
- New fixture files for warmup:
  - `tests/fixtures/conform_cases/warmup/cases/clean.cfwu` and its `.expected.json`;
  - `tests/fixtures/conform_docs/{spec,log}/warmup.md`.

**Tests (new)**
- `tests/core/test_hardening.py`: B1–B6, 19 tests.
- `tests/pipeline_helpers.py`: `run_checked()` calls `pipeline.run` with an explicit `jobs`, then asserts `multiprocessing.active_children()` is empty.
- `tests/fixtures/hostile_formats/`: `memhog` (4 GiB), `stubborn` (ignores SIGTERM, loops), `slow` (0.5 s), and a STUB re-export.
- `tests/fixtures/cli_with_package.py`: runs the real `salvage.cli.main` with a fixture decoder package (used by the SIGTERM test).

**Tests (changed)**
- `tests/core/test_pipeline.py`:
  - every run goes through `run_checked` with an explicit `jobs`;
  - out1 uses `jobs=1` and out2 `jobs=4`, compared byte for byte;
  - the too-large test asserts the file is never hashed.
- `tests/core/test_validate.py`: patches `_collect` instead of `_process`.
- `tests/core/test_identify.py`: the read-error test reads a folder; a missing file now gives "file disappeared".
- `tests/core/test_cli.py`: `--jobs` and `--stats` parsing; a bad `--jobs` still exits 0.
- `tests/golden.py`: passes `jobs=1`.

## 2. Quick vs full conform

`samples/` is empty today, so the corpus is the same in both modes for now. Once samples arrive, quick mode leaves them all out.

**Real package (STUB)**

| | full (`conform`) | quick (`conform --quick`, merge gate) |
|---|---|---|
| corpus | 3 case inputs + every file in `samples/` (0 today) + 5 synthetic | 3 case inputs + 5 synthetic (`samples/` never read) |
| claimed inputs | 2 | 2 |
| variants per claimed input (at most) | 43 (16 truncate, 20 bitflip, 3 zero, 3 overwrite, 1 append) | 21 (8, 8, 2, 2, 1) |
| variants decoded | 82 | 40 |
| C7 inputs | every clean claimed input (2) | the first one (1) |
| runtime | 0.5 s | 0.4 s (merge-gate test: 0.43 s) |

**Fixture package (14 decoders, `--timeout 2`)**

| | full | quick |
|---|---|---|
| variants (CF-OK, for example) | 41 | 20 |
| runtime | 15.0 s | 14.8 s |

Fixed waits dominate the fixture run (hang timeouts, 3 s sleeps, exclusive re-measures), so quick mode barely changes its time.

## 3. B items

| item | what was done | test(s) | ran on |
|---|---|---|---|
| **B1** limit overrides | `SALVAGE_LIMITS` JSON is applied at import of `limits.py`. Unknown keys, wrong types, negative values and bad JSON are ignored, with one stderr line, printed by the main process only. Workers inherit the environment. | `LimitOverrideTests` (3). `test_isolated_workers_see_the_override` sets `MAX_RECORDS=2` and gets "output capped at 2 records", which is enforced inside the worker. | Windows, Linux |
| **B2** memory cap | The worker calls `cap_memory()` before reading the file: `setrlimit(RLIMIT_AS, (2 GiB, 2 GiB))`, keeping a lower existing hard limit. A `MemoryError` in decode gives the outcome `error: memory limit`; if nothing succeeds, the file fails with `memory limit (2048 MiB)`. On Windows the cap is skipped silently (documented). | `test_memory_hog_fails_and_next_file_decodes`: 4 GiB `bytearray`, then the next file decodes. Also `test_memory_error_outcome_in_process` and `test_cap_memory_is_a_no_op_without_resource`. | hog test on Linux only (skipped on Windows with a reason); the other two on both |
| **B3** stubborn and leftover processes | `Worker` reaps without blocking. A timed-out worker gets SIGTERM, then SIGKILL after 2 s. A worker that answered gets 1 s to exit by itself. | `test_sigterm_ignoring_worker_is_killed_and_reported_as_timeout` (`timeout after 1s (during decode)`). `run_checked()` asserts `active_children()` is empty after **every** in-process run in `test_pipeline` and `test_hardening` (17 runs). | Windows, Linux |
| **B4** interrupted runs | SIGINT/SIGTERM handlers (main thread only) set a flag, polled every 0.2 s. On the flag: no new files start, running workers are killed, and the report gets `interrupted: N files not processed`. Unfinished files get no output. Handlers are restored afterwards. Exit code 0. | `test_sigterm_mid_run_writes_report_and_exits_0`: real CLI subprocess, 12 slow files, SIGTERM after the first progress line. It checks exit 0, a report that passes the schema, the exact error text, and that outputs exist only for finished files. Also `test_signal_after_first_file_stops_the_run` (SIGTERM raised inside the run). | CLI test on Linux; in-process test on both |
| **B5** console encoding | `stdout.reconfigure(errors="replace")` and the same for stderr at CLI start. | `test_unencodable_names_on_an_ascii_console`: `PYTHONIOENCODING=ascii`; names `café`, `नमस्ते`, `😀 smile`; exit 0, 3 stderr lines with `?`, report names intact. | Windows, Linux |
| **B6** file-system edges | Several fixes. A file deleted after the walk gives `file disappeared` (both in the parent and in the worker). An output path that is an existing folder gives `cannot write output: output path is an existing folder`, and the run continues. A non-empty output dir gets the run-level warning `output dir was not empty: N existing files`; nothing is deleted. Too-large files are never opened, not even to hash them. | `FileSystemEdgeTests` (8): spaces, emoji, Devanagari; case-only names; 60-level tree; deleted after walk; deleted before worker read; output path is a folder; non-empty output dir; `SALVAGE_LIMITS` 1 MiB with a 2 MiB file, where the patched `sha256_file`/`Worker` never see the big file. | all on both, except case-only names: Linux only (skipped on NTFS: "case-insensitive file system"). The 60-level tree ran on both. |
| **B7** parallel processing | The parent drives up to N `Worker`s with `multiprocessing.connection.wait`, each with its own pipe and deadline. Only the parent writes. Report entries are kept in walk order, and progress lines come in completion order. `--jobs N`/`--jobs=N`/`--jobs auto`; default `min(cpu_count, 4)`. `pipeline.run(jobs=1)` is the library default. | `test_deterministic_and_jobs_1_vs_4_byte_identical` (11 inputs including hang, crash, raise, bad, big). `ParseArgsTests` (4). `bench` also checks identity on 525 files. | Windows, Linux |
| **B8** benchmark | `python tools/task.py bench [--docker]`: 500 STUB + 20 random 1 MiB + 5 truncated files. It runs the CLI with `--jobs 1` and `--jobs auto --stats`, prints the table and checks both outputs are identical. | — (not part of `test`) | Windows, Docker |

## 4. Benchmark (525 files, host has 12 logical CPUs)

| where | jobs | seconds | files/s | peak workers |
|---|---|---|---|---|
| Windows host | 1 | 58.23 | 9.0 | 1 |
| Windows host | auto (4) | 17.47 | 30.0 | 4 |
| Docker (salvage:dev) | 1 | 14.84 | 35.4 | 1 |
| Docker (salvage:dev) | auto (4) | 11.10 | 47.3 | 4 |

Outputs of `--jobs 1` and `--jobs auto` were byte-identical in both runs. The times include interpreter start-up, and container start-up for Docker.

Docker with `--jobs auto` is **above** the 20 files/s threshold, so no fix is needed. The jobs 1 → 4 speed-up in Docker is only 1.3×, though, so I profiled the parent inside the container (no code was changed). Of the parent's 6.3 s, **2.9 s are `posix.lstat` (5,768 calls)**. Most come from `os.path.realpath()` in `pipeline._key()`: the input-overwrite guard resolves every input path, and every output target, one path component at a time. On a Docker Desktop bind mount from Windows each `lstat` is slow.

**Proposed fix (not implemented):** build the `protected` set and check targets only when the output dir is inside, or the same as, the input dir. Otherwise no output can land on an input. For the remaining case, compare `normcase(abspath())` first and call `realpath()` only on a match.

## 5. Test totals and times

| run | tests | skipped | time |
|---|---|---|---|
| Windows `task.py test` | 268 | 5 | 32.6 s (Phase 4: 30.8 s for 243) |
| `docker-test` (Linux) | 268 | 0 | 46.9 s (Phase 4: 39.1 s for 243) |

Windows skips:
- FIFO and symlink: both existed before this phase.
- Case-only names: NTFS is case-insensitive.
- Memory hog: no `resource` module on Windows.
- CLI SIGTERM: a POSIX-only test.

docker-smoke:
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

## 6. Behaviour that differs between Windows and Linux

- **Memory cap:** Linux only. On Windows a decoder that runs out of memory fails with `out of memory (no memory cap in this process)`, not `memory limit (2048 MiB)`. Its attempt outcome is `error: memory limit` on both.
- **Killing a stubborn worker:** on Windows, `terminate()` is TerminateProcess, which cannot be ignored, so the worker dies at once. On Linux a worker that ignores SIGTERM is SIGKILLed after a 2 s grace, so that file takes about 2 s longer. The output is the same on both.
- **Interrupts:** `docker stop` sends SIGTERM, which only exists in practice on POSIX. On Windows, Ctrl-C (SIGINT) uses the same handler. The handler logic is tested in-process on Windows; a real Ctrl-C of a CLI subprocess on Windows was **not** tested (see section 8).
- **Worker start:** spawn on Windows takes about 110 ms per file; fork on Linux takes a few ms. This shows in the benchmark only, not in the output.
- **Case-only file names** cannot exist on NTFS. On Linux they get `A.stub.json` and `a.stub~2.json`.
- **Unreadable path error text** depends on the OS when a path cannot be read. Reading a folder gives `Permission denied` on Windows and `not a regular file` on Linux; this was already the case in Phase 4. The new "output path is an existing folder" error uses a fixed text, so it is the same on both.

## 7. Deviations

1. **`report.json` always has `"warnings": []`.** B6 asks for the list. Keeping it always present gives a stable schema. As a result `report.json` is not byte-identical to Phase 4's: it has one extra key. Every per-file output is byte-identical (verified; see Status at the top).
2. **Too-large files now have `sha256: null`.** Phase 4 hashed them. "Never fully read" rules out hashing. The old test asserted a hash; it now asserts the file is never hashed.
3. **A missing file at read time is `file disappeared`.** It used to be `cannot read file: No such file or directory`. `test_identify` was updated to match.
4. **A pass on the re-measure is a WARN that shows both timings,** not silence. A one-time warm-up is worth knowing about, and a WARN does not fail the gate.
5. **The re-measure runs in the same worker process** (warm), after every other decoder in that run has finished, including their C7. A fixture that is slow only on its first call would be slow again in a fresh process. `_Gate` blocks new checks while a re-measure runs. Checks that have not started do not count, so a full thread pool cannot deadlock.
6. **C9 for a clean decode that times out is not re-measured.** It is already a C4 FAIL, and timing a hang again would only time out again.
7. **Quick-mode C7 uses "the first claimed input that decoded cleanly".** C7 only ever runs on those.
8. **`pipeline.run(jobs=1)` is the library default.** Library callers keep the old sequential behaviour; the CLI's default is auto. Every test passes `jobs` explicitly.
9. **Extra CLI pieces:** `--jobs auto`, `--jobs=N`, `--`, and `--stats`. `--stats` was needed so `bench` can report peak workers from the real CLI, including in Docker. A bad `--jobs` prints an error plus usage and exits 0.
10. **When a run is interrupted, a worker that had already sent its result is kept,** because its work is real and finished. Only unfinished files are dropped. N counts running plus never-started files.
11. **SIGINT during a run no longer raises `KeyboardInterrupt` out of `pipeline.run`.** It is handled like SIGTERM, as B4 asks. Outside a run, Ctrl-C still raises as before.
12. **The memory message shows the cap actually in force.** If the container's hard limit is lower than 2 GiB, that lower value is used and shown.
13. **The SIGTERM CLI test uses `tests/fixtures/cli_with_package.py`.** It runs the real `cli.main` with `pipeline.run` wrapped to use the fixture package. I did not add a production "decoder package" hook only for tests.
14. **`SALVAGE_LIMITS` also ignores wrong value types and negative values,** with the same single stderr line. Only the main process prints that line, because every worker re-reads the environment.
15. **"Output dir was not empty" counts every file under the output dir, recursively, before the run starts.** That includes foreign files, and inputs when the output dir is the input dir.
16. **The output-is-a-folder case is checked before writing and has a fixed message,** so Windows and Linux reports match. `os.replace` would otherwise give different OS errors.
17. **Extra tests:**
    - B3 runs on both OSes;
    - an in-process interrupt test, so the stop logic is also covered on Windows;
    - the 60-level tree uses one-letter folder names, so it fits Windows' 260-character limit and actually ran here. The skip path exists but was not needed.
18. **A timed-out worker is terminated at once** (Phase 4 first waited 1 s). This saves 1 s per timeout; reasons and exit codes are unchanged.

## 8. Not done / to watch

- **A real Ctrl-C (CTRL_C_EVENT) of a CLI subprocess on Windows is not tested.**
  - On Windows Ctrl-C also reaches the spawn workers. They ignore SIGINT once `_child` runs.
  - A worker that is still starting up could print a `KeyboardInterrupt` traceback to the console. This is cosmetic: it does not affect the outputs, and I have not verified it.
- **Docker throughput:** above the threshold, but the parent's `realpath()` cost on bind mounts limits scaling. The fix is proposed in section 4, not implemented.
- **The conformance self-test run grew from about 10 s to about 15 s.** The causes are the warmup fixture's 3 s first decode (and the same in its two C7 children) and the exclusive re-measures. Total `task.py test` time is still within budget, because pipeline tests now overlap their timeouts with `jobs=4`.
- Nothing is committed.
