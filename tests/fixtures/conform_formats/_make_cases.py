"""Regenerate tests/fixtures/conform_cases/ (one clean case per fixture except nocases).

    python -m tests.fixtures.conform_formats._make_cases [MODULE...]

Expectations come from the real pipeline; the nondet one is order-random by design.
"""

import sys
from pathlib import Path

from salvage.core import emit
from tests import golden
from tests.fixtures.conform_formats import _base

PACKAGE = "tests.fixtures.conform_formats"
CASES = Path(__file__).resolve().parent.parent / "conform_cases"
FIXTURES = {
    "ok": b"CFOK", "greedyprobe": b"CFGP", "slowprobe": b"CFSP", "raisetrunc": b"CFRT",
    "badoffset": b"CFBO", "hang": b"CFHG", "liar": b"CFLR", "badtrip": b"CFBT",
    "nondet": b"CFND", "forbidden": b"CFFB", "slow": b"CFSL", "crash": b"CFCR",
    "warmup": b"CFWU",
}


def main() -> None:
    only = set(sys.argv[1:])
    for module, magic in FIXTURES.items():
        if only and module not in only:
            continue
        cases = CASES / module / "cases"
        cases.mkdir(parents=True, exist_ok=True)
        name = "clean." + magic.decode("ascii").lower()
        (cases / name).write_bytes(_base.build(magic))
        got = golden.run_cases(cases, PACKAGE)
        (cases / (name + golden.SUFFIX)).write_bytes(emit.dumps(got[name]).encode("utf-8"))
        print(f"wrote {cases / name}")


if __name__ == "__main__":
    main()
