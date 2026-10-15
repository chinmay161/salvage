# Phase 3 report: identification fields, schema validation, coverage, resync, limits, decoder guide

**Status:** done. Every "done when" check passed:

- `python tools/task.py test` passes 220 tests on Windows (2 skipped).
- `docker-test` passes 220 tests inside the image (0 skipped).
- `docker-smoke` passes all 8 checks. The host and container outputs are byte-identical.
- Every output in the test_pipeline folder validates against the provisional schemas (`test_every_output_validates`).
- The decoder template test passes (`tests/core/test_decoder_template.py`, 8 tests).

The contract files `model.py`, `plugin.py` and `reader.py` are unchanged.

## 1. Files created or changed

**New core modules**
- `salvage/core/jsonschema_lite.py` (B1): the validator. It provides `Schema`, `load_schema`, `SchemaError` and `UnsupportedSchema`.
- `salvage/core/validate.py` (B2): picks the active schema, exposes `active()`, `version()`, `errors()` and `load_problems()`, and the configurable `SCHEMA_FILES`. `python -m salvage.core.validate` prints which schemas are active.
- `salvage/core/coverage.py` (C): `coverage(reader)`.
- `salvage/core/resync.py` (D): `ByteView`, `resync`, `ResyncResult` and `resync_damage`.
- `salvage/core/caps.py` (E): `enforce(result)` cuts the record and member lists to the limits.

**New schema files** (inside `salvage/`, so they ship in the image)
- `salvage/core/schemas/output.provisional.json`
- `salvage/core/schemas/report.provisional.json`
- `salvage/core/schemas/official/README.txt`

**Changed core**
- `salvage/core/limits.py`: adds `MAX_RECORDS`, `MAX_MEMBERS`, `MAX_DECOMPRESSED`, `MAX_RESYNC_SCAN` and `within()`, each with a comment.
- `salvage/core/emit.py`: the output gets `variant`. `schema_version` now comes from the active output schema.
- `salvage/core/report.py`: the entry gets `variant`, `probe_score` and `coverage`. The report's `schema_version` now comes from the active report schema.
- `salvage/core/isolate.py`:
  - New `process_data()`: the worker-side core, usable in-process. `process_file()` now reads the file, discovers the decoders and calls it.
  - New `decoded_identity()` (Part A).
  - New `_try_candidates()`, which also returns the kept attempt's SafeReader. `try_candidates()` keeps its old 3-value signature.
  - The caps and coverage are applied in the worker.
- `salvage/core/pipeline.py`:
  - New `checked_output()`: validates each per-file output and swaps in a "failed" replacement if it is invalid.
  - New `_check_report()`: validates report.json; on failure it adds a run-level error and prints to stderr.
  - Schema load problems are added to the run-level errors.

**Tests**
- New: `tests/core/test_jsonschema_lite.py`, `test_validate.py`, `test_coverage.py`, `test_resync.py`, `test_caps.py` and `test_decoder_template.py`.
- New fixture package `tests/fixtures/limit_formats/` with `many.py` (T-MANY: 23 records, 6 nested members).
- `tests/core/test_pipeline.py`: new tests that every output validates, for the identification fields and for coverage.
- `tests/stub/cases/*.expected.json`: regenerated (section 2).

**Docs**
- `docs/decoder-guide.md` (F1).
- `docs/decoder-template.py` (F2).
- `docs/output-format.md`: documents `variant`/`confidence`/`probe_score`, coverage, limits, schema validation and `schema_version`.
- `CLAUDE.md`: adds the `python -m salvage.core.validate` command and a "Decoders" section that points to the guide.
- `docs/phase-reports/phase-3.md`: this file.

## 2. Part A: stub golden diffs

I ran `python tools/task.py golden-update stub`: 3 changed, 0 added. I checked each diff by hand. In all three files the **only** change is one added key:

| file | change |
|---|---|
| `clean.stub.expected.json` | `+ "variant": null` |
| `truncated.stub.expected.json` | `+ "variant": null` |
| `wrong_magic.bin.expected.json` | `+ "variant": null` |

`confidence` did not change. STUB's decoder confidence (1.0) equals its probe score (1.0), and `wrong_magic.bin` is `unknown` (0.0 before and after). `schema_version` is still `"provisional-1"`.

## 3. Supported schema keywords and load_schema results

**Supported:**
- `type`: single type or a list of types, with `integer` and `number` kept apart
- object keywords: `properties`, `required`, `additionalProperties` (boolean or schema)
- array keywords: `items` (single schema), `prefixItems`, `minItems`, `maxItems`, `uniqueItems`
- `enum`, `const`
- number keywords: `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum` (numeric form)
- string keywords: `minLength`, `maxLength`, `pattern` (`re.search`)
- combinators: `anyOf`, `oneOf`, `allOf`, `not`
- references: `$ref` (local only), `$defs`, `definitions`
- annotations, not enforced: `$schema`, `$id`, `title`, `description`, `default`, `examples`, `$comment`, `format`

Boolean schemas (`true`/`false`) are supported too.

**Refused at load:**
- Any other keyword raises `UnsupportedSchema`, which lists every such keyword with its JSON-pointer location, for example `#/properties/a/patternProperties: patternProperties`.
- The array form of `items`, the boolean form of `exclusiveMinimum`/`exclusiveMaximum` and non-local `$ref` are also reported as unsupported.
- A malformed keyword value, an unresolvable `$ref` or a `$ref` loop that never descends into the instance raises `SchemaError`.

**JSON rules:**
- `true`/`false` are not numbers.
- `1.0` counts as an integer.
- `1 == 1.0` but `true != 1`, in `enum`, `const` and `uniqueItems`.

**load_schema on both provisional schemas** (`python -m salvage.core.validate`, the same on Windows and in the image):

```
output: provisional output.provisional.json (loaded), schema_version 'provisional-1'
report: provisional report.provisional.json (loaded), schema_version 'provisional-1'
```

Both load with no problems. Both use `additionalProperties: false` on every object and list every enum: file status, trust status and damage kind. Their `required` lists are complete. The outcome pattern in `attempts` is `^(ok|empty|(invalid|error): ...)$`.

## 4. report.json entry for the truncated stub

This comes from `tests/stub/cases/truncated.stub`: count 5, two complete values, then 2 stray bytes.

```json
{
  "attempts": [{"format": "STUB", "outcome": "ok"}],
  "candidates": [{"format": "STUB", "score": 1.0}],
  "confidence": 1.0,
  "coverage": {
    "accounted_pct": 92.0,
    "bytes_explained": 23,
    "bytes_padding": 0,
    "bytes_total": 25,
    "explained_pct": 92.0,
    "unexplained": [[23, 25]],
    "unexplained_truncated": false
  },
  "damage": [{"end": 25, "kind": "truncated",
              "reason": "expected 5 values, file ends after 2", "start": 23}],
  "errors": [],
  "fields_by_status": {"consistent": 0, "lost": 0, "unverified": 3, "verified": 1},
  "format": "STUB",
  "input": "truncated.stub",
  "members": 0,
  "output": "truncated.stub.json",
  "probe_score": 1.0,
  "records_by_status": {"consistent": 0, "lost": 0, "unverified": 3, "verified": 0},
  "sha256": "b8462380dededcaedb867a7b2859b75f8bdca3cc2a950065764d8234333956dd",
  "size": 25,
  "status": "partial",
  "variant": null,
  "warnings": ["truncated at offset 23: expected 5 values, file ends after 2"]
}
```

The 2 stray bytes are unexplained because the failed `u32le` read claims nothing. They are also the reported damage range.

## 5. Validation timing on the 40,000-record output

The document is the real `big.t.json` from the T-BIG fixture: 40,000 records, 15.5 MB on disk. I validated it against the provisional output schema 5 times on each system:

| where | best | worst |
|---|---|---|
| Windows (Python 3.12.2) | 0.193 s | 0.201 s |
| Docker (python:3.12-slim) | 0.199 s | 0.212 s |

The test `SpeedTests.test_40000_record_output_under_2s` checks the 2 s bound.

**Why it is fast:** the schema is compiled once into closures, and JSON paths are built only when an error is reported.

## 6. Test totals

| where | command | result |
|---|---|---|
| Windows (host, Python 3.12.2) | `python tools/task.py test` | `Ran 220 tests in 18.8s`, `OK (skipped=2)` |
| Linux (image) | `python tools/task.py docker-test` | `Ran 220 tests in 20.3s`, `OK` |

**Where the new tests are:** Phase 2 had 138 tests; Phase 3 adds 82.

| test file | tests |
|---|---|
| test_jsonschema_lite | 25 |
| test_validate | 18 |
| test_resync | 11 |
| test_caps | 9 |
| test_coverage | 8 |
| test_decoder_template | 8 |
| test_pipeline | 3 |

The 2 Windows skips are the same as in Phase 2: FIFOs and symlinks.

`docker-smoke` passed all 8 checks after a `build-offline`.

## 7. Table of contents of docs/decoder-guide.md

1. Where your files go
2. The Decoder class
3. SafeReader
4. Statuses: verified / consistent / unverified / lost
5. Damage
6. Recovering from damage with resync
7. Archives
8. variant and confidence
9. Running your decoder alone
10. Golden tests
11. FIELD-LOG entries
12. Before opening a pull request

## 8. Deviations

1. **The template's "100% coverage" is checked as `accounted_pct` = 100 with no unexplained bytes.** F2 requires the template to show padding. Its 8 zero header bytes are labelled `"padding"`, so on the clean file `explained_pct` is 83.33 (40 of 48 bytes) and `accounted_pct` is 100.0. The test checks `accounted_pct == 100`, `unexplained == []`, `bytes_padding == 8` and `bytes_explained == size - 8`. The STUB clean file has no padding and is checked at `explained_pct` 100.0 (C).
2. **Percentages are 0 to 100, not 0 to 1.** They are rounded with `round(x, 2)` and are null for an empty file.
3. **`variant` is set only for decoded/partial files.**
   - A `DecodeResult.format` that is not a string, or is empty, gives `null`.
   - A confidence that is not a number gives 0.0. Core's result check already rejects this, so the case cannot actually happen.
4. **An official schema that cannot be used falls back to the provisional one.** "Unusable" means unreadable, or using an unsupported keyword. Its problems become a run-level error in every run.
   - The other options were to validate nothing, or to fail every file because of a schema problem. Falling back keeps checking the shape we actually write, and the problem is still loud.
   - If even the provisional schema cannot be loaded, documents are not validated and a run-level error says so. A test checks that this never happens with the shipped files.
5. **`schema_version` comes from the active schema in both document kinds.** The task named only report.json. Per-file outputs follow the active output schema in the same way.
   - The official version string is `"official"`, because we do not know the organizers' version naming.
6. **The official file names are a guess, and the setting is in validate.py.** The names are `official/output.schema.json` and `official/report.schema.json`. They are set in `validate.SCHEMA_FILES`, not in limits.py, because limits.py holds resource limits.
7. **`$ref` support is wider than the task asked.**
   - `$ref` accepts any local JSON pointer (`#`, `#/...`), not only `#/$defs/...` and `#/definitions/...`. Non-local refs are refused at load.
   - Keywords next to a `$ref` are applied too (2020-12 behaviour). Draft-07 ignores them.
8. **The validator does more load-time checking than asked.**
   - Malformed keyword values and `$ref` loops that would recurse forever raise `SchemaError` at load. So `Schema.errors()` can never fail because of the schema.
   - An instance nested too deeply to validate is reported as an error at `$`, not raised.
   - Python tuples count as arrays.
9. **The replacement output carries no warnings.** The decoder's warnings might be the invalid part, so the replacement's `warnings` is `[]`.
   - Its `errors` has one header line plus up to 10 validation errors, so at most 11 lines.
   - The report entry is changed to match: status `failed`, zero counts, `coverage` null, and the same errors added.
10. **A report validation failure shows twice on stderr in a CLI run.** The pipeline prints it so library callers see it, and the CLI prints all run-level errors as well. The report holds it once.
11. **Caps.**
    - Members are cut first, then records, both depth first.
    - A capped file is `partial` even with no damage. Only a warning is added, not a `Damage`, because a cap has no byte range.
    - The limits are read at call time, so tests can patch them.
12. **Coverage for `unknown` files comes from an unused reader.** So the whole file is unexplained. An empty unknown file gets null percentages.
13. **The template test runs in-process, not through `pipeline.run`.** It uses `isolate.process_data`, the same worker-side function `process_file` uses: probe, attempts, caps, coverage and output building.
    - `pipeline.run`'s worker finds decoders by package name, and the template is deliberately outside any package.
    - The test also runs the template standalone in a subprocess.
14. **`resync` argument handling.**
    - `start` is clamped to [0, size].
    - A `step` below 1 or not an int becomes 1.
    - A `max_scan` that is invalid uses the default.
    - The offset equal to the file size is never a candidate.
    - A callback that raises `SystemExit` also counts as False, as in `safe_probe`.
15. **The template's strict resync check skips bad-checksum records inside junk.** Its check requires a matching CRC, so a bad-CRC record sitting inside junk is reported as `UNPARSED`. A bad-CRC record right after a good one is still decoded and gets `CHECKSUM` damage. The guide explains this trade-off.
16. **`limits.within` returns False for bools** (`within(True, 5)` is False), as for the rest of the code base.
17. **I edited `CLAUDE.md`** (lead-owned): one command line and a "Decoders" section.

## 9. Not done

- **The real official schema has not been tried.** None has arrived. The fallback and override paths are tested with temporary schemas.
- **The archive example in the guide is not run by any test.** This is the `MAX_DECOMPRESSED` / `zlib` snippet. F2's list for the template does not include archives, so the template has no members. The members path through core (caps, counts, validation of nested members) is tested with the T-MANY fixture.
- **No `make` target for `python -m salvage.core.validate`.** `make` is not installed here, and the task did not ask for one.
- **Nothing was committed.**
