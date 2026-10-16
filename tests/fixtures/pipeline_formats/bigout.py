"""BIGOUT: returns ~5 MB of records (checks the result pipe cannot deadlock)."""

from salvagekit.core.model import DecodeResult, Field, Record, Status
from tests.fixtures.pipeline_formats._base import MagicDecoder

RECORDS = 40_000
VALUE = "v" * 100


class BigOutputDecoder(MagicDecoder):
    name = "T-BIG"
    magic = b"T-BIG"

    def decode(self, reader):
        n = len(self.magic)
        return DecodeResult(format=self.name, confidence=1.0, records=[
            Record(offset=0, status=Status.UNVERIFIED, kind="big",
                   fields=[Field("v", f"{i:08d}{VALUE}", 0, n, Status.UNVERIFIED)])
            for i in range(RECORDS)])
