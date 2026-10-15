"""CRASH: decode kills the worker process with exit code 3."""

import os

from tests.fixtures.pipeline_formats._base import MagicDecoder


class CrashDecoder(MagicDecoder):
    name = "T-CRASH"
    magic = b"T-CRASH"

    def decode(self, reader):
        os._exit(3)
