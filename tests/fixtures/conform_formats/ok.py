"""CF-OK: well-behaved (CRC-checked records, encode, resync, damage); must PASS."""

from salvagekit.core.standalone import run_standalone
from tests.fixtures.conform_formats._base import CrcDecoder


class OkDecoder(CrcDecoder):
    name = "CF-OK"
    extensions = (".cfok",)
    magic = b"CFOK"


if __name__ == "__main__":
    run_standalone(OkDecoder)
