"""SafeReader: bounds-checked access to file bytes (frozen Phase 0 contract).

Decoders read file bytes ONLY through a SafeReader. No public method ever
raises, for any argument. Failed reads return None (or a short/empty bytes
value), leave the position unchanged where documented, and record a
:class:`ReaderEvent`. Every successful read records a claim
``(start, end, label)`` so coverage can be reported.
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from typing import Any, Iterator, NamedTuple


class ReaderEvent(NamedTuple):
    """Something that went wrong during a read.

    kind is one of "truncated", "bad_seek", "bad_length", "bad_format",
    "bad_data". ``wanted``/``available`` are byte counts (or the requested
    position for "bad_seek"); either may be None when not meaningful.
    """

    kind: str
    offset: int
    wanted: int | None
    available: int | None
    label: str | None


_U8 = struct.Struct("<B")
_I8 = struct.Struct("<b")
_U16LE, _U16BE = struct.Struct("<H"), struct.Struct(">H")
_I16LE, _I16BE = struct.Struct("<h"), struct.Struct(">h")
_U32LE, _U32BE = struct.Struct("<I"), struct.Struct(">I")
_I32LE, _I32BE = struct.Struct("<i"), struct.Struct(">i")
_U64LE = struct.Struct("<Q")
_F32LE = struct.Struct("<f")
_F64LE = struct.Struct("<d")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _clean_label(label: Any) -> str | None:
    if label is None:
        return None
    if isinstance(label, str):
        return str(label)
    try:
        return str(label)
    except Exception:
        return "?"


class SafeReader:
    """Read-only cursor over a bytes buffer that never raises."""

    def __init__(self, data: bytes) -> None:
        self._events: list[ReaderEvent] = []
        self._claims: list[tuple[int, int, str]] = []
        self._pos = 0
        if isinstance(data, bytes):
            self._data = data
        else:
            try:
                self._data = bytes(data)
            except Exception:
                self._data = b""
                self._events.append(ReaderEvent("bad_data", 0, None, 0, None))

    # -- position ---------------------------------------------------------

    @property
    def size(self) -> int:
        """Total number of bytes in the buffer."""
        return len(self._data)

    def tell(self) -> int:
        """Current position."""
        return self._pos

    def remaining(self) -> int:
        """Bytes left from the current position to the end."""
        return len(self._data) - self._pos

    def seek(self, pos: int) -> bool:
        """Move to absolute ``pos`` (0 <= pos <= size).

        Invalid -> position unchanged, "bad_seek" event, returns False.
        """
        if _is_int(pos) and 0 <= pos <= len(self._data):
            self._pos = pos
            return True
        self._event("bad_seek", pos if _is_int(pos) else None, len(self._data), None)
        return False

    def skip(self, n: int) -> bool:
        """Move by ``n`` bytes (may be negative); same rules as :meth:`seek`."""
        if _is_int(n) and 0 <= self._pos + n <= len(self._data):
            self._pos += n
            return True
        self._event("bad_seek", self._pos + n if _is_int(n) else None, len(self._data), None)
        return False

    @contextmanager
    def at(self, offset: int) -> Iterator[bool]:
        """``with r.at(off) as ok:`` seek to ``off``, restore position on exit.

        ``ok`` is False (and the position does not move) if ``off`` is invalid.
        """
        saved = self._pos
        ok = self.seek(offset)
        try:
            yield ok
        finally:
            self._pos = saved

    # -- fixed-size reads -------------------------------------------------

    def _read_struct(self, st: struct.Struct, label: str | None) -> Any:
        label = _clean_label(label)
        n = st.size
        if self.remaining() < n:
            self._event("truncated", n, self.remaining(), label)
            return None
        (value,) = st.unpack_from(self._data, self._pos)
        self._claim(self._pos, self._pos + n, label)
        self._pos += n
        return value

    def u8(self, label: str | None = None) -> int | None:
        """Unsigned 8-bit integer, or None if truncated."""
        return self._read_struct(_U8, label)

    def i8(self, label: str | None = None) -> int | None:
        """Signed 8-bit integer, or None if truncated."""
        return self._read_struct(_I8, label)

    def u16le(self, label: str | None = None) -> int | None:
        """Unsigned 16-bit little-endian integer, or None if truncated."""
        return self._read_struct(_U16LE, label)

    def u16be(self, label: str | None = None) -> int | None:
        """Unsigned 16-bit big-endian integer, or None if truncated."""
        return self._read_struct(_U16BE, label)

    def i16le(self, label: str | None = None) -> int | None:
        """Signed 16-bit little-endian integer, or None if truncated."""
        return self._read_struct(_I16LE, label)

    def i16be(self, label: str | None = None) -> int | None:
        """Signed 16-bit big-endian integer, or None if truncated."""
        return self._read_struct(_I16BE, label)

    def u32le(self, label: str | None = None) -> int | None:
        """Unsigned 32-bit little-endian integer, or None if truncated."""
        return self._read_struct(_U32LE, label)

    def u32be(self, label: str | None = None) -> int | None:
        """Unsigned 32-bit big-endian integer, or None if truncated."""
        return self._read_struct(_U32BE, label)

    def i32le(self, label: str | None = None) -> int | None:
        """Signed 32-bit little-endian integer, or None if truncated."""
        return self._read_struct(_I32LE, label)

    def i32be(self, label: str | None = None) -> int | None:
        """Signed 32-bit big-endian integer, or None if truncated."""
        return self._read_struct(_I32BE, label)

    def u64le(self, label: str | None = None) -> int | None:
        """Unsigned 64-bit little-endian integer, or None if truncated."""
        return self._read_struct(_U64LE, label)

    def f32le(self, label: str | None = None) -> float | None:
        """32-bit little-endian IEEE float, or None if truncated."""
        return self._read_struct(_F32LE, label)

    def f64le(self, label: str | None = None) -> float | None:
        """64-bit little-endian IEEE float, or None if truncated."""
        return self._read_struct(_F64LE, label)

    # -- variable reads ---------------------------------------------------

    def bytes(self, n: int, label: str | None = None) -> bytes:
        """Return up to ``n`` bytes and advance past them.

        A short read returns what is available and records "truncated";
        a negative or non-integer ``n`` returns b"" and records "bad_length".
        """
        label = _clean_label(label)
        if not _is_int(n) or n < 0:
            self._event("bad_length", n if _is_int(n) else None, self.remaining(), label)
            return b""
        avail = self.remaining()
        take = min(n, avail)
        if take < n:
            self._event("truncated", n, avail, label)
        start = self._pos
        out = self._data[start:start + take]
        self._claim(start, start + take, label)
        self._pos += take
        return out

    def unpack(self, fmt: str, label: str | None = None) -> tuple | None:
        """``struct.unpack`` at the current position, then advance.

        ``fmt`` must start with "<" or ">" (else None + "bad_format").
        Not enough bytes -> None, position unchanged, "truncated".
        """
        label = _clean_label(label)
        if not isinstance(fmt, str) or not fmt or fmt[0] not in "<>":
            self._event("bad_format", None, self.remaining(), label)
            return None
        try:
            st = struct.Struct(fmt)
        except Exception:
            self._event("bad_format", None, self.remaining(), label)
            return None
        n = st.size
        if self.remaining() < n:
            self._event("truncated", n, self.remaining(), label)
            return None
        try:
            values = st.unpack_from(self._data, self._pos)
        except Exception:  # pragma: no cover - defensive
            self._event("bad_format", n, self.remaining(), label)
            return None
        self._claim(self._pos, self._pos + n, label)
        self._pos += n
        return values

    def cstring(self, max_len: int = 4096, label: str | None = None) -> bytes | None:
        """Bytes up to a NUL terminator; consumes the NUL, excludes it.

        The NUL must lie within the next ``max_len`` bytes and before the
        end of data, else None, position unchanged, "truncated".
        """
        label = _clean_label(label)
        if not _is_int(max_len) or max_len < 0:
            self._event("bad_length", max_len if _is_int(max_len) else None,
                        self.remaining(), label)
            return None
        start = self._pos
        end = min(start + max_len, len(self._data))
        nul = self._data.find(b"\x00", start, end)
        if nul < 0:
            self._event("truncated", max_len, self.remaining(), label)
            return None
        self._claim(start, nul + 1, label)
        self._pos = nul + 1
        return self._data[start:nul]

    def peek(self, n: int) -> bytes:
        """Up to ``n`` bytes from the current position; no advance, no claim."""
        if not _is_int(n) or n <= 0:
            return b""
        return self._data[self._pos:self._pos + n]

    # -- bookkeeping ------------------------------------------------------

    @property
    def events(self) -> list[ReaderEvent]:
        """Copy of all recorded events, in order."""
        return list(self._events)

    def claimed(self) -> list[tuple[int, int, str]]:
        """Claimed ranges ``(start, end, label)``, sorted.

        Adjacent or overlapping ranges are merged only when they share the
        same label.
        """
        by_label: dict[str, list[tuple[int, int]]] = {}
        for start, end, label in self._claims:
            by_label.setdefault(label, []).append((start, end))
        merged: list[tuple[int, int, str]] = []
        for label, ranges in by_label.items():
            ranges.sort()
            cur_s, cur_e = ranges[0]
            for s, e in ranges[1:]:
                if s <= cur_e:
                    cur_e = max(cur_e, e)
                else:
                    merged.append((cur_s, cur_e, label))
                    cur_s, cur_e = s, e
            merged.append((cur_s, cur_e, label))
        merged.sort()
        return merged

    def covered_bytes(self) -> int:
        """Number of distinct bytes claimed by any read."""
        total = 0
        cur_s = cur_e = -1
        for s, e in sorted((s, e) for s, e, _ in self._claims):
            if s > cur_e:
                total += cur_e - cur_s if cur_e > cur_s else 0
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        total += cur_e - cur_s if cur_e > cur_s else 0
        return total

    def _claim(self, start: int, end: int, label: str | None) -> None:
        if end > start:
            self._claims.append((start, end, "?" if label is None else label))

    def _event(self, kind: str, wanted: int | None, available: int | None,
               label: str | None) -> None:
        self._events.append(ReaderEvent(kind, self._pos, wanted, available, label))
