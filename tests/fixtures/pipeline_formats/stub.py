"""Re-export of the real STUB decoder, so one run covers stub and hostile files.

Discovery only counts classes defined in the module itself, so this is a
trivial subclass rather than a plain import.
"""

from salvage.formats.stub import StubDecoder as _StubDecoder


class StubDecoder(_StubDecoder):
    """The production STUB decoder, unchanged."""
