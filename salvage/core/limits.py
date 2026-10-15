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
