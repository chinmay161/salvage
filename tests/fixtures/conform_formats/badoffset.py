"""CF-BADOFFSET: a cut-off record keeps its declared length, past the end (expected: C4)."""

from salvage.core.model import Field, Record, Status
from tests.fixtures.conform_formats._base import CrcDecoder


class BadOffsetDecoder(CrcDecoder):
    name = "CF-BADOFFSET"
    extensions = (".cfbo",)
    magic = b"CFBO"

    def truncated_record(self, result, off, n, size):
        # bug: trusts the declared length instead of the file size
        result.records.append(Record(offset=off, status=Status.LOST, kind="text", fields=[
            Field("text", None, off + 4, n, Status.LOST, "file ends inside this record")]))
