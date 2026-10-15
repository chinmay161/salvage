# Salvage

Salvage reads a folder of files in legacy binary formats, works out each
file's format, decodes what it can, and writes one JSON file per input plus
a `report.json`. Damaged files are recovered as far as possible, and the
damage is reported. Nothing is guessed. It runs fully offline.

## Build

```sh
docker build -t salvage .
```

The build needs no network beyond the base image (`python:3.12-slim`,
pinned by digest). It runs no pip, apt-get or downloads.

## Run

Put the input files in `./in`. Results go to `./out`.

```sh
docker run --rm --network none -v "$PWD/in:/in:ro" -v "$PWD/out:/out" salvage /salvage /in /out
```

The short form without `/salvage` also works:

```sh
docker run --rm --network none -v "$PWD/in:/in:ro" -v "$PWD/out:/out" salvage /in /out
```

Windows PowerShell:

```powershell
docker run --rm --network none -v "${PWD}\in:/in:ro" -v "${PWD}\out:/out" salvage /salvage /in /out
```

With no arguments the image prints its help. Salvage always exits with
status 0, even for a missing input folder. Problems are listed in
`report.json` and on stderr.

**Linux: owning the output files.** The container runs as root, so it can
write to an output folder that Docker created. Those files are then owned by
root. To get files owned by you, create `out` first and add
`--user "$(id -u):$(id -g)"`:

```sh
mkdir -p out
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/in:/in:ro" -v "$PWD/out:/out" salvage /salvage /in /out
```

**Machines without internet.** On a machine that has internet, save the
base image:

```sh
docker pull python:3.12-slim
docker save python:3.12-slim -o base.tar
```

Copy `base.tar` and this repository to the offline machine. Then run:

```sh
docker load -i base.tar
docker build --network none -t salvage .
```

## Output

- One JSON per input file: `<input path>.json`, with subfolders mirrored.
  For example, `sub/x.dat` gives `sub/x.dat.json`.
- `report.json` in the output root lists every file, a summary and any errors.

Each file gets exactly one `status`:

| status    | meaning |
|-----------|---------|
| `decoded` | decoded with no damage and nothing lost |
| `partial` | decoded, but some data is damaged or lost; the damaged byte ranges are listed |
| `unknown` | no decoder recognised the file; only facts about the bytes are given (size, hash, entropy) |
| `failed`  | the file was recognised (or not) but could not be decoded: decoder error, timeout, crash, unreadable or too large |

`format` says what the file was identified as. `status` says how decoding
went. The full shape is in [docs/output-format.md](docs/output-format.md).

## Development

You need Python 3.12 and only the standard library.

```sh
python tools/task.py test            # all unit and golden tests
python tools/task.py api             # public API of salvage.core / salvage.formats
python tools/task.py run IN OUT      # run the CLI locally
python tools/task.py golden [FORMAT] # golden tests (tests/<format>/cases/)
python tools/task.py docker-smoke    # host vs container run: outputs must be byte-identical
```

There are more commands: `build`, `build-offline`, `docker-run`,
`docker-test` and `golden-update`. Run `python tools/task.py` to see them all.
Each one also has a `make` target. Project rules are in [CLAUDE.md](CLAUDE.md).
