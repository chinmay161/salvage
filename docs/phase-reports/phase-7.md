# Phase 7 report: migration to the official output contract

Branch `phase-7` from `main` 7322242: commit 5e95b3d (the migration), plus
a second commit with this report and the saved samples report. The tool now
writes exactly the organizers' contract (kit/OUTPUT-CONTRACT.md). Where it is
silent, the reference answers in kit/expected_outputs/ decide; the decisions
are in section 2 and in docs/output-format.md.

**Done-when:**
- `test` passes on Windows (339 tests). `docker-test` passes (339). The
  python:3.10-slim run passes (339).
- `./salvage kit/samples out` works from the repo root in WSL (Ubuntu,
  Python 3.12.3) and in a python:3.10-slim container. `salvage.cmd` works
  on Windows.
- The Docker run on kit/samples/ exits 0. It writes one JSON per top-level
  file plus report.json, and the `nested/` subfolder is skipped.
  check-outputs finds 0 problems.
- Every output validates against the official schemas.
- `calibrate` runs and prints `0/7 files match`. That is expected: no
  decoders exist yet.
- docker-smoke: 16 PASS. conform: `PASS STUB`. `docs --check` passes.
- precheck on a clean clone of HEAD: 8 PASS, 0 FAIL.

## 1. Files created, renamed or changed

| area | files | change |
|---|---|---|
| A1 rename | `salvage/` → `salvagekit/` (git mv), every import, `-m` path, test, fixture, doc, Dockerfile, .dockerignore, task.py | `grep -rn "salvage\." --include=*.py` finds only `salvagekit.` imports. The phase reports 0-6 were left as written (history) |
| A2/A3 entry points | `salvage` (new, POSIX sh, LF, git mode 100755), `salvage.cmd` (new, CRLF via .gitattributes) | resolve their own folder (and symlinks), put it first on PYTHONPATH, check for Python ≥ 3.10 (clear stderr message, exit 0 otherwise), run `python3 -m salvagekit.cli` |
| A5 Docker | `Dockerfile`, `docker/entrypoint.sh`, `.dockerignore`; `docker/salvage` deleted | `WORKDIR /app` holds `./salvage`; `/salvage` is a symlink to it; the entrypoint accepts `./salvage`, `/salvage`, `salvage` or nothing before IN OUT |
| B contract | `salvagekit/core/model.py`, `plugin.py` (docstring only); `reader.py` unchanged | B1-B5 exactly as specified; validate() details in Deviations |
| C walking, naming | `salvagekit/core/walk.py`, `emit.py` | non-recursive walk; `<name>.json`; `~N` only for `report` and, on a case-insensitive output folder, case collisions (detected once per run with an exclusive probe file) |
| D mapping | `salvagekit/core/emit.py`, `report.py`, `isolate.py`, `pipeline.py`, `fallback.py`, `cli.py` | contract per-file shape and report shape, D3 statuses, `unsupported` handling, diagnostics |
| D5 schemas | `salvagekit/core/schemas/official/output.schema.json`, `report.schema.json` (new); both provisional schemas and `official/README.txt` deleted; `validate.py` | the official schemas are the only schemas; no fallback path |
| D6 shapes | `salvagekit/core/contract_shapes.py` (new) | graded fields, conditional and nullable fields, enums, graded metadata keys |
| STUB | `salvagekit/formats/stub.py`, `tests/stub/cases/*.expected.json` (golden-update stub, checked by hand) | values are CONSISTENT when the count fits, so a clean stub file is `ok`; `issues` on truncation; trailing bytes are not lossy |
| E1/E2 conformance | `tests/conformance.py`, `tests/fixtures/conform_formats/badshape.py` + its case, `_make_cases.py`, all conform_cases expectations regenerated | C1 contract names (STUB exempt, fixtures exempt); C8 allows `salvagekit.core`; new C12 record shape; samples root `kit/samples` |
| E3 samples | `tests/sample_formats.json`, `tests/core/test_samples.py` (new) | the hinted format per sample; the run on the organizers' layout |
| E4 calibrate | `tools/calibrate.py` (new), `tools/task.py`, `Makefile`, `tests/core/test_calibrate.py` (new) | `python tools/task.py calibrate [FILE]` |
| E5 tests | every `tests/core/test_*.py` that read the old shapes; new `test_contract_output.py`; fixtures `limit_formats/many.py` (records CONSISTENT) | all pipeline guarantees kept: isolation, determinism, jobs 1 vs 4, interrupts, memory cap, overwrite guards |
| tools | `tools/task.py` (check-outputs, docker-smoke, precheck, calibrate), `tools/build_docs.py` (`ebcdic_dump` after `cvt`), `tools/build_docs_intro.md` | non-recursive expectations, official schemas, new report shape, the clone's `kit/` |
| F docs | `docs/output-format.md` (rewritten), `docs/decoder-guide.md` (rewritten, 15 sections), `docs/conformance.md` (C1, C12), `docs/decoder-template.py`, `docs/spec/_TEMPLATE.md`, `docs/log/_TEMPLATE.md`, `docs/schema-notes.md` (marked superseded), `README.md`, `CLAUDE.md`, `FORMAT-SPEC.md` (generated) | |
| other | `.gitattributes` | `kit/samples/** -text`, `*.cmd eol=crlf`, `salvage eol=lf` |

## 2. Where the expected outputs decided (the priority rule)

The seven expected outputs are answer keys, not literal outputs. They
carry grader keys (`expected_damage`, `match_on`,
`optional_partial_records`) and call the file `file`.

| # | open question | what the expected outputs show | decision |
|---|---|---|---|
| 1 | top-level keys | answer keys use `file` plus grader keys | we write the contract's six keys. `source_file` is their `file`; report rows use `file`, as the contract says. calibrate compares semantically |
| 2 | `"verified": true` vs absent | none of the 61 expected records has a `verified` key | verified and consistent records carry nothing; only `"verified": false` is ever written |
| 3 | null vs missing | LIBRA-98 `due_date: null`; VAULT binary entry has no `text`; WKS `alignment` only on labels; formulas have no `value` but `cached_value` + `formula_raw_hex`; `number_format`/`iso_date` absent | a field that always applies is always written (null when empty or lost); a type-conditional field is left out when it does not apply |
| 4 | metadata beyond the graded keys | LIBRA-98, LABLOG, VAULT and WKS metadata carry extra header keys | metadata is the decoder's full header; graded keys are required for LABLOG/CVT/EBCDIC-DUMP, extra keys allowed |
| 5 | number formatting | `265.0` keeps `.0`; `2.3000000000000003` kept; `price_cents` integer but EBCDIC `balance` a float (`88.5`); `gpa` a float | values are written as computed: no rounding, ints stay ints, floats stay floats |
| 6 | damage offsets | `expected_damage` gives only `any_of` kinds and `lossy` | offset = absolute start of the damaged range; only kind and lossy are graded |
| 7 | a record cut by truncation | s04 `optional_partial_records: [{"id": 1040}]` | it may be emitted (`"verified": false`, lost fields null) or left out |
| 8 | which kinds for a short file | s04 (8 declared, 5 complete) lists only `truncated` | truncation that explains a short count is reported as `truncated` only, not also `count_mismatch` |
| 9 | value types and formats | string `isbn`/`student_id`; bool flags; `YYYY-MM-DD` dates; `YYYY-MM-DDTHH:MM:SS`, `...Z`, `YYYY-MM-DDTHH:MM` timestamps; WKS `version_code` `"0x0404"` | decoders write exactly these types (decoder guide section 8) |
| 10 | record order | `match_on` keys | records keep file order; matching is by `match_on` |

Decisions where the contract is silent and no expected output exists:

- `unrecognized` and `failed` outputs have empty metadata, records and
  damage. An unrecognized file's byte facts (size, sha256, entropy, top
  candidates) go to `diagnostics.files[].bytes`.
- An `unsupported` output keeps the decoder's metadata, records and damage.
- Archive members are not emitted; their damage is.
- Key order: contract order at the top level and in damage objects; record
  keys in field order; metadata keys sorted.

## 3. Outputs for the samples run

`./salvage kit/samples out`. The Windows host run, the Docker run, the WSL
run and the python:3.10 container run all give byte-identical report.json
files (md5 65c2d610b30628c934243cdab0d3ab8d).

`s25_random.bin.json`:

```json
{
  "source_file": "s25_random.bin",
  "format": "UNKNOWN",
  "status": "unrecognized",
  "metadata": {},
  "records": [],
  "damage": []
}
```

`s26_empty.dat.json`:

```json
{
  "source_file": "s26_empty.dat",
  "format": "UNKNOWN",
  "status": "unrecognized",
  "metadata": {},
  "records": [],
  "damage": []
}
```

`report.json`: the `files` rows are shown one per line, and only the
diagnostics entries for s25 and s26 are shown. The other 28 entries have
the same shape. The complete file (2,036 lines) is committed as
[phase-7-samples-report.json](phase-7-samples-report.json).

```json
{
  "tool_version": "0.1.0",
  "files": [
    {"file": "s01.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s02.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s03.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s04.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s05.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s06.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s07.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s08.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s09.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s10.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s11.wks", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s12.wks", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s13.wks", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s14.wpd", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s15.wpd", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s16.bravo", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s17.bravo", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s18.cvt", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s19.cvt", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s20.000", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s21.000", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s22.000", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s23.wad", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s24.pak", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s25_random.bin", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s26_empty.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s27_notes.txt", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s28_tiny.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s29_almost_libra.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0},
    {"file": "s30_png_like.dat", "format": "UNKNOWN", "status": "unrecognized", "records": 0, "damage": 0}
  ],
  "totals": {"ok": 0, "partial": 0, "unsupported": 0, "unrecognized": 30, "failed": 0},
  "diagnostics": {
    "summary": {"files": 30, "skipped": 1, "by_format": {"UNKNOWN": 30}},
    "files": [
      {
        "input": "s25_random.bin",
        "output": "s25_random.bin.json",
        "size": 300,
        "sha256": "c6b124794a1fb31ec77bbd3a5267219bf2cbd757bfc46c1e5a09d89dabfcf884",
        "status": "unrecognized",
        "format": "UNKNOWN",
        "variant": null,
        "confidence": 0.0,
        "probe_score": 0.0,
        "candidates": [
          {
            "format": "STUB",
            "score": 0.0
          }
        ],
        "attempts": [],
        "records_by_status": {
          "verified": 0,
          "consistent": 0,
          "unverified": 0,
          "lost": 0
        },
        "fields_by_status": {
          "verified": 0,
          "consistent": 0,
          "unverified": 0,
          "lost": 0
        },
        "members": 0,
        "damage": [],
        "coverage": {
          "bytes_total": 300,
          "bytes_explained": 0,
          "bytes_padding": 0,
          "explained_pct": 0.0,
          "accounted_pct": 0.0,
          "unexplained": [
            [
              0,
              300
            ]
          ],
          "unexplained_truncated": false
        },
        "bytes": {
          "size": 300,
          "sha256": "c6b124794a1fb31ec77bbd3a5267219bf2cbd757bfc46c1e5a09d89dabfcf884",
          "entropy": 7.2465,
          "entropy_sampled": false,
          "top_candidates": [
            {
              "format": "STUB",
              "score": 0.0
            }
          ]
        },
        "warnings": [],
        "errors": []
      },
      {
        "input": "s26_empty.dat",
        "output": "s26_empty.dat.json",
        "size": 0,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "status": "unrecognized",
        "format": "UNKNOWN",
        "variant": null,
        "confidence": 0.0,
        "probe_score": 0.0,
        "candidates": [
          {
            "format": "STUB",
            "score": 0.0
          }
        ],
        "attempts": [],
        "records_by_status": {
          "verified": 0,
          "consistent": 0,
          "unverified": 0,
          "lost": 0
        },
        "fields_by_status": {
          "verified": 0,
          "consistent": 0,
          "unverified": 0,
          "lost": 0
        },
        "members": 0,
        "damage": [],
        "coverage": {
          "bytes_total": 0,
          "bytes_explained": 0,
          "bytes_padding": 0,
          "explained_pct": null,
          "accounted_pct": null,
          "unexplained": [],
          "unexplained_truncated": false
        },
        "bytes": {
          "size": 0,
          "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          "entropy": 0.0,
          "entropy_sampled": false,
          "top_candidates": [
            {
              "format": "STUB",
              "score": 0.0
            }
          ]
        },
        "warnings": [],
        "errors": []
      },
      "... 28 more entries of the same shape, one per file (full file: docs/phase-reports/phase-7-samples-report.json)"
    ],
    "skipped": [{"input": "nested", "reason": "directory (not entered: the walk is non-recursive)"}],
    "warnings": [],
    "errors": []
  }
}
```

## 4. The contract_shapes table as implemented

| format | record fields (required) | conditional | nullable | enums | graded metadata |
|---|---|---|---|---|---|
| LIBRA-98 | id, title, author, year, price_cents, copies, isbn, checked_out, deleted, reference_only, due_date | - | due_date | - | - |
| LABLOG | sample, time_ms, values | - | - | - | instrument, sample_interval_ms, channels, start_time_utc, declared_block_count, events |
| VAULT | id, name, type, size, sha256, compressed | text (type text), width (type bitmap), height (type bitmap) | - | type: text/bitmap/binary | - |
| WKS | cell, row, col, type | value (not formulas), alignment (labels), number_format (cells with a number format), iso_date (date-formatted cells), cached_value (formulas), formula_raw_hex (formulas) | - | type: label/integer/number/formula/blank; alignment: left/right/center/repeat | - |
| WPD | index, type, text | - | text | type: paragraph/page_break | - |
| BRAVO | index, text | - | - | - | - |
| CVT | slot, text | - | - | metadata.structure: seq/vlir | name, structure, geos_type, modified, class_name, author, description, declared_blocks |
| EBCDIC-DUMP | student_id, name, dob, gpa, credits, status, balance | - | - | - | title, run_date, trailer_count, trailer_credits_total |
| WAD | name, offset, size, sha256 | - | - | - | - |
| PAK | name, offset, size, sha256 | - | - | - | - |

Every record may also carry `verified` and `issues`. In C12, a null in a
non-nullable field is accepted only in a record marked `"verified": false`
(a lost value). All 61 records and the metadata of the seven expected
outputs pass these shapes.

## 5. calibrate output

`python tools/task.py calibrate` (exit 1):

```text
s01.dat  13 differences
    format: expected "LIBRA-98", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.version: expected 2, got nothing (key missing)
    metadata.encoding: expected "cp437", got nothing (key missing)
    metadata.created: expected "1998-10-03T11:20:22", got nothing (key missing)
    metadata.branch_id: expected 576, got nothing (key missing)
    metadata.declared_record_count: expected 5, got nothing (key missing)
    metadata.data_offset: expected 16, got nothing (key missing)
    records[id=1002]: missing (expected {"author": "Bram Stoker", "checked_out": false, "copies": 3, "delet...)
    records[id=1009]: missing (expected {"author": "Fyodor Dostoevsky", "checked_out": true, "copies": 4, "...)
    records[id=1017]: missing (expected {"author": "F. Scott Fitzgerald", "checked_out": false, "copies": 2...)
    records[id=1021]: missing (expected {"author": "Mary Shelley", "checked_out": false, "copies": 4, "dele...)
    records[id=1028]: missing (expected {"author": "James Joyce", "checked_out": false, "copies": 4, "delet...)
s04.dat  14 differences
    format: expected "LIBRA-98", got "UNKNOWN"
    status: expected "partial", got "unrecognized"
    metadata.version: expected 2, got nothing (key missing)
    metadata.encoding: expected "cp437", got nothing (key missing)
    metadata.created: expected "1998-04-03T15:18:36", got nothing (key missing)
    metadata.branch_id: expected 1991, got nothing (key missing)
    metadata.declared_record_count: expected 8, got nothing (key missing)
    metadata.data_offset: expected 16, got nothing (key missing)
    records[id=1000]: missing (expected {"author": "Hermann Hesse", "checked_out": false, "copies": 1, "del...)
    records[id=1008]: missing (expected {"author": "Mary Shelley", "checked_out": false, "copies": 2, "dele...)
    records[id=1019]: missing (expected {"author": "James Joyce", "checked_out": false, "copies": 3, "delet...)
    records[id=1023]: missing (expected {"author": "Jane Austen", "checked_out": false, "copies": 4, "delet...)
    records[id=1033]: missing (expected {"author": "Bram Stoker", "checked_out": false, "copies": 3, "delet...)
    damage: expected a damage of kind truncated, lossy true, found none
s05.dat  31 differences
    format: expected "LABLOG", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.version: expected 1, got nothing (key missing)
    metadata.instrument: expected "THERMO LOGGER", got nothing (key missing)
    metadata.sample_interval_ms: expected 500, got nothing (key missing)
    metadata.channels: expected [{"index": 0, "unit": "mV"}, {"index": 1, "unit": "ppm"}], got nothing (key missing)
    metadata.start_time_utc: expected "1992-10-11T05:07:43Z", got nothing (key missing)
    metadata.declared_block_count: expected 7, got nothing (key missing)
    metadata.events: expected [{"message": "Sensor drift", "sample": 9, "severity": 2}, {"message..., got nothing (key missing)
    records[sample=0]: missing (expected {"sample": 0, "time_ms": 0, "values": [188.5, 600.5]})
    records[sample=1]: missing (expected {"sample": 1, "time_ms": 500, "values": [265.0, 596.0]})
    records[sample=2]: missing (expected {"sample": 2, "time_ms": 1000, "values": [260.0, 594.5]})
    records[sample=3]: missing (expected {"sample": 3, "time_ms": 1500, "values": [250.5, 593.5]})
    records[sample=4]: missing (expected {"sample": 4, "time_ms": 2000, "values": [248.5, 596.0]})
    records[sample=5]: missing (expected {"sample": 5, "time_ms": 2500, "values": [250.0, 594.0]})
    records[sample=6]: missing (expected {"sample": 6, "time_ms": 3000, "values": [246.5, 597.0]})
    records[sample=7]: missing (expected {"sample": 7, "time_ms": 3500, "values": [255.0, 592.5]})
    records[sample=8]: missing (expected {"sample": 8, "time_ms": 4000, "values": [257.5, 595.0]})
    records[sample=9]: missing (expected {"sample": 9, "time_ms": 4500, "values": [266.5, 590.0]})
    records[sample=10]: missing (expected {"sample": 10, "time_ms": 5000, "values": [262.0, 590.5]})
    records[sample=11]: missing (expected {"sample": 11, "time_ms": 5500, "values": [264.5, 599.0]})
    records[sample=12]: missing (expected {"sample": 12, "time_ms": 6000, "values": [265.5, 609.5]})
    records[sample=13]: missing (expected {"sample": 13, "time_ms": 6500, "values": [273.5, 609.0]})
    records[sample=14]: missing (expected {"sample": 14, "time_ms": 7000, "values": [263.0, 600.5]})
    records[sample=15]: missing (expected {"sample": 15, "time_ms": 7500, "values": [269.5, 597.5]})
    records[sample=16]: missing (expected {"sample": 16, "time_ms": 8000, "values": [267.5, 585.5]})
    records[sample=17]: missing (expected {"sample": 17, "time_ms": 8500, "values": [270.0, 581.5]})
    records[sample=18]: missing (expected {"sample": 18, "time_ms": 9000, "values": [264.0, 587.5]})
    records[sample=19]: missing (expected {"sample": 19, "time_ms": 9500, "values": [261.0, 594.5]})
    records[sample=20]: missing (expected {"sample": 20, "time_ms": 10000, "values": [269.0, 591.5]})
    ... and 1 more
s08.dat  8 differences
    format: expected "VAULT", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.entry_count: expected 3, got nothing (key missing)
    metadata.xor_key: expected 32, got nothing (key missing)
    metadata.flags: expected 0, got nothing (key missing)
    records[id=30574]: missing (expected {"compressed": true, "id": 30574, "name": "report.txt", "sha256": "...)
    records[id=30577]: missing (expected {"compressed": false, "id": 30577, "name": "notes.txt", "sha256": "...)
    records[id=30580]: missing (expected {"compressed": false, "id": 30580, "name": "logo.bin", "sha256": "9...)
s11.wks  25 differences
    format: expected "WKS", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.version_code: expected "0x0404", got nothing (key missing)
    metadata.declared_range: expected "A1:D5", got nothing (key missing)
    metadata.column_widths: expected {"A": 14}, got nothing (key missing)
    records[cell="A1"]: missing (expected {"alignment": "left", "cell": "A1", "col": 0, "row": 0, "type": "la...)
    records[cell="B1"]: missing (expected {"alignment": "left", "cell": "B1", "col": 1, "row": 0, "type": "la...)
    records[cell="C1"]: missing (expected {"alignment": "left", "cell": "C1", "col": 2, "row": 0, "type": "la...)
    records[cell="D1"]: missing (expected {"alignment": "left", "cell": "D1", "col": 3, "row": 0, "type": "la...)
    records[cell="A2"]: missing (expected {"alignment": "left", "cell": "A2", "col": 0, "row": 1, "type": "la...)
    records[cell="B2"]: missing (expected {"cell": "B2", "col": 1, "row": 1, "type": "integer", "value": 47})
    records[cell="C2"]: missing (expected {"cell": "C2", "col": 2, "row": 1, "type": "number", "value": 19.99})
    records[cell="D2"]: missing (expected {"cached_value": 939.53, "cell": "D2", "col": 3, "formula_raw_hex":...)
    records[cell="A3"]: missing (expected {"alignment": "left", "cell": "A3", "col": 0, "row": 2, "type": "la...)
    records[cell="B3"]: missing (expected {"cell": "B3", "col": 1, "row": 2, "type": "integer", "value": 32})
    records[cell="C3"]: missing (expected {"cell": "C3", "col": 2, "row": 2, "type": "number", "value": 19.99})
    records[cell="D3"]: missing (expected {"cached_value": 639.68, "cell": "D3", "col": 3, "formula_raw_hex":...)
    records[cell="A4"]: missing (expected {"alignment": "left", "cell": "A4", "col": 0, "row": 3, "type": "la...)
    records[cell="B4"]: missing (expected {"cell": "B4", "col": 1, "row": 3, "type": "integer", "value": 46})
    records[cell="C4"]: missing (expected {"cell": "C4", "col": 2, "row": 3, "type": "number", "value": 0.05})
    records[cell="D4"]: missing (expected {"cached_value": 2.3000000000000003, "cell": "D4", "col": 3, "formu...)
    records[cell="A5"]: missing (expected {"alignment": "left", "cell": "A5", "col": 0, "row": 4, "type": "la...)
    records[cell="B5"]: missing (expected {"cell": "B5", "col": 1, "row": 4, "type": "integer", "value": 189})
    records[cell="C5"]: missing (expected {"cell": "C5", "col": 2, "row": 4, "type": "number", "value": 19.99})
    records[cell="D5"]: missing (expected {"cached_value": 3778.1099999999997, "cell": "D5", "col": 3, "formu...)
s18.cvt  11 differences
    format: expected "CVT", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.name: expected "Notes v2", got nothing (key missing)
    metadata.structure: expected "seq", got nothing (key missing)
    metadata.geos_type: expected 7, got nothing (key missing)
    metadata.modified: expected "1991-11-19T18:29", got nothing (key missing)
    metadata.class_name: expected "Text Scrap", got nothing (key missing)
    metadata.author: expected "S. Sam", got nothing (key missing)
    metadata.description: expected "Memo scrap", got nothing (key missing)
    metadata.declared_blocks: expected 4, got nothing (key missing)
    records[slot=0]: missing (expected {"slot": 0, "text": "Dear Diary,\nDisk 2 holds Maps (v1.2) & Fonts;...)
s20.000  11 differences
    format: expected "EBCDIC-DUMP", got "UNKNOWN"
    status: expected "ok", got "unrecognized"
    metadata.title: expected "STUDENT EXTRACT", got nothing (key missing)
    metadata.run_date: expected "1999-03-14", got nothing (key missing)
    metadata.trailer_count: expected 5, got nothing (key missing)
    metadata.trailer_credits_total: expected 402, got nothing (key missing)
    records[student_id="909014"]: missing (expected {"balance": 698.36, "credits": 40, "dob": "1978-10-11", "gpa": 2.63...)
    records[student_id="935798"]: missing (expected {"balance": 875.42, "credits": 74, "dob": "1983-10-27", "gpa": 3.7,...)
    records[student_id="908015"]: missing (expected {"balance": 88.5, "credits": 82, "dob": "1986-10-02", "gpa": 1.62, ...)
    records[student_id="683591"]: missing (expected {"balance": 490.59, "credits": 84, "dob": "1987-08-16", "gpa": 2.68...)
    records[student_id="796852"]: missing (expected {"balance": 762.09, "credits": 122, "dob": "1982-08-11", "gpa": 2.5...)
calibrate: 0/7 files match
```

## 6. Minimum Python version

**3.10.** Verified by running the whole suite in `python:3.10-slim` (pulled
during dev). The source was mounted read-only, with
`python3 -m unittest discover -s tests -t .`: 339 tests, OK (24 skipped,
all sample-format checks for decoders that do not exist yet). Nothing
needed 3.11+, so nothing was changed. `./salvage` and `salvage.cmd` check
`sys.version_info >= (3, 10)`. In the 3.10 container, `./salvage` was also
run four ways, each exiting 0:
- from the repo root;
- from another directory;
- through a symlink;
- with no `python3` on PATH, or a fake 3.8 `python3`: both print a clear
  error.

## 7. Test totals

| where | result |
|---|---|
| Windows, Python 3.12.2 (`python tools/task.py test`) | 339 tests, OK, 29 skipped (24 sample-format checks without a decoder; 5 that need POSIX or symlink rights: memory cap, SIGTERM to the CLI, FIFO, symlinks, case-sensitive names) |
| `docker-test` (image Python 3.12, Linux) | 339 tests, OK, 24 skipped (sample-format checks) |
| python:3.10-slim container | 339 tests, OK, 24 skipped (sample-format checks) |
| conform (full mode) | `PASS STUB 2 inputs, 82 variants, 0 warnings` |
| docker-smoke | 16 PASS, 0 FAIL (host vs `./salvage`, `/salvage`, and no-command runs: byte-identical) |
| precheck (clean clone of 5e95b3d) | 8 PASS, 0 FAIL in 43.2 s |

precheck summary:

| # | step | result | seconds |
|---|------|--------|--------:|
| 1 | test | PASS | 34.2 |
| 2 | conform (full) | PASS | 0.7 |
| 3 | docs --check | PASS | 0.2 |
| 4 | lint-docker | PASS | 0.1 |
| 5 | build --no-cache --network none | PASS | 2.2 |
| 6 | docker run on kit/samples/ + HINTS.md | PASS | 1.2 |
| 7 | docker run on golden inputs | PASS | 0.8 |
| 8 | docker-smoke | PASS | 3.3 |

The suite went from 301 to 339 tests. New test files:
`test_contract_output.py` (10), `test_calibrate.py` (7), `test_samples.py`
(5). New tests in existing files cover:
- C12 and contract names (3 in the conformance selftest);
- the case probe and the naming rules;
- the B5 model checks;
- the schema status rules;
- report rows and totals;
- subfolder skipping;
- count mismatch in the template.

Tests that covered recursion now prove that subfolders are skipped.

## 8. Deviations

1. **The kit lives in `kit/`, not `samples/`.** Commit 7322242 moved the
   samples, hints, contract and expected outputs to `kit/samples/`,
   `kit/HINTS.md`, `kit/OUTPUT-CONTRACT.md` and `kit/expected_outputs/`.
   Everything the task calls `samples/` uses `kit/samples/`. Because
   `HINTS.md` is no longer inside the samples folder, the samples test and
   precheck rebuild the organizers' layout: kit/samples/ plus HINTS.md,
   31 top-level files. A plain `./salvage kit/samples out` gives 30
   outputs.
2. **`source_file`, not `file`, in per-file outputs.** The expected outputs
   are answer keys, so their key set cannot be the output's. The contract
   names `source_file`, so we keep it, and calibrate maps `file` to it.
3. **B5 read slightly wider.** validate() also refuses the field names
   `verified` and `issues`, which would clash with the keys the output
   adds. It also refuses a non-string name, a non-list `issues`, and a
   non-bool `lossy` or `unsupported`.
4. **An `unsupported` result stops the candidate loop** (attempt outcome
   `unsupported`), even with no records. Otherwise it would count as
   "empty" and the next candidate would be tried.
5. **The STUB decoder changed** (values CONSISTENT when the count fits;
   `issues` on truncation; trailing bytes `lossy=False`). Without this a
   clean stub file would be `partial`, because D3 counts UNVERIFIED as
   partial. The `limit_formats/many.py` fixture records are CONSISTENT for
   the same reason, so the caps test still proves "capped ok → partial".
6. **Output key order is no longer sorted.** It is the contract order;
   record keys follow field order, and metadata and dict values are
   key-sorted. That keeps determinism without depending on how a decoder
   built a dict.
7. **The output schema also encodes two status rules**, beyond pure shape:
   `unrecognized` ⇒ `UNKNOWN` with nothing decoded; `ok` ⇒ no damage and no
   `"verified": false` record. A decoder output that breaks them is
   replaced by a `failed` output, as for any schema violation.
8. **Top-level symlinks are still skipped** (listed in diagnostics), as
   before Phase 7, even though the contract says "every file". Following
   links is unsafe.
9. **`report.json` is abridged in section 3.** The full file is committed
   next to this report.
10. **The decoder template was restructured**, beyond F4's "names and
    kinds". Header values went to `meta`, records became `{index, text}`,
    and a CRC mismatch now gives `issues` plus non-lossy damage, with a
    `count_mismatch` example. The template must teach the shape C12
    checks.
11. **The decoder guide was renumbered** (new sections 8 record shapes,
    9 unsupported, 13 calibrate). The section numbers in conformance
    messages were updated.
12. **`tests/sample_formats.json` wraps the map** as
    `{"_comment", "formats"}`.
13. **precheck now has two Docker run steps.** One runs on kit/samples/ +
    HINTS.md, the other on the golden inputs. The non-recursive walk means
    golden inputs can no longer sit in subfolders, so they are copied flat
    as `<format>-<name>`.
14. **Docker `WORKDIR` is `/app`** (was `/work`), as A5 asks. Relative
    paths given to `docker run` now resolve from `/app`.
15. **`./salvage` uses `exec`**, so SIGTERM/SIGINT reach Python directly,
    as before. Its exit status is the CLI's (always 0); only a python3
    killed by a signal could end non-zero.
16. **`tool_version` stays `0.1.0`.** It was not bumped; that was not asked.

## 9. Not done

- No format decoders exist yet, so calibrate is 0/7. In the samples test,
  24 sample-format checks are skipped with "no <FORMAT> decoder yet", as
  E3 asks.
- Python versions below 3.10 were not tried (A4 sets the floor at the
  first version that passes).
- The phase reports 0-6 still name `salvage/...` paths. They are
  historical and were not edited.
