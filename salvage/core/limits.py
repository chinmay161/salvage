"""Resource limits and identification thresholds (one place, easy to extend)."""

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

# Default number of bytes salvage.core.resync.resync() scans for the next
# valid record start before giving up.
MAX_RESYNC_SCAN = 16 * 1024 * 1024


def within(n: object, limit: int) -> bool:
    """True if ``n`` is an int (not a bool) with ``0 <= n <= limit``."""
    return isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= limit
