"""BADRES: returns a Field whose offset lies beyond the end of the file."""

from salvage.core.model import DecodeResult, Field, Record, Status
from tests.fixtures.pipeline_formats._base import MagicDecoder


class BadResultDecoder(MagicDecoder):
    name = "T-BAD"
    magic = b"T-BAD"

    def decode(self, reader):
        beyond = reader.size + 10
        return DecodeResult(format=self.name, confidence=1.0, records=[
            Record(offset=0, status=Status.UNVERIFIED,
                   fields=[Field("x", 1, beyond, 4, Status.UNVERIFIED)])])
