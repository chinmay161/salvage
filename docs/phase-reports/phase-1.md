# Phase 1 report: Phase 0 follow-ups and the end-to-end pipeline

**Status:** done. `python tools/task.py test` passes 127 tests: 84 from Phase 0 plus 43 new ones. That takes 11.8 s on Windows and 8.7 s on Linux. The contract files `model.py`, `plugin.py` and `reader.py` are unchanged.

## 1. Files created or changed

**Part A (Phase 0 follow-ups)**
- `.gitattributes`: new, exactly as specified.
- `tools/task.py`: new. It provides `test`, `api` and `run IN OUT`, all through `sys.executable`. An unknown command or no command prints usage and exits with code 2.
- `Makefile`: `test`, `api` and `run` are now thin wrappers around `$(PY) tools/task.py ...`.
- `CLAUDE.md`: the Commands section now lists `python tools/task.py <cmd>` first and make second. Added the Windows/Linux rule under Hard rules.
- `.gitignore`: added `/out-test/`.

**Part B (pipeline)**
- `salvage/cli.py`: replaced the placeholder.
- `salvage/core/limits.py`, `walk.py`, `identify.py`, `fallback.py`, `emit.py`, `report.py`, `isolate.py`, `pipeline.py`: all new.
- `docs/output-format.md`: new. Documents the per-file output shape and the report.json shape, clearly marked PROVISIONAL.

**Part C (tests)**
- `tests/core/test_cli.py`, `test_naming.py`, `test_walk.py` and `test_pipeline.py`: new, as specified.
- `tests/core/test_identify.py`: new, not in the spec. Covers the tie-break rules, decode-attempt outcomes, the fallback/entropy result, and isolation under every start method.
- `tests/fixtures/pipeline_formats/`: new. Contains `__init__.py`, `_base.py`, `hang.py`, `raising.py`, `crash.py`, `badres.py`, `bigout.py` and `stub.py`.

**Report**
- `docs/phase-reports/phase-1.md`: this file.

## 2. `python tools/task.py api` (new modules only)

```
== salvage.core.emit
def display_path(text: 'str') -> 'str'
def dumps(obj: 'Any') -> 'str'
def output_names(rel_paths: 'Iterable[str]') -> 'dict[str, str]'
def to_output(*, rel: 'str', size: 'int', sha256: 'str | None', fmt: 'str', confidence: 'float', status: 'str', result: 'dict[str, Any] | None' = None, warnings: 'Iterable[str]' = (), errors: 'Iterable[str]' = ()) -> 'dict[str, Any]'
def write_json(path: 'str', obj: 'Any') -> 'None'

== salvage.core.fallback
def entropy(data: 'bytes') -> 'float'
def unknown(data: 'bytes', ranked: 'list[Ranked]') -> 'DecodeResult'

== salvage.core.identify
class Choice(ranked: 'list[Ranked]' = <factory>, candidates: 'list[Decoder]' = <factory>, warnings: 'list[str]' = <factory>) -> None
class Ranked(format: 'str', score: 'float', error: 'str | None' = None) -> None
    error = None
def choose(decoders: 'list[Decoder]', data: 'bytes', filename: 'str') -> 'Choice'

== salvage.core.isolate
def failed_payload(rel: 'str', size: 'int | None', reason: 'str') -> 'dict[str, Any]'
def process_file(path: 'str', rel: 'str', package: 'str' = 'salvage.formats') -> 'dict[str, Any]'
def read_regular(path: 'str', limit: 'int' = 268435456) -> 'bytes'
def run_isolated(path: 'str', rel: 'str', package: 'str', timeout: 'float', method: 'str | None' = None) -> 'tuple[dict[str, Any] | None, str | None]'
def start_method() -> 'str'
def try_candidates(candidates: 'list[Decoder]', data: 'bytes') -> 'tuple[DecodeResult | None, Decoder | None, list[tuple[str, str]]]'

== salvage.core.limits

== salvage.core.pipeline
def run(input_dir: 'str', output_dir: 'str', *, decoder_package: 'str' = 'salvage.formats', timeout: 'float' = 20, progress: 'Progress | None' = None) -> 'dict[str, Any]'
def sha256_file(path: 'str') -> 'str | None'

== salvage.core.report
def file_status(result: 'DecodeResult') -> 'str'
def make_entry(*, rel: 'str', size: 'int', status: 'str', fmt: 'str', confidence: 'float', candidates: 'Iterable[Any]' = (), attempts: 'Iterable[tuple[str, str]]' = (), result: 'DecodeResult | None' = None, warnings: 'Iterable[str]' = (), errors: 'Iterable[str]' = ()) -> 'dict[str, Any]'
def new_report() -> 'dict[str, Any]'
def summarize(rep: 'dict[str, Any]') -> 'None'
def walk_results(result: 'DecodeResult') -> 'Iterator[DecodeResult]'

== salvage.core.walk
class InputFile(path: 'str', rel: 'str', size: 'int') -> None
class Skipped(rel: 'str', reason: 'str') -> None
def list_inputs(input_dir: 'str', output_dir: 'str | None' = None) -> 'tuple[list[InputFile], list[Skipped]]'
```

`api_dump` prints only classes and functions, so module constants are missing from the dump above. They are:
- `limits`: `MAX_SECONDS_PER_FILE = 20`, `MAX_FILE_BYTES = 268435456`, `PROBE_THRESHOLD = 0.5`, `AMBIGUITY_MARGIN = 0.1`
- `emit`: `SCHEMA_VERSION = "provisional-1"`, `REPORT_NAME = "report.json"`
- `report`: `TRUST`, `FILE_STATUSES`

## 3. report.json from the test_pipeline input folder

This report comes from the same 11 inputs as `test_pipeline.py`, run with `decoder_package="tests.fixtures.pipeline_formats"` and `timeout=2`. All keys and values are complete. Only the layout is changed: each file entry sits on one line, where the real file uses `indent=2` and runs to 596 lines. The Windows and Linux runs of this tree produced byte-identical files (see section 5).

```json
{
  "errors": [],
  "files": [
    {"attempts": [{"format": "T-BAD", "outcome": "invalid: records[0].fields[0].offset: 23 outside [0, 13]"}], "candidates": [{"format": "T-BAD", "score": 1.0}, {"format": "STUB", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 0.0, "damage": [], "errors": ["no candidate decoder produced a valid result"], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "bad.t", "members": 0, "output": "bad.t.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "e6edefe273459498dbc83bd351c91cbb5e328c56bd33c868c33d7746b9b062d1", "size": 13, "status": "failed", "warnings": []},
    {"attempts": [{"format": "T-BIG", "outcome": "ok"}], "candidates": [{"format": "T-BIG", "score": 1.0}, {"format": "STUB", "score": 0.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 1.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 40000, "verified": 0}, "format": "T-BIG", "input": "big.t", "members": 0, "output": "big.t.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 40000, "verified": 0}, "sha256": "6a1f1443444d463fc76f2faa33a1128a73f260508e111680764c0284b28ba19c", "size": 13, "status": "decoded", "warnings": []},
    {"attempts": [{"format": "STUB", "outcome": "ok"}], "candidates": [{"format": "STUB", "score": 1.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 1.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 1}, "format": "STUB", "input": "clean.stub", "members": 0, "output": "clean.stub.json", "records_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 0}, "sha256": "35782b611b56441adfe573e4ef89faaf1b177faac80d9bb0e2ddf5b470f7946f", "size": 27, "status": "decoded", "warnings": []},
    {"attempts": [], "candidates": [], "confidence": 0.0, "damage": [], "errors": ["worker crashed (exit code 3)"], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "crash.t", "members": 0, "output": "crash.t.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "f202a12388f3ee67adef2c28d097c46ecb7200a90fb208e4ed2e85d580a695e7", "size": 15, "status": "failed", "warnings": []},
    {"attempts": [], "candidates": [{"format": "STUB", "score": 0.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 0.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "empty.bin", "members": 0, "output": "empty.bin.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "size": 0, "status": "unknown", "warnings": []},
    {"attempts": [], "candidates": [], "confidence": 0.0, "damage": [], "errors": ["timeout after 2s"], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "hang.t", "members": 0, "output": "hang.t.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "fb59d5b4e027e771c6f209118c9c399b7add74f0f5fe02e65e1cc782056d642b", "size": 14, "status": "failed", "warnings": []},
    {"attempts": [{"format": "T-RAISE", "outcome": "error: ValueError: raised on purpose"}], "candidates": [{"format": "T-RAISE", "score": 1.0}, {"format": "STUB", "score": 0.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}], "confidence": 0.0, "damage": [], "errors": ["no candidate decoder produced a valid result"], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "raise.t", "members": 0, "output": "raise.t.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "0466c2c9eb0c634e3ec67df94cd53341a66a0012faa8a14e61bb9be70abac641", "size": 15, "status": "failed", "warnings": []},
    {"attempts": [], "candidates": [{"format": "STUB", "score": 0.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 0.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "format": "unknown", "input": "random.bin", "members": 0, "output": "random.bin.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 0, "verified": 0}, "sha256": "7ac41208e875fa1e7f7a6690299feb30c80b45cf533618f1d955d9d410b92879", "size": 65536, "status": "unknown", "warnings": []},
    {"attempts": [{"format": "STUB", "outcome": "ok"}], "candidates": [{"format": "STUB", "score": 1.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 1.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 1}, "format": "STUB", "input": "report", "members": 0, "output": "report~2.json", "records_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 0}, "sha256": "35782b611b56441adfe573e4ef89faaf1b177faac80d9bb0e2ddf5b470f7946f", "size": 27, "status": "decoded", "warnings": []},
    {"attempts": [{"format": "STUB", "outcome": "ok"}], "candidates": [{"format": "STUB", "score": 1.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 1.0, "damage": [{"end": 23, "kind": "truncated", "reason": "expected 5 values, file ends after 2", "start": 23}], "errors": [], "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 3, "verified": 1}, "format": "STUB", "input": "truncated.stub", "members": 0, "output": "truncated.stub.json", "records_by_status": {"consistent": 0, "lost": 0, "unverified": 3, "verified": 0}, "sha256": "854c9c9d39c46a044c2f564a4fbc25935be0c279803c21a98308faf4a42f58ac", "size": 23, "status": "partial", "warnings": ["truncated at offset 23: expected 5 values, file ends after 2"]},
    {"attempts": [{"format": "STUB", "outcome": "ok"}], "candidates": [{"format": "STUB", "score": 1.0}, {"format": "T-BAD", "score": 0.0}, {"format": "T-BIG", "score": 0.0}, {"format": "T-CRASH", "score": 0.0}, {"format": "T-HANG", "score": 0.0}, {"format": "T-RAISE", "score": 0.0}], "confidence": 1.0, "damage": [], "errors": [], "fields_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 1}, "format": "STUB", "input": "sub/nested.stub", "members": 0, "output": "sub/nested.stub.json", "records_by_status": {"consistent": 1, "lost": 0, "unverified": 3, "verified": 0}, "sha256": "35782b611b56441adfe573e4ef89faaf1b177faac80d9bb0e2ddf5b470f7946f", "size": 27, "status": "decoded", "warnings": []}
  ],
  "schema_version": "provisional-1",
  "skipped": [],
  "summary": {"by_format": {"STUB": 4, "T-BIG": 1, "unknown": 6}, "decoded": 4, "failed": 4, "files": 11, "partial": 1, "skipped": 0, "unknown": 2},
  "tool": "salvage",
  "version": "0.1.0"
}
```

## 4. Last 30 lines of `python tools/task.py test` (Windows)

```
test_bytes_exact (tests.core.test_reader.TruncationTests.test_bytes_exact) ... ok
test_bytes_negative_length (tests.core.test_reader.TruncationTests.test_bytes_negative_length) ... ok
test_bytes_short_tail (tests.core.test_reader.TruncationTests.test_bytes_short_tail) ... ok
test_every_numeric_read_truncates_cleanly (tests.core.test_reader.TruncationTests.test_every_numeric_read_truncates_cleanly) ... ok
test_truncated_read_returns_none_and_keeps_position (tests.core.test_reader.TruncationTests.test_truncated_read_returns_none_and_keeps_position) ... ok
test_cstring_empty (tests.core.test_reader.UnpackAndCStringTests.test_cstring_empty) ... ok
test_cstring_nul_beyond_max_len (tests.core.test_reader.UnpackAndCStringTests.test_cstring_nul_beyond_max_len) ... ok
test_cstring_with_nul (tests.core.test_reader.UnpackAndCStringTests.test_cstring_with_nul) ... ok
test_cstring_without_nul (tests.core.test_reader.UnpackAndCStringTests.test_cstring_without_nul) ... ok
test_unpack (tests.core.test_reader.UnpackAndCStringTests.test_unpack) ... ok
test_unpack_requires_endianness (tests.core.test_reader.UnpackAndCStringTests.test_unpack_requires_endianness) ... ok
test_unpack_truncated (tests.core.test_reader.UnpackAndCStringTests.test_unpack_truncated) ... ok
test_deterministic_json (tests.core.test_stub.StubTests.test_deterministic_json) ... ok
test_probe (tests.core.test_stub.StubTests.test_probe) ... ok
test_round_trip (tests.core.test_stub.StubTests.test_round_trip) ... ok
test_standalone_cli (tests.core.test_stub.StubTests.test_standalone_cli) ... ok
test_statuses (tests.core.test_stub.StubTests.test_statuses) ... ok
test_trailing_bytes_reported (tests.core.test_stub.StubTests.test_trailing_bytes_reported) ... ok
test_truncated (tests.core.test_stub.StubTests.test_truncated) ... ok
test_truncated_inside_count (tests.core.test_stub.StubTests.test_truncated_inside_count) ... ok
test_wrong_magic (tests.core.test_stub.StubTests.test_wrong_magic) ... ok
test_fifo_skipped (tests.core.test_walk.WalkTests.test_fifo_skipped) ... skipped 'no FIFOs on this OS'
test_output_dir_inside_input_is_not_walked (tests.core.test_walk.WalkTests.test_output_dir_inside_input_is_not_walked) ... ok
test_sorted_walk_order (tests.core.test_walk.WalkTests.test_sorted_walk_order) ... ok
test_symlinks_skipped (tests.core.test_walk.WalkTests.test_symlinks_skipped) ... skipped "cannot create symlinks here: [WinError 1314] A required privilege is not held by the client: 'C:\\\\Users\\\\Chinmay\\\\AppData\\\\Local\\\\Temp\\\\tmpqpk2jnoj\\\\real' -> 'C:\\\\Users\\\\Chinmay\\\\AppData\\\\Local\\\\Temp\\\\tmpqpk2jnoj\\\\link'"

----------------------------------------------------------------------
Ran 127 tests in 11.769s

OK (skipped=2)
```

On Linux (WSL Ubuntu 24.04, Python 3.12.3), `make test PY=python3.12` reported `Ran 127 tests in 8.737s` and `OK`, with no skips.

## 5. Multiprocessing start method

- **This machine (Windows 11):** `spawn`.
- **Linux `fork` path:** tested for real on WSL Ubuntu 24.04 with Python 3.12.3, which picks `fork`. Three checks:
  1. The full suite passes there with 0 skips: 127 tests, including the symlink and FIFO walk tests.
  2. `IsolateTests.test_every_start_method` runs a stub file through every start method the OS offers. On Linux that is fork, spawn and forkserver. It asserts that each payload is identical to the in-process result.
  3. The test_pipeline input tree was run once on Windows (`spawn`) and once on Linux (`fork`). `diff -r` on the two output trees showed all 12 files byte-identical.
- **Not tested:** inside the real Docker image, because there is no Dockerfile yet.

## 6. Deviations

1. **Where some helpers live.** The spec did not assign a module to every piece, so:
   - `output_names` is in `emit.py`, the output-shape module.
   - The decode-attempt loop is `isolate.try_candidates`.
   - The file-status rule is `report.file_status`.

   The child process has to import these, and putting them in `pipeline.py` would create a circular import.
2. **`StubDecoder` is re-exported as a trivial subclass.** `discover_decoders` (frozen contract) only counts classes defined in the module itself, so a plain import would not be discovered.
3. **Failed files report `format: "unknown"` and confidence 0.0,** even when a candidate matched. The `format` field names a format only when decoding succeeded. The report entry's `candidates` and `attempts` show what was tried (safest reading).
4. **Decoder import errors are collected from the worker processes,** then deduplicated and sorted. The parent never imports decoder code, so an import-time hang or crash cannot take down the run. Side effect: when there are no input files, import errors are not reported.
5. **`SystemExit` from `decode()` counts as an attempt error,** the same as an `Exception`. This matches `safe_probe`.
6. **Workers send their stdout and stderr to devnull.** Otherwise a decoder's `print` would break the rule of one summary line on stdout and one line per file on stderr.
7. **The timeout covers the worker's whole life,** including process start-up. `spawn` start-up takes roughly 0.1–0.3 s.
8. **Extra safety: no output ever overwrites an input file.** This can happen when output_dir equals input_dir, or when the input dir is nested inside the output dir. The output is skipped, and the entry gets `"output": null` plus an error. The same check protects `report.json`.
9. **output_dir equal to input_dir is not excluded from the walk.** Excluding it would exclude everything. The guard in item 8 keeps the inputs safe.
10. **An output_dir inside input_dir is excluded silently,** not listed in `skipped`. Listing it would make report.json depend on whether the output dir already existed.
11. **Two extra naming rules:**
    - A file whose output name equals an output folder gets `~N`. Example: inputs `a` and `a.json/b` give `a~2.json`.
    - A root folder that casefolds to `report.json` becomes `report.json~dir`, so the report can always be written.
12. **Pipeline warnings such as `ambiguous: ...` are added to the output's `warnings`,** after the decoder's own warnings. The spec says warnings come from `to_dict()`.
13. **Extra keyword parameters:**
    - `pipeline.run(progress=...)`: the CLI uses this callback to print one stderr line per file.
    - `isolate.run_isolated(method=...)`: tests use it to force a start method.
14. **Files are opened with `O_NONBLOCK` and checked with `fstat` for `S_ISREG`** before reading, both for the parent's sha256 and in the worker. A file swapped for a FIFO after the walk can therefore never block.
15. **CLI details:**
    - `-h`, `--help` and `--version` take effect wherever they appear in the arguments.
    - If flushing stdout fails (for example a closed pipe), the CLI falls back to `os._exit(0)`, so it still exits 0.
16. **Error texts never use `str(OSError)`,** because it embeds the absolute path. They use `strerror` only.
17. **Non-UTF-8 file names are backslash-escaped in the JSON** (`emit.display_path`). The output files on disk keep the original name bytes.
18. **`tools/task.py run` runs from the caller's directory** with the repo root on `PYTHONPATH`, so relative `IN` and `OUT` paths work.
19. **Windows `spawn` re-imports the calling script.** Any script that calls `pipeline.run()` needs an `if __name__ == "__main__":` guard. The guard is documented in `pipeline.run`, and the CLI already has one. I hit this myself with an unguarded scratch script.

## 7. Not done / open points

- **No Dockerfile yet,** so nothing was tested inside the Docker image. Linux was covered through WSL instead.
- **Two walk tests skip on Windows.** The symlink test needs a privilege this account lacks, and Windows has no FIFOs. Both pass on Linux.
- **Windows-reserved output names are not handled.** This covers `CON`, `NUL`, and names ending in a dot or space. It only matters when Linux-made inputs are processed on Windows.
- **Entropy on a 256 MB unknown file was not timed.** It runs `Counter` over the bytes, which should take a few seconds, under the 20 s limit.
- **Parallel workers** are deferred to Phase 5, as specified.
- **For the lead: `.gitignore` ignores `CLAUDE.md` and `docs/`.** As it stands, this report, `docs/output-format.md` and the teammates' `docs/spec/` would never be committed. That looks unintended, but I did not change it.
