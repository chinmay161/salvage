# How Salvage reads a file

<!-- Hand-written. tools/build_docs.py puts it at the top of FORMAT-SPEC.md. -->

`./salvage <input_dir> <output_dir>` processes the regular files directly
in `input_dir` (subfolders are skipped) and writes `<file name>.json` per
file plus `report.json`, following the organizers' output contract. The
full output shape is in [docs/output-format.md](../docs/output-format.md)
(also included at the end of this document).

**Identification.** Every decoder's `probe` looks at the file's bytes
(magic numbers, header sanity) and returns a score from 0.0 to 1.0. File
names are never trusted: the extension only breaks ties. Decoders scoring
at least 0.5 are tried, best first; the first one that returns a valid,
non-empty result wins. If none reaches 0.5 the file is `unrecognized`
(format `UNKNOWN`), and only facts about its bytes are reported, in the
report's diagnostics (size, SHA-256, entropy, the top candidates).

**File status.** Each file gets exactly one:

| status | meaning |
|--------|---------|
| `ok` | decoded; nothing damaged, lost or unverified |
| `partial` | decoded, but some bytes are damaged or some values are lost or unverified |
| `unsupported` | recognised, but cannot be decoded (e.g. password-protected) |
| `unrecognized` | no decoder recognised the file |
| `failed` | recognised (or not) but could not be decoded: decoder error, timeout, crash, unreadable or too large |

**Trust levels.** Inside Salvage every decoded record and field carries
one, with an `evidence` string saying why:

| level | meaning |
|-------|---------|
| `verified` | proven by real evidence: a checksum match, an exact round trip (re-encoding gives the same bytes), an exact magic match |
| `consistent` | agrees with something else in the file, but nothing proves it |
| `unverified` | read as-is; nothing to check it against |
| `lost` | should exist but cannot be recovered; the value is `null`, never guessed |

A record that is `unverified` or `lost` (or has such a field) carries
`"verified": false` in the output, and `"issues": [kinds]` names the
damage that affects it.

**Damage and coverage.** Damage is reported with the contract's kinds:
`truncated`, `crc_mismatch`, `checksum_mismatch`, `header_checksum`,
`bad_length`, `count_mismatch`, `oob_pointer`, `index_missing`,
`invalid_value`, `unknown_record`, `unparsed_bytes`, `encrypted`; each with
the offset where it starts and whether data was lost (`lossy`). The report's
diagnostics give the full `[start, end)` ranges and the coverage: how many
of the file's bytes the decoder read and explained, how many were padding,
and which ranges nobody explained.
