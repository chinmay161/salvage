"""MANY: 5 top-level records plus 3 members, each with 4 records and 1 nested member
holding 2 records. Totals: 5 + 3*4 + 3*2 = 23 records, 3 + 3 = 6 members."""

from salvage.core.model import DecodeResult, Field, Record, Status
from salvage.core.plugin import Decoder

MAGIC = b"T-MANY"


def _records(n, tag):
    return [Record(offset=0, status=Status.UNVERIFIED, kind=tag,
                   fields=[Field("i", i, 0, 1, Status.UNVERIFIED)]) for i in range(n)]


class ManyDecoder(Decoder):
    name = "T-MANY"

    def probe(self, data):
        return 1.0 if bytes(data[:len(MAGIC)]) == MAGIC else 0.0

    def decode(self, reader):
        members = []
        for m in range(3):
            inner = DecodeResult(format="T-MANY", confidence=1.0, name=f"m{m}/inner",
                                 records=_records(2, f"m{m}.inner"))
            members.append(DecodeResult(format="T-MANY", confidence=1.0, name=f"m{m}",
                                        records=_records(4, f"m{m}"), members=[inner]))
        return DecodeResult(format=self.name, confidence=1.0, records=_records(5, "top"),
                            members=members)
