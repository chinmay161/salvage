"""Re-export of the real STUB decoder (a trivial subclass, so discovery sees it)."""

from salvagekit.formats.stub import StubDecoder as _StubDecoder


class StubDecoder(_StubDecoder):
    """The production STUB decoder, unchanged."""
