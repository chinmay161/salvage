"""Salvage command-line entry point: ``python -m salvage.cli <input_dir> <output_dir>``.

Always exits 0. stdout gets one summary line; stderr gets one line per file
("<status> <format> <input>") plus any errors.
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

from salvage import __version__

USAGE = """usage: python -m salvage.cli <input_dir> <output_dir>

Identify and decode every file under <input_dir>; write one JSON per file
plus report.json to <output_dir>. Always exits with status 0.

options:
  -h, --help    show this help
  --version     show the version
"""


def _say(text: str, stream: TextIO | None) -> None:
    """Print without ever raising (bad encodings, closed pipes)."""
    if stream is None:
        return
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        try:
            enc = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(enc, "backslashreplace").decode(enc) + "\n")
        except Exception:
            pass
    except Exception:
        pass


def _file_line(entry: dict[str, Any]) -> None:
    _say(f"{entry.get('status')} {entry.get('format')} {entry.get('input')}", sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Always returns 0; only KeyboardInterrupt propagates."""
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if "-h" in args or "--help" in args:
            _say(USAGE.rstrip("\n"), sys.stdout)
            return 0
        if "--version" in args:
            _say(f"salvage {__version__}", sys.stdout)
            return 0
        if len(args) != 2:
            _say(USAGE.rstrip("\n"), sys.stderr)
            return 0

        from salvage.core import pipeline
        rep = pipeline.run(args[0], args[1], progress=_file_line)
        for err in rep.get("errors", []):
            _say(f"error: {err}", sys.stderr)
        s = rep.get("summary", {})
        _say(f"salvage: {s.get('files', 0)} files: {s.get('decoded', 0)} decoded, "
             f"{s.get('partial', 0)} partial, {s.get('unknown', 0)} unknown, "
             f"{s.get('failed', 0)} failed; {s.get('skipped', 0)} skipped; "
             f"{len(rep.get('errors', []))} errors", sys.stdout)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - the CLI never fails
        _say(f"error: internal error: {type(exc).__name__}: {exc}", sys.stderr)
    return 0


if __name__ == "__main__":
    main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001 - e.g. a closed pipe; still exit 0
        os._exit(0)
    sys.exit(0)
