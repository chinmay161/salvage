"""CF-FORBIDDEN: breaks three static rules (expected: C8, exactly 3 findings)."""

import socket  # bug: network module
from datetime import datetime

from salvagekit.core.standalone import run_standalone
from tests.fixtures.conform_formats._base import CrcDecoder


class ForbiddenDecoder(CrcDecoder):
    name = "CF-FORBIDDEN"
    extensions = (".cffb",)
    magic = b"CFFB"

    def dump(self, path, data):
        with open(path, "wb") as fh:  # bug: file access outside SafeReader
            fh.write(data)

    def stamp(self, seconds):
        return datetime.fromtimestamp(seconds).isoformat()  # bug: local time zone


if __name__ == "__main__":
    with open(__file__, "rb") as fh:  # exempt: only runs standalone
        fh.read()
    run_standalone(ForbiddenDecoder)
