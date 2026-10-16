"""SLOW: decode sleeps 0.5 s, then returns one record (for interrupting a run)."""

import time

from salvage.core.model import DecodeResult, Field, Record, Status
from tests.fixtures.pipeline_formats._base import MagicDecoder


class SlowDecoder(MagicDecoder):
    name = "T-SLOW"
    magic = b"T-SLOW"

    def decode(self, reader):
        time.sleep(0.5)
        return DecodeResult(format=self.name, confidence=1.0, records=[
            Record(offset=0, status=Status.UNVERIFIED,
                   fields=[Field("magic", "T-SLOW", 0, 6, Status.UNVERIFIED)])])
