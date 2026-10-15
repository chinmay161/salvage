"""SLOWPROBE: probe sleeps forever (timeout before identification)."""

import time

from salvage.core.plugin import Decoder


class SlowProbeDecoder(Decoder):
    name = "T-SLOWPROBE"

    def probe(self, data):
        while True:
            time.sleep(1)

    def decode(self, reader):  # pragma: no cover - never reached
        raise AssertionError("decode must not run")
