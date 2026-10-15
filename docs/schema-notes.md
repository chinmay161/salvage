# Schema notes (Phase 0)

## BLOCKERS

- **schema/ is empty.** No schema file existed when Phase 0 ran (the folder
  was missing and was created empty). There is nothing to check the model
  against, so the Phase 1 emitter cannot be written against a real target
  until the schema lands. Everything below is an assumption.

## What the schema says

- Draft version: unknown (no schema file).
- Top-level required fields: unknown (no schema file).

## Mapping assumptions for the Phase 1 emitter

The emitter maps `DecodeResult.to_dict()` onto the schema; the model is not
changed to fit the schema.

| Model                                   | Assumed schema location                                                                            |
|-----------------------------------------|----------------------------------------------------------------------------------------------------|
| `DecodeResult.format`                   | detected format identifier (e.g. `format`)                                                         |
| `DecodeResult.confidence`               | identification confidence, number in [0, 1]                                                        |
| `DecodeResult.records[]`                | record array; each record keeps `offset`, `kind`, `status`                                         |
| `Record.fields[]`                       | per-record field list or object keyed by `Field.name` (if keyed, duplicate names need a rule)      |
| `Field.status`                          | per-field status enum: `verified`, `consistent`, `unverified`, `lost`                              |
| `Field.offset` / `length`               | provenance: absolute byte range in the input file                                                  |
| `Field.evidence`                        | free-text justification for the status                                                             |
| `DecodeResult.damage[]`                 | damage list: `start`, `end` (exclusive), `kind`, `reason`                                          |
| `DecodeResult.members[]` + `name`       | nested archive entries, recursive, each with its member file name                                  |
| `DecodeResult.meta`                     | format-specific header data / extra properties                                                     |
| `DecodeResult.warnings`                 | warning strings                                                                                    |
| `Status.worst(...)` over all fields     | overall per-file status, if the schema wants one                                                   |
| `SafeReader.covered_bytes()` / size     | coverage figure, if the schema wants one (not stored in DecodeResult; the CLI must pass it in)      |

## Things the model cannot carry (watch for these once the schema arrives)

- Input file identity (path, size, hash such as SHA-256): not in
  `DecodeResult`; the CLI knows these and must add them.
- Tool version / run metadata (`salvage.__version__`): CLI/emitter side.
- Byte coverage and reader events: available from `SafeReader`, not from
  `DecodeResult`; the CLI must hold the reader and pass them to the emitter.
- Typed field values (e.g. a declared `type` or unit per field): the model
  only stores a JSON-safe `value`. A schema that demands a type tag needs a
  mapping rule (e.g. inferred from the Python type) or a contract change.
- Non-finite floats are emitted as the strings "nan"/"inf"/"-inf"; a schema
  that types a field as `number` will reject them.
- Raw bytes are emitted as lowercase hex strings; a schema expecting base64
  needs conversion in the emitter.
