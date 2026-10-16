"""Resource limits and identification thresholds (one place, easy to extend).

TEST-ONLY override: the environment variable ``SALVAGE_LIMITS`` may hold a
JSON object such as ``{"MAX_FILE_BYTES": 1048576}``. It is read once, when
this module is imported; each key must name one of the numeric limits below
and its value replaces that limit. Unknown keys, wrong value types and bad
JSON are ignored, with one line on stderr (printed by the main process
only). Worker processes inherit the environment, so they see the same
limits; this is how tests reach spawned workers, which never see values
monkeypatched in the parent. Never set it in production.
"""

import json
import multiprocessing
import os
import sys

# Wall-clock seconds one input file may spend in its worker process
# (start-up, reading, probing, decoding and building the output). After this
# the worker is killed and the file is reported as "failed".
MAX_SECONDS_PER_FILE = 20

# Files larger than this are never read fully; they are reported "failed".
MAX_FILE_BYTES = 256 * 1024 * 1024

# Minimum probe score for a decoder to be tried at all.
PROBE_THRESHOLD = 0.5

# Candidates whose scores are within this margin of the top score count as a
# tie: the extension hint decides, and an "ambiguous" warning is added.
AMBIGUITY_MARGIN = 0.1

# Records kept per file, counting the records of all nested archive members.
# Core cuts the lists after decode, adds the warning "output capped at N
# records" and reports the file as "partial".
MAX_RECORDS = 1_000_000

# Archive members kept per file, counting nested members at every depth.
# Enforced by core like MAX_RECORDS ("output capped at N members").
MAX_MEMBERS = 100_000

# Total bytes a decoder may decompress for one file (all members together).
# Core cannot see decompression, so DECODERS check this themselves: stop,
# keep what was decoded and report the rest as damage
# (see docs/decoder-guide.md, "Archives").
MAX_DECOMPRESSED = 256 * 1024 * 1024

# Address-space cap for each worker process (POSIX only, via
# resource.setrlimit(RLIMIT_AS)); a decoder that needs more gets MemoryError
# and the file is reported "failed" with "memory limit (N MiB)". Not
# enforced on Windows (no `resource` module); see docs/output-format.md.
MAX_WORKER_MEMORY = 2 * 1024 * 1024 * 1024

# Default number of bytes salvage.core.resync.resync() scans for the next
# valid record start before giving up.
MAX_RESYNC_SCAN = 16 * 1024 * 1024


def within(n: object, limit: int) -> bool:
    """True if ``n`` is an int (not a bool) with ``0 <= n <= limit``."""
    return isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= limit


ENV_OVERRIDES = "SALVAGE_LIMITS"


def _numeric_limits() -> dict[str, type]:
    return {k: type(v) for k, v in globals().items()
            if k.isupper() and not k.startswith("_") and type(v) in (int, float)}


def apply_overrides(raw: str | None) -> list[str]:
    """Apply a ``SALVAGE_LIMITS`` JSON text to this module; return what was ignored.

    A value is accepted if it has the limit's type (an int is also accepted
    for a float limit) and is not negative. Test-only (see the module
    docstring).
    """
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except ValueError:
        return ["not valid JSON"]
    if not isinstance(obj, dict):
        return ["not a JSON object"]
    known = _numeric_limits()
    ignored: list[str] = []
    for key in sorted(obj):
        value = obj[key]
        kind = known.get(key)
        ok_type = kind is not None and not isinstance(value, bool) and (
            isinstance(value, kind) or (kind is float and isinstance(value, int)))
        if kind is None:
            ignored.append(f"unknown key {key}")
        elif not ok_type or value < 0:
            ignored.append(f"bad value for {key}")
        else:
            globals()[key] = kind(value)
    return ignored


def _apply_env() -> None:
    ignored = apply_overrides(os.environ.get(ENV_OVERRIDES))
    if ignored and multiprocessing.parent_process() is None:
        try:
            sys.stderr.write(f"salvage: {ENV_OVERRIDES} (test-only): ignored "
                             + "; ".join(ignored) + "\n")
        except Exception:
            pass


_apply_env()
