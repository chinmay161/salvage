# Output contract

`./salvage <input_dir> <output_dir>` must exit 0, never crash on any input, and write
`<output_dir>/<input file name>.json` (e.g. `s01.dat.json`) for every file in `input_dir` (non-recursive; directories are skipped), plus `report.json`.

## Per-file JSON
```json
{ "source_file": "s01.dat", "format": "LIBRA-98", "status": "ok|partial|unsupported|unrecognized|failed",
  "metadata": { }, "records": [ ], "damage": [ {"kind": "crc_mismatch", "offset": 123, "detail": "...", "lossy": true} ] }
```
* `status`: `ok` = nothing lost; `partial` = some data lost or unverified; `unsupported` = recognised but cannot decode (e.g. encrypted); `unrecognized` = unknown format; `failed` = recognised but unreadable.
* `damage[].kind` vocabulary: `truncated, crc_mismatch, checksum_mismatch, bad_length, unparsed_bytes, count_mismatch, invalid_value, oob_pointer, index_missing, header_checksum, encrypted, unknown_record`.
* A record that was recovered but could not be verified carries `"verified": false`, and/or `"issues": [kinds]`.
* Format names: `LIBRA-98, LABLOG, VAULT, WKS, WPD, BRAVO, CVT, EBCDIC-DUMP, WAD, PAK, UNKNOWN`.

## `report.json`
`{"tool_version": "...", "files": [{"file","format","status","records":N,"damage":N}], "totals": {"ok":N,"partial":N,"unrecognized":N,...}}`

## Record shapes (graded fields)
| format | `records[]` fields |
|---|---|
| LIBRA-98 | id, title, author, year, price_cents, copies, isbn, checked_out, deleted, reference_only, due_date (ISO or null) |
| LABLOG | sample, time_ms, values[] (calibrated floats, `null` for dropout) ; `metadata`: instrument, sample_interval_ms, channels[{index,unit}], start_time_utc, declared_block_count, events[{sample,severity,message}] |
| VAULT | id, name, type (`text/bitmap/binary`), size, sha256 (of decoded payload), compressed, text (type text), width/height (bitmap) |
| WKS | cell ("B3"), row, col (0-based), type (`label/integer/number/formula/blank`), value, alignment (labels: left/right/center/repeat), number_format, iso_date (date-formatted cells), cached_value + formula_raw_hex (formulas) |
| WPD | index, type (`paragraph/page_break`), text |
| BRAVO | index, text (one per CR-terminated paragraph); `metadata.format_runs[{start,length,looks[],font}]` is bonus |
| CVT | slot, text ; `metadata`: name, structure (`seq/vlir`), geos_type, modified (`YYYY-MM-DDTHH:MM`), class_name, author, description, declared_blocks |
| EBCDIC-DUMP | student_id, name, dob, gpa, credits, status, balance ; `metadata`: title, run_date, trailer_count, trailer_credits_total |
| WAD / PAK | name, offset, size, sha256 |
