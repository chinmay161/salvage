"""CF-BADSHAPE: claims a contract format name but emits the wrong record shape (expected: C12).

Its records are the CF ones ({"magic", "count"} then {"text"}), not BRAVO's
{"index", "text"}. Fixture packages are exempt from the C1 contract-name
rule, so only C12 fails.
"""

from salvagekit.core.standalone import run_standalone
from tests.fixtures.conform_formats._base import CrcDecoder


class BadShapeDecoder(CrcDecoder):
    name = "BRAVO"
    extensions = (".cfbs",)
    magic = b"CFBS"


if __name__ == "__main__":
    run_standalone(BadShapeDecoder)
