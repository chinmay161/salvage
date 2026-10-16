"""Salvage command-line entry point: ``./salvage [options] <input_dir> <output_dir>``
(the repo-root script runs ``python3 -m salvagekit.cli``).

Always exits 0. stdout gets one summary line; stderr gets one line per file
("<status> <format> <input>", in completion order) plus any errors.
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

from salvagekit import __version__

USAGE = """usage: ./salvage [--jobs N] [--stats] <input_dir> <output_dir>

Identify and decode every file directly in <input_dir> (subfolders are
skipped); write <file name>.json per file plus report.json to <output_dir>.
Always exits with status 0.

options:
  -h, --help    show this help
  --version     show the version
  --jobs N      decode up to N files at once (default: auto = the number
                of CPUs, at most 4); --jobs 1 decodes one file at a time.
                The output is the same for every N.
  --stats       print run statistics (jobs, peak workers) to stderr
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


def _reconfigure_streams() -> None:
    """A file name the console cannot encode is printed with "?" instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _file_line(entry: dict[str, Any]) -> None:
    _say(f"{entry.get('status')} {entry.get('format')} {entry.get('input')}", sys.stderr)


def parse_args(args: list[str]) -> tuple[list[str], int | None, bool, str | None]:
    """Hand-parse ``[--jobs N|auto] [--stats] IN OUT`` (options in any position).

    Returns ``(positionals, jobs, stats, error)``; ``jobs`` None means auto.
    ``--jobs=N`` works too, and ``--`` ends the options.
    """
    positionals: list[str] = []
    jobs: int | None = None
    stats = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            positionals += args[i + 1:]
            break
        if arg == "--stats":
            stats = True
        elif arg == "--jobs" or arg.startswith("--jobs="):
            if arg == "--jobs":
                i += 1
                if i >= len(args):
                    return positionals, None, stats, "--jobs needs a value"
                value = args[i]
            else:
                value = arg[len("--jobs="):]
            if value == "auto":
                jobs = None
            elif value.isascii() and value.isdigit() and int(value) >= 1:
                jobs = int(value)
            else:
                return positionals, None, stats, \
                    f"--jobs needs a positive integer or 'auto', not {value!r}"
        else:
            positionals.append(arg)
        i += 1
    return positionals, jobs, stats, None


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Always returns 0; only KeyboardInterrupt propagates.

    During the run itself SIGINT/SIGTERM do not raise: the pipeline stops,
    writes report.json and returns (see :func:`salvagekit.core.pipeline.run`).
    """
    from salvagekit.core.report import FILE_STATUSES
    _reconfigure_streams()
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if "-h" in args or "--help" in args:
            _say(USAGE.rstrip("\n"), sys.stdout)
            return 0
        if "--version" in args:
            _say(f"salvage {__version__}", sys.stdout)
            return 0
        paths, jobs, want_stats, error = parse_args(args)
        if error is not None or len(paths) != 2:
            if error is not None:
                _say(f"error: {error}", sys.stderr)
            _say(USAGE.rstrip("\n"), sys.stderr)
            return 0

        from salvagekit.core import pipeline
        stats: dict[str, Any] = {}
        rep = pipeline.run(paths[0], paths[1], progress=_file_line, stats=stats,
                           jobs=pipeline.default_jobs() if jobs is None else jobs)
        diag = rep.get("diagnostics", {})
        for err in diag.get("errors", []):
            _say(f"error: {err}", sys.stderr)
        for warning in diag.get("warnings", []):
            _say(f"warning: {warning}", sys.stderr)
        if want_stats:
            _say(f"stats: jobs={stats.get('jobs')} peak_workers={stats.get('peak_workers')} "
                 f"files={stats.get('files')}", sys.stderr)
        totals = rep.get("totals", {})
        summary = diag.get("summary", {})
        counts = ", ".join(f"{totals.get(s, 0)} {s}" for s in FILE_STATUSES)
        _say(f"salvage: {summary.get('files', 0)} files: {counts}; "
             f"{summary.get('skipped', 0)} skipped; "
             f"{len(diag.get('errors', []))} errors", sys.stdout)
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
