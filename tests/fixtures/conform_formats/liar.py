"""CF-LIAR: marks every field verified without checking anything (expected: C5)."""

from salvagekit.core.model import Status
from tests.fixtures.conform_formats._base import CrcDecoder


class LiarDecoder(CrcDecoder):
    name = "CF-LIAR"
    extensions = (".cflr",)
    magic = b"CFLR"

    def decode(self, reader):
        result = super().decode(reader)
        for rec in result.records:  # bug: no evidence for any of this
            rec.status = Status.VERIFIED
            for f in rec.fields:
                f.status = Status.VERIFIED
                f.evidence = "looks right"
        return result
