# Output format

Salvage writes exactly what the organizers' output contract
([kit/OUTPUT-CONTRACT.md](../kit/OUTPUT-CONTRACT.md)) asks for, plus one
extra key in `report.json`: `diagnostics`, which holds everything else we
know about the run. Where the contract is silent, the reference answers in
[kit/expected_outputs/](../kit/expected_outputs/) decide; every such
decision is listed under [Expected-output decisions](#expected-output-decisions).

Only `salvagekit/core/emit.py` (per-file shape, file names) and
`salvagekit/core/report.py` (report shape, file status) know these shapes.
They are written down as JSON Schemas in
`salvagekit/core/schemas/official/` (`output.schema.json`,
`report.schema.json`), and every document is validated against them before
it is written (see [Schema validation](#schema-validation)).

All output files are UTF-8 with LF line endings, indented JSON (2 spaces)
plus a final newline, written atomically (`<name>.tmp`, then rename).
There are no timestamps, durations, PIDs or absolute paths, so the same
input bytes give the same output bytes on every OS and with any `--jobs`.

## Running

```sh
./salvage <input_dir> <output_dir>
```

- Only the **regular files directly in `input_dir`** are processed. The walk
  is non-recursive: subfolders are never entered; they are listed in
  `report.json` diagnostics (`skipped`), like symlinks, FIFOs, devices and
  sockets, which are never opened.
- The exit status is always 0, also for bad arguments or a missing input
  folder; problems go to `report.json` and stderr.
- stdout gets one summary line; stderr gets one line per file,
  `<status> <format> <file>`, in completion order, plus run-level errors.

## Output file names

| Input file | Output file | Rule |
|------------|-------------|------|
| `s01.dat` | `s01.dat.json` | the contract: exactly `<input file name>.json` |
| `report.json` | `report.json.json` | |
| `report` | `report~2.json` | `report.json` is reserved for the report |
| `A.dat`, `a.dat` | `A.dat.json`, `a.dat.json` | case-sensitive output folder (Linux): exact names |
| `A.dat`, `a.dat` | `A.dat.json`, `a.dat~2.json` | case-insensitive output folder (Windows, macOS, some bind mounts): names compared with `casefold()`; `~2`, `~3`, ... in sorted input order |

Whether the output folder is case-insensitive is checked once per run: a
probe file is created there exclusively (never overwriting anything),
looked up with its case swapped, and removed. If the folder cannot be
probed it counts as case-insensitive (the safe side: an extra `~2`, never
an overwrite).

An output that would overwrite an input file (input and output folder are
the same) is not written; its diagnostics entry gets `"output": null` and
an error. An output path that is an existing folder is an error too; the
run continues.

## Per-file output: `<input file name>.json`

Exactly six keys, in this order:

```json
{
  "source_file": "s04.dat",
  "format": "LIBRA-98",
  "status": "partial",
  "metadata": {"branch_id": 1991, "version": 2},
  "records": [
    {"id": 1000, "title": "Siddhartha", "due_date": null},
    {"id": 1040, "title": null, "verified": false, "issues": ["truncated"]}
  ],
  "damage": [
    {"kind": "truncated", "offset": 240, "detail": "record 5 runs past the end", "lossy": true}
  ]
}
```

| key | value |
|-----|-------|
| `source_file` | the input file name |
| `format` | the decoder's name: `LIBRA-98`, `LABLOG`, `VAULT`, `WKS`, `WPD`, `BRAVO`, `CVT`, `EBCDIC-DUMP`, `WAD`, `PAK`, or `UNKNOWN` when no decoder recognized the file (test-only decoders such as `STUB` keep their own names) |
| `status` | `ok`, `partial`, `unsupported`, `unrecognized` or `failed` (below) |
| `metadata` | the decoder's `DecodeResult.meta`; `{}` when there is none (always for `unrecognized` and `failed`). Its keys are sorted |
| `records` | one flat object per top-level record (below) |
| `damage` | `{"kind", "offset", "detail", "lossy"}` per damaged range, archive members included |

### `status`: exactly one per file

| status | when |
|--------|------|
| `ok` | decoded; no damage, and no record or field is `unverified` or `lost` (members included) |
| `partial` | decoded, but with any damage, anything `unverified` or `lost`, or the output was capped (see [Limits](#limits)) |
| `unsupported` | the decoder recognized the file but cannot decode it: `DecodeResult.unsupported` is true (e.g. password-protected). Records may be empty; the damage should include `encrypted` when that is the reason |
| `unrecognized` | no decoder's probe reached 0.5. `format` is `UNKNOWN`; metadata, records and damage are empty |
| `failed` | identified, but every attempt errored or was invalid, or it timed out, crashed or ran out of memory; or the file is too large, unreadable or disappeared. `format` is the identified decoder, or `UNKNOWN` if the file failed before identification finished; metadata, records and damage are empty |

The reason for a `failed` file is in its diagnostics entry (`errors`):

| error | meaning |
|-------|---------|
| `timeout after 20s (during probe)` / `(during decode)` | the worker was killed at the deadline; "during probe" covers everything before identification finished |
| `worker crashed with exit code N (during decode)` | the worker process died |
| `too large (N bytes > M)` | over `MAX_FILE_BYTES`; hashed but never decoded |
| `file disappeared` | deleted between the folder walk and the read |
| `cannot read file: <reason>` | could not be opened or read |
| `memory limit (2048 MiB)` | a candidate ran out of memory under the worker cap (POSIX) and no candidate succeeded |
| `no candidate decoder produced a valid result` | every candidate errored or returned an invalid result |

### `records`

Each `Record` becomes one object `{field.name: field.value}`, in field
order, then:

- `"verified": false` if the record's status, or any of its fields'
  statuses, is `unverified` or `lost`. Verified and consistent records
  carry no `verified` key (never `"verified": true`).
- `"issues": ["crc_mismatch", ...]` if `Record.issues` is not empty (the
  damage kinds that affect this record; duplicates removed).

Field names are the contract's record keys (per format:
[`salvagekit/core/contract_shapes.py`](../salvagekit/core/contract_shapes.py)),
so they must be unique within a record and never `verified` or `issues`;
`DecodeResult.validate()` refuses a result that breaks this. Values are
written in their final form (ISO dates, integer cents, `null` for a lost
value); bytes become lowercase hex; dict values have sorted keys.

**Archives** (VAULT, WAD, PAK): each archive entry is a record
(`name`, `offset`, `size`, `sha256`, ... per the contract). Decoders may
still put a decoded entry in `DecodeResult.members` (a nested result);
members' records are **not** emitted, but their damage is (it uses absolute
offsets in the outer file), their records count for the file's status, and
their counts appear in the diagnostics.

### `damage`

`Damage(start, end, kind, reason, lossy)` maps to
`{"kind": kind, "offset": start, "detail": reason, "lossy": lossy}`. The
end of the range stays in the diagnostics. `kind` is exactly the contract's
vocabulary:

| kind | the bytes ... |
|------|---------------|
| `truncated` | end before the structure does (the file ends early) |
| `crc_mismatch` | fail a CRC check |
| `checksum_mismatch` | fail another checksum (sum, xor, Fletcher, ...) |
| `header_checksum` | are a header whose checksum does not match |
| `bad_length` | hold a length that cannot be right |
| `count_mismatch` | hold a count that disagrees with what was found |
| `oob_pointer` | hold an offset/pointer outside the file or its container |
| `index_missing` | should hold an index/directory that is missing or unreadable |
| `invalid_value` | hold a value outside its allowed range |
| `unknown_record` | are a record of a type the decoder does not know |
| `unparsed_bytes` | were skipped (junk, resync gaps, trailing bytes) |
| `encrypted` | are encrypted and cannot be read |

`lossy` is true when data was lost (the default), false when everything
was still recovered (e.g. a CRC mismatch over text that was kept, or
trailing bytes after a complete file). Which kind to use when: the
[decoder guide](decoder-guide.md#5-damage).

## `report.json`

Written last, in the output root, also after a failure midway or an
interrupt.

```json
{
  "tool_version": "0.1.0",
  "files": [
    {"file": "s01.dat", "format": "LIBRA-98", "status": "ok", "records": 5, "damage": 0}
  ],
  "totals": {"ok": 1, "partial": 0, "unsupported": 0, "unrecognized": 0, "failed": 0},
  "diagnostics": {
    "summary": {"files": 1, "skipped": 1, "by_format": {"LIBRA-98": 1}},
    "files": [ ... one entry per file, below ... ],
    "skipped": [{"input": "nested", "reason": "directory (not entered: the walk is non-recursive)"}],
    "warnings": ["output dir was not empty: 3 existing files"],
    "errors": ["run-level errors, e.g. decoder import errors"]
  }
}
```

- `files`: one row per processed file, in walk order (names sorted).
  `records` and `damage` are the lengths of that file's `records` and
  `damage` lists.
- `totals`: a count for every status, zeros included.
- `diagnostics` is our only extra key; nothing extra goes in the per-file
  outputs.

### `diagnostics`

| key | value |
|-----|-------|
| `summary` | `files` (rows), `skipped` (entries), `by_format` (rows per format) |
| `files` | one entry per processed file, same order as `files` (below) |
| `skipped` | subfolders (never entered), symlinks, FIFOs, devices, sockets, unreadable entries: `{"input", "reason"}` |
| `warnings` | run level: `"output dir was not empty: N existing files"` (counted recursively before the run; nothing is deleted, our own outputs are overwritten) |
| `errors` | run level: missing/unreadable input folder, decoder import errors, a failed report write, an unusable schema, a report that fails validation, internal errors, `"interrupted: N files not processed"` |

A diagnostics entry:

```json
{"input": "s04.dat", "output": "s04.dat.json", "size": 259, "sha256": "<hex>",
 "status": "partial", "format": "LIBRA-98", "variant": null,
 "confidence": 1.0, "probe_score": 1.0,
 "candidates": [{"format": "LIBRA-98", "score": 1.0},
                {"format": "OTHER", "score": 0.0, "error": "probe raised ..."}],
 "attempts": [{"format": "LIBRA-98", "outcome": "ok"}],
 "records_by_status": {"verified": 5, "consistent": 0, "unverified": 0, "lost": 1},
 "fields_by_status":  {"verified": 55, "consistent": 0, "unverified": 0, "lost": 10},
 "members": 0,
 "damage": [{"start": 240, "end": 259, "kind": "truncated", "reason": "...", "lossy": true}],
 "coverage": {"bytes_total": 259, "bytes_explained": 259, "bytes_padding": 0,
              "explained_pct": 100.0, "accounted_pct": 100.0,
              "unexplained": [], "unexplained_truncated": false},
 "bytes": null,
 "warnings": [], "errors": []}
```

| key | value |
|-----|-------|
| `input`, `output` | file names; `output` is null if it could not be written |
| `size`, `sha256` | of the input (`sha256` null only if unreadable); files over `MAX_FILE_BYTES` are still hashed, streamed in 1 MiB chunks |
| `status`, `format` | as in the per-file output |
| `variant` | the decoder's `DecodeResult.format` when it differs from its name (a sub-version, e.g. `"WPD 5.1"`), else null |
| `confidence` | decoded files: the decoder's post-decode confidence (0-1); otherwise the probe score |
| `probe_score` | the chosen candidate's probe score (0.0 if none) |
| `candidates` | every decoder's probe, by score then name; `error` only if the probe misbehaved |
| `attempts` | `ok`, `unsupported`, `empty`, `invalid: <first 3 problems>`, `error: <Type>: <message>` or `error: memory limit` |
| `records_by_status`, `fields_by_status`, `members` | counts, archive members included |
| `damage` | full byte ranges `[start, end)` with kind, reason, lossy |
| `coverage` | below; null for failed files |
| `bytes` | `unrecognized` files only: `{size, sha256, entropy (bits/byte, 4 decimals), entropy_sampled, top_candidates (best 3)}`; files over 4 MB are measured on the first 1 MB + middle 2 MB + last 1 MB. Nothing is carved or guessed |
| `warnings` | the decoder's warnings, core warnings (`"output capped at N records"`), pipeline warnings (`"ambiguous: A, B"`) |
| `errors` | why the file failed, or `"cannot write output: <reason>"` |

**Identification.** A decoder is a candidate when its probe scores at
least 0.5. Candidates within 0.1 of the best are ordered by the extension
hint, then by name; the rest follow by score. The first candidate whose
result is valid and not empty wins; an `unsupported` result also wins. If
every candidate returns an empty result, the first one is used.

### `coverage`

How much of the file the decoder's reads explained, from the SafeReader of
the attempt whose result was emitted:

| key | meaning |
|-----|---------|
| `bytes_total` | file size |
| `bytes_explained` | bytes claimed by any read whose label is not `"padding"` |
| `bytes_padding` | bytes claimed ONLY by `"padding"` reads |
| `explained_pct` | 100 × explained / total, 2 decimals; null for an empty file |
| `accounted_pct` | 100 × (explained + padding) / total, 2 decimals; null for an empty file |
| `unexplained` | merged `[start, end)` ranges never claimed, at most 100 |
| `unexplained_truncated` | true if there were more than 100 such ranges |

Unrecognized files: nothing is explained. Probing with
`salvagekit.core.resync.ByteView` claims nothing, so it never counts.

## Expected-output decisions

The kit's expected outputs (s01, s04, s05, s08, s11, s18, s20) are
**answer keys**, not literal outputs: they carry grader keys
(`expected_damage`, `match_on`, `optional_partial_records`) and call the
file `file`. Where they and the contract differ, or the contract is silent,
they decided:

| # | question | the expected outputs show | our decision |
|---|----------|---------------------------|--------------|
| 1 | top-level keys of a per-file output | answer keys use `file` and grader keys | we emit the contract's six keys; our `source_file` is their `file` (and `report.json` rows use `file`, as the contract says). `python tools/task.py calibrate` compares semantically |
| 2 | `"verified": true` or nothing on verified records | none of the 61 expected records has a `verified` key | verified/consistent records carry nothing; only `"verified": false` is ever written |
| 3 | null vs missing | LIBRA-98 `due_date: null` when not checked out; VAULT binary entries have no `text`; WKS `alignment` only on labels, formulas have no `value` but `cached_value` + `formula_raw_hex`, `number_format`/`iso_date` absent when not applicable | a field that always applies is written, `null` when it has no value; a type-conditional field is left out when it does not apply (`contract_shapes.py`: required / conditional / nullable) |
| 4 | metadata beyond the graded keys | LIBRA-98 (`version`, `encoding`, `created`, `branch_id`, `declared_record_count`, `data_offset`), LABLOG (`version`), VAULT (`entry_count`, `xor_key`, `flags`), WKS (`version_code`, `declared_range`, `column_widths`) | metadata is the decoder's full header in final form; the contract's metadata keys must be present for LABLOG, CVT, EBCDIC-DUMP, extra keys are allowed |
| 5 | number formatting | whole floats keep `.0` (`265.0`); float artefacts kept (`2.3000000000000003`, `3778.1099999999997`); money as integer cents in LIBRA-98 (`price_cents`) but as a float in EBCDIC-DUMP (`balance: 88.5`); `gpa` a float | values are Python numbers written by `json` as computed: never rounded or reformatted; ints stay ints, floats stay floats |
| 6 | damage offsets and details | `expected_damage` gives only `any_of` kinds and `lossy` | only kind and lossy are graded; we write `offset` = the absolute start of the damaged range and a human `detail` |
| 7 | a record cut off by truncation | s04: `optional_partial_records: [{"id": 1040}]` | a partly recovered record may be emitted (with `"verified": false`, lost fields `null`) or left out; both match |
| 8 | which kinds for a short file | s04 (declares 8 records, 5 complete): only `truncated`, lossy | when truncation explains a short count, report `truncated` only, not also `count_mismatch` |
| 9 | value types | `isbn`/`student_id` strings (leading zeros, `X`), ids and counts ints, flags JSON booleans, dates `YYYY-MM-DD`, timestamps `YYYY-MM-DDTHH:MM:SS` (LIBRA-98 `created`), `...Z` (LABLOG `start_time_utc`), `YYYY-MM-DDTHH:MM` (CVT `modified`), WKS `version_code` a hex string `"0x0404"` | decoders write exactly these types and formats |
| 10 | record order | answer keys have `match_on` | records keep file order; graders (and calibrate) match on the `match_on` key |

Decisions where the contract is silent and no expected output exists:

- `unrecognized` and `failed` outputs have `metadata: {}`, `records: []`,
  `damage: []`; the byte facts of an unrecognized file go to diagnostics.
- An `unsupported` output keeps whatever metadata, records and damage the
  decoder produced.
- Archive members are not emitted; their damage is (see Archives).
- `tool_version` is the package version (`salvagekit.__version__`).
- Key order: the contract's order at the top level and in damage objects;
  record keys in field order; metadata keys sorted.

## Running in parallel, memory, interrupts

- **Parallel workers.** `--jobs N` (default `min(cpu_count, 4)`) runs up to
  N isolated workers at once, each with its own pipe and deadline. Only the
  parent writes files and rows stay in walk order, so the output is
  byte-identical for every N.
- **Memory cap (POSIX only).** Each worker caps its address space at
  `MAX_WORKER_MEMORY` (2 GiB) with `resource.setrlimit(RLIMIT_AS)`; a decode
  that needs more gets a `MemoryError` and the file fails with `memory limit
  (2048 MiB)`. On Windows there is no `resource` module and no cap; a decoder
  that runs out of memory fails with `out of memory (no memory cap in this
  process)`.
- **Interrupts.** SIGTERM (`docker stop`) and SIGINT (Ctrl-C) stop the run:
  no new file is started, running workers are killed, and `report.json` is
  written with the files finished so far plus the diagnostics error
  `"interrupted: N files not processed"`. Unfinished files get no output.
  The exit status is 0.
- **Test-only limit overrides.** `SALVAGE_LIMITS` (a JSON object such as
  `{"MAX_FILE_BYTES": 1048576}`) replaces limits from
  `salvagekit/core/limits.py` at import time, in the parent and every
  worker. Never set it in production.

## Limits

After decode, core keeps at most `MAX_RECORDS` (1,000,000) records and
`MAX_MEMBERS` (100,000) archive members per file, both counted over all
nested members, depth first. Anything past a limit is dropped, the warning
`"output capped at N records"` (or `"... members"`) is added, and an `ok`
file becomes `partial`. Decoders enforce `MAX_DECOMPRESSED` themselves.

## Schema validation

Before anything is written, the parent validates it against the official
schemas (`salvagekit/core/validate.py`, using the stdlib-only validator
`salvagekit/core/jsonschema_lite.py`). `python -m salvagekit.core.validate`
shows them. Besides the shapes, the output schema checks two status rules:
`unrecognized` means format `UNKNOWN` with nothing decoded, and `ok` means
no damage and no record with `"verified": false`.

- **Per-file output invalid** → it is NOT written. A `failed` output is
  written instead (same `format`; empty metadata, records and damage). The
  diagnostics entry is changed to match (status `failed`, zero counts,
  `coverage` null); its `errors` get a header line plus the first 10
  validation errors (`"<json path>: <message>"`). If even the replacement
  fails validation it is written anyway and a run-level error says so (a
  bug).
- **report.json invalid** → it is still written (the report must always
  exist), with a run-level error naming the first problems; the same
  message goes to stderr.
- **A schema that cannot be loaded** is a run-level error, and that kind
  of document is not validated. There is no fallback schema.
