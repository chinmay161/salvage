# Salvage

Offline CLI: `/salvage <input_dir> <output_dir>`. Identifies each input file's
legacy binary format, decodes it, validates it, and writes one schema-valid
JSON per input plus `report.json`. Damaged files are recovered as far as
possible and the damage is reported honestly. Hackathon project, 4 people.

## Hard rules
- Python 3.12, standard library only. No pip installs, no network, ever.
- The CLI always exits 0, even on bad arguments or a missing input dir.
- One bad input file must never stop the run or affect another file's output.
- Never invent data. `verified` needs real evidence (checksum, round trip,
  exact magic match). Unknown or damaged = `unverified` or `lost`.
- Output is deterministic: same input bytes -> identical output bytes.
- Decoders read file bytes only through `SafeReader` and never raise.
- Code must run on Windows (dev) and Linux (Docker). Paths written to
  output always use forward slashes. Output files are UTF-8 with LF line
  endings.

## Ownership
- Core (lead): salvage/core/, salvage/cli.py, salvage/formats/stub.py,
  tests/core/, tests/fixtures/, tools/ (except tools/fuzz.py), Dockerfile,
  Makefile, README.md, CLAUDE.md, docs/phase-reports/, docs/*/_TEMPLATE.md,
  FORMAT-SPEC.md and FIELD-LOG.md (generated).
- Teammates: salvage/formats/<format>.py, tests/<format>/, docs/spec/,
  docs/log/. Do not edit these unless the task explicitly says so.
- samples/ and schema/ are read-only.
- The contract (salvage/core/model.py, plugin.py, reader.py) is frozen after
  Phase 0. Changes need the lead's approval; never change it silently.

## Commands
- `python tools/task.py test`  run all tests (must pass before handing work back)
- `python tools/task.py api`   print the public API of salvage.core/formats
- `python tools/task.py run IN OUT`  run the CLI on IN, writing to OUT
- `python tools/task.py golden [FORMAT]`  golden tests (all formats, or one)
- `python tools/task.py golden-update FORMAT`  regenerate tests/FORMAT/cases/*.expected.json
- `python tools/task.py conform [NAME] [--verbose] [--quick]`  decoder
  conformance suite (docs/conformance.md); every decoder must PASS (`test`
  runs it in quick mode: no samples/, fewer variants)
- `python tools/task.py bench [--docker]`  throughput, --jobs 1 vs auto
  (not part of `test`)
- `python tools/task.py build` / `build-offline`  build the salvage:dev image
  (offline: base image must already be pulled)
- `python tools/task.py docker-run IN OUT`  run the image on IN (read-only), writing to OUT
- `python tools/task.py docker-test`  run the unit tests with the image's Linux Python
- `python tools/task.py docker-smoke`  host vs container run; outputs must be byte-identical
- `python tools/task.py docs [--check] [--strict]`  generate FORMAT-SPEC.md,
  FIELD-LOG.md and the README formats table from docs/spec/ and docs/log/
  (--check: write nothing, exit 1 if stale)
- `python tools/task.py check-outputs IN OUT`  check a finished run's output
- `python tools/task.py lint-docker`  Dockerfile: no network in RUN, FROM pinned
- `python tools/task.py save-base` / `load-base`  base image <-> dist/base-image.tar
- `python tools/task.py precheck`  release checklist on a clean clone of HEAD
  (commit first)
- `python -m salvage.core.validate`  show which output/report schemas are
  active (official in salvage/core/schemas/official/, else provisional)
- `make <command>` wraps each of these where make exists
  (`make run IN=... OUT=...`, `make golden FORMAT=stub`, `make conform NAME=stub`, ...)

## Decoders
- Teammates follow docs/decoder-guide.md; docs/decoder-template.py is the
  tested skeleton (kept working by tests/core/test_decoder_template.py).

## Generated docs
- Never edit FORMAT-SPEC.md, FIELD-LOG.md or the README formats table by
  hand; run `python tools/task.py docs`. Specs and logs start from
  docs/spec/_TEMPLATE.md and docs/log/_TEMPLATE.md (files named `_*` are
  never assembled).

## Golden tests
- Cases live in `tests/<format>/cases/`: an input file `<name>` plus
  `<name>.expected.json` (the exact per-file output). The format's owner
  owns the folder.
- Run golden-update only for a format you own, and only after checking by
  hand that the new output is correct. Never update an expectation just to
  make a test pass.

## Working style
- Implement the task as specified. Ambiguities: choose the safest reading
  and list it under "Deviations" in the report.
- Small modules, type hints on public functions, docstrings on the contract.
- Every bug fix gets a test that would have caught it.
- Finish every task with the report format the task asks for.
