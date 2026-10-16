"""STUBBORN: decode ignores SIGTERM and loops forever (must be SIGKILLed)."""

import signal

from tests.fixtures.pipeline_formats._base import MagicDecoder


class StubbornDecoder(MagicDecoder):
    name = "T-STUBBORN"
    magic = b"T-STUBBORN"

    def decode(self, reader):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            pass
