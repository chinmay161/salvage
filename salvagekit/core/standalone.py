"""Run a single decoder from the command line: ``python -m salvagekit.formats.x FILE``."""

from __future__ import annotations

import json
import sys

from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader


def run_standalone(decoder_cls: type[Decoder]) -> int:
    """Decode the file named in ``sys.argv[1]`` and print its JSON.

    Usage and read errors go to stderr. Always returns 0 (never exits non-zero).
    """
    if len(sys.argv) != 2:
        prog = getattr(decoder_cls, "__module__", "decoder")
        print(f"usage: python -m {prog} <file>", file=sys.stderr)
        return 0
    path = sys.argv[1]
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 0
    try:
        result = decoder_cls().decode(SafeReader(data))
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    except Exception as exc:
        print(f"error: {getattr(decoder_cls, 'name', '?')} decoder failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    print(text)
    return 0
