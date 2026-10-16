"""CF-WARMUP: slow only on its FIRST big probe and FIRST decode (one-time warm-up).

The first timing of C2 and C9 is over the limit; the re-measure in the same
worker is fast, so it must PASS (with a WARN for each). Waits with
queue.Queue().get(timeout=...) because C8 forbids `time`.
"""

import queue

from tests.fixtures.conform_formats._base import CrcDecoder

_cold = {"probe": True, "decode": True}


def _wait(seconds):
    try:
        queue.Queue().get(timeout=seconds)
    except queue.Empty:
        pass


class WarmupDecoder(CrcDecoder):
    name = "CF-WARMUP"
    extensions = (".cfwu",)
    magic = b"CFWU"

    def probe(self, data):
        if _cold["probe"] and len(data) >= 1024 * 1024:
            _cold["probe"] = False
            _wait(1.0)           # over the 0.5 s C2 limit, once
        return super().probe(data)

    def decode(self, reader):
        if _cold["decode"]:
            _cold["decode"] = False
            _wait(3.0)           # over the 2 s C9 limit, once
        return super().decode(reader)
