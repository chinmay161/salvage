# Output format — PROVISIONAL

> **PROVISIONAL (`schema_version: "provisional-1"`).** No schema has been
> delivered yet (see `docs/schema-notes.md`). This shape will change when
> the schema arrives. Only `salvage/core/emit.py` (per-file shape, naming)
> and `salvage/core/report.py` (report shape) know it, so the change stays
> in those two modules.

All output files are UTF-8, LF line endings, `json.dumps(indent=2,
sort_keys=True, ensure_ascii=False)` plus a final newline, written
atomically (`<name>.tmp` then rename). Paths in output always use forward
slashes and are relative to the input or output directory. There are no
timestamps, durations, PIDs or absolute paths, so the same input bytes give
the same output bytes on every OS.

## Output file names

| Input (relative)  | Output (relative)       | Rule                                           |
|-------------------|-------------------------|------------------------------------------------|
| `a.bin`           | `a.bin.json`            | default: `<rel>.json`, subfolders mirrored      |
| `sub/x.dat`       | `sub/x.dat.json`        |                                                |
| `report`          | `report~2.json`         | `report.json` at the root is reserved           |
| `A.bin`, `a.bin`  | `A.bin.json`, `a.bin~2.json` | names compared with `casefold()`; `~2`, `~3`, ... in sorted input order |
| `a` with folder `a.json/` | `a~2.json`      | a file name never shadows an output folder     |
| `report.json/x`   | `report.json~dir/x.json`| a root folder named like the report is renamed |

An output that would overwrite an input file is not written; the report
entry gets `"output": null` and an error.

## Per-file output: `<rel>.json`

```json
{
  "schema_version": "provisional-1",
  "source":   {"path": "sub/x.dat", "size": 1234, "sha256": "<hex or null>"},
  "format":   "STUB",
  "confidence": 1.0,
  "status":   "decoded",
  "records":  [ ... ],
  "members":  [ ... ],
  "damage":   [ ... ],
  "meta":     { ... },
  "warnings": [ "..." ],
  "errors":   [ "..." ]
}
```

- `records`, `members`, `damage`, `meta` come from `DecodeResult.to_dict()`
  (see `salvage/core/model.py`): records hold `offset`, `kind`, `status`,
  `fields` (`name`, `value`, `offset`, `length`, `status`, `evidence`);
  damage holds `start`, `end` (exclusive), `kind`, `reason`; members are
  nested results with a `name`.
- `warnings` = the decoder's warnings, then pipeline warnings (e.g.
  `"ambiguous: A, B"`).
- `errors` = why a file failed (timeout, crash, read error, ...).
- `sha256` is `null` only if the file could not be read.

### `format` and `confidence` = identification

`format` and `confidence` say what the file was **identified** as, whatever
happened when decoding it:

- `format` is the chosen candidate's name if any decoder's probe reached
  the threshold (0.5), else `"unknown"`. The chosen candidate is the
  decoder whose result is emitted, or, if no result is emitted, the first
  candidate tried (best score; ties broken by extension hint, then name).
- `confidence` is that candidate's probe score, else 0.0.

So a LIBRA-98 file whose decoder crashes is `"format": "LIBRA-98"`,
`"status": "failed"`.

### `status` = decoding outcome (exactly one per file)

| status    | meaning                                                                 |
|-----------|-------------------------------------------------------------------------|
| `decoded` | a decoder succeeded; no damage and nothing `lost` anywhere (incl. members) |
| `partial` | a decoder succeeded; some damage or something `lost`                    |
| `unknown` | no candidate: no decoder's probe reached 0.5; see below                 |
| `failed`  | timeout, worker crash, too large, unreadable, or every candidate errored or returned an invalid result |

For `unknown` files `format` is `"unknown"`, `confidence` 0.0, no records,
and `meta` = `{size, sha256, entropy (bits/byte, 4 decimals),
entropy_sampled, top_candidates: [{format, score}] (best 3)}`. For files
over 4 MB entropy is measured on a fixed sample (first 1 MB + middle 2 MB +
last 1 MB) and `entropy_sampled` is `true`; otherwise `false`. Nothing is
carved or guessed.

For `failed` files there are no records. `format`/`confidence` keep the
identification if probing finished (see above); they are `"unknown"`/0.0
only if the file failed before or during probing (unreadable, too large,
probe timeout). The report entry keeps `candidates` (and `attempts`, when
the worker got far enough to report them). A timeout or crash says how far
the worker got: `"timeout after 20s (during probe)"`,
`"timeout after 20s (during decode)"`,
`"worker crashed with exit code 3 (during decode)"`. "During probe" covers
everything before identification finished (start-up, reading, probing).

## `report.json` (output root, written last, also after a midway failure)

```json
{
  "tool": "salvage", "version": "0.1.0", "schema_version": "provisional-1",
  "summary": {"files": 11, "decoded": 4, "partial": 1, "unknown": 2,
              "failed": 4, "skipped": 0,
              "by_format": {"STUB": 4, "T-BIG": 1, "unknown": 6}},
  "files": [
    {"input": "sub/x.dat", "output": "sub/x.dat.json", "size": 1234,
     "sha256": "<hex>", "status": "decoded", "format": "STUB", "confidence": 1.0,
     "candidates": [{"format": "STUB", "score": 1.0},
                    {"format": "OTHER", "score": 0.0, "error": "probe raised ..."}],
     "attempts": [{"format": "STUB", "outcome": "ok"}],
     "records_by_status": {"verified": 0, "consistent": 1, "unverified": 3, "lost": 0},
     "fields_by_status":  {"verified": 1, "consistent": 1, "unverified": 3, "lost": 0},
     "members": 0,
     "damage": [{"start": 23, "end": 23, "kind": "truncated", "reason": "..."}],
     "warnings": [], "errors": []}
  ],
  "skipped": [{"input": "link", "reason": "symlink (not followed)"}],
  "errors": ["run-level errors, e.g. decoder import errors"]
}
```

- `files` are in walk order (names sorted at every directory level).
- `candidates` lists every decoder's probe, sorted by score then name;
  `error` appears only when the probe misbehaved.
- `attempts[].outcome` is `ok`, `empty`, `invalid: <first 3 problems>` or
  `error: <Type>: <message>`.
- Counts and `damage` include archive members, recursively; `members` is
  the total number of nested members.
- `skipped`: symlinks, FIFOs, devices, sockets, unreadable folders. They
  are never opened.
- `errors` (run level): missing/unreadable input directory, decoder import
  errors, a failed report write, internal errors.
