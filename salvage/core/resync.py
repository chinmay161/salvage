"""Resync: after damage, find the next offset where a valid record could start.

Probing goes through a :class:`ByteView`, which reads the file bytes
without claiming them and without recording reader events, so scanning
never inflates coverage. Only the bytes the decoder then really reads
through the SafeReader count as explained.
"""

from __future__ import annotations

import struct
from typing import Callable, NamedTuple

from salvage.core import limits
from salvage.core.model import Damage, DamageKind
from salvage.core.reader import SafeReader

_U16LE, _U16BE = struct.Struct("<H"), struct.Struct(">H")
_U32LE, _U32BE = struct.Struct("<I"), struct.Struct(">I")


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


class ByteView:
    """Read-only, non-claiming access to a SafeReader's bytes. Never raises.

    Every method takes an absolute file offset. Out-of-range or non-integer
    arguments give None (``bytes`` gives a short or empty result).
    """

    def __init__(self, reader: SafeReader) -> None:
        # Core may use SafeReader internals; decoders use this class instead.
        data = getattr(reader, "_data", b"")
        self._data: bytes = data if isinstance(data, bytes) else b""

    @property
    def size(self) -> int:
        """Total number of bytes."""
        return len(self._data)

    def _unpack(self, st: struct.Struct, offset: object) -> int | None:
        if not _is_int(offset) or offset < 0 or offset + st.size > len(self._data):
            return None
        return st.unpack_from(self._data, offset)[0]

    def u8(self, offset: int) -> int | None:
        """Byte at ``offset``, or None."""
        if not _is_int(offset) or not 0 <= offset < len(self._data):
            return None
        return self._data[offset]

    def u16le(self, offset: int) -> int | None:
        """Unsigned 16-bit little-endian at ``offset``, or None."""
        return self._unpack(_U16LE, offset)

    def u16be(self, offset: int) -> int | None:
        """Unsigned 16-bit big-endian at ``offset``, or None."""
        return self._unpack(_U16BE, offset)

    def u32le(self, offset: int) -> int | None:
        """Unsigned 32-bit little-endian at ``offset``, or None."""
        return self._unpack(_U32LE, offset)

    def u32be(self, offset: int) -> int | None:
        """Unsigned 32-bit big-endian at ``offset``, or None."""
        return self._unpack(_U32BE, offset)

    def bytes(self, offset: int, n: int) -> bytes:
        """Up to ``n`` bytes from ``offset`` (short at the end; b"" if invalid)."""
        if not (_is_int(offset) and _is_int(n)) or offset < 0 or n <= 0:
            return b""
        return self._data[offset:offset + n]


class ResyncResult(NamedTuple):
    """Outcome of :func:`resync`.

    ``offset`` is the first valid start found, or None. ``[skipped_start,
    skipped_end)`` is the byte range passed over (up to the found offset,
    or up to the end of the scan). ``checks`` counts callback calls.
    """

    offset: int | None
    skipped_start: int
    skipped_end: int
    checks: int


StartCheck = Callable[[ByteView, int], bool]


def resync(reader: SafeReader, is_valid_start: StartCheck, *, start: int | None = None,
           step: int = 1, max_scan: int | None = None) -> ResyncResult:
    """Scan forward for the next offset where ``is_valid_start(view, offset)`` is true.

    Candidates run from ``start`` (default ``reader.tell() + 1``) towards the
    end of the file in steps of ``step``, covering at most ``max_scan`` bytes
    (default :data:`limits.MAX_RESYNC_SCAN`). A callback that raises counts as
    False. Found: the reader is moved to the offset. Not found: the reader
    position is unchanged and ``offset`` is None. Never raises.
    """
    size = reader.size
    if start is None or not _is_int(start):
        start = reader.tell() + 1
    start = max(0, min(start, size))
    if not _is_int(step) or step < 1:
        step = 1
    if max_scan is None or not _is_int(max_scan) or max_scan < 0:
        max_scan = limits.MAX_RESYNC_SCAN
    end = min(size, start + max_scan)

    view = ByteView(reader)
    checks = 0
    for offset in range(start, end, step):
        checks += 1
        try:
            ok = bool(is_valid_start(view, offset))
        except (Exception, SystemExit):
            ok = False
        if ok:
            reader.seek(offset)
            return ResyncResult(offset, start, offset, checks)
    return ResyncResult(None, start, end, checks)


def resync_damage(result: ResyncResult, reason: str) -> Damage | None:
    """``Damage(UNPARSED)`` over the skipped range, or None if nothing was skipped."""
    if result.skipped_end <= result.skipped_start:
        return None
    return Damage(result.skipped_start, result.skipped_end, DamageKind.UNPARSED, reason)
