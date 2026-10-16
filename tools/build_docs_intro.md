# How Salvage reads a file

<!-- Hand-written. tools/build_docs.py puts it at the top of FORMAT-SPEC.md. -->

The full output shape is in [docs/output-format.md](../docs/output-format.md)
(also included at the end of this document).

**Identification.** Every decoder's `probe` looks at the file's bytes
(magic numbers, header sanity) and returns a score from 0.0 to 1.0. File
names are never trusted: the extension only breaks ties. Decoders scoring
at least 0.5 are tried, best first; the first one that returns a valid,
non-empty result wins. If none reaches 0.5 the file is `unknown`, and only
facts about its bytes are reported (size, SHA-256, entropy, the top
candidates).

**File status.** Each file gets exactly one:

| status | meaning |
|--------|---------|
| `decoded` | decoded; no damage and nothing lost |
| `partial` | decoded, but some bytes are damaged or some values are lost |
| `unknown` | no decoder recognised the file |
| `failed` | recognised (or not) but could not be decoded: decoder error, timeout, crash, unreadable or too large |

**Trust levels.** Every decoded record and field carries one, with an
`evidence` string saying why:

| level | meaning |
|-------|---------|
| `verified` | proven by real evidence: a checksum match, an exact round trip (re-encoding gives the same bytes), an exact magic match |
| `consistent` | agrees with something else in the file, but nothing proves it |
| `unverified` | read as-is; nothing to check it against |
| `lost` | should exist but cannot be recovered; the value is `null`, never guessed |

**Damage and coverage.** Damaged byte ranges are listed as `[start, end)`
with a kind: `truncated` (the file ends early), `checksum` (a stored
checksum does not match), `bounds` (a length or offset points outside the
file), `unparsed` (bytes skipped, e.g. junk between records) or `other`.
Coverage says how many of the file's bytes the decoder actually read and
explained, how many were padding, and which ranges nobody explained.
