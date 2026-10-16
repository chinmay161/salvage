"""MEMHOG: decode tries to allocate 4 GiB (the worker memory cap must stop it)."""

from tests.fixtures.pipeline_formats._base import MagicDecoder


class MemHogDecoder(MagicDecoder):
    name = "T-MEMHOG"
    magic = b"T-MEMHOG"

    def decode(self, reader):
        hog = bytearray(4 * 1024 * 1024 * 1024)
        hog[-1] = 1  # touch it, in case the allocation was lazy
        raise AssertionError("allocated 4 GiB: no memory cap in force")
