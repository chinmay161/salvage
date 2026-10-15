"""Checksum algorithms and a brute-force checksum finder for format research."""

from __future__ import annotations

import zlib
from functools import lru_cache
from typing import Any, Callable, Iterable, NamedTuple


def _reflect(value: int, width: int) -> int:
    out = 0
    for _ in range(width):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


@lru_cache(maxsize=None)
def _table(width: int, poly: int, refin: bool) -> tuple[int, ...]:
    """Byte-wise lookup table for one (width, poly, refin) combination."""
    table = []
    if refin:
        rpoly = _reflect(poly, width)
        for i in range(256):
            c = i
            for _ in range(8):
                c = (c >> 1) ^ rpoly if c & 1 else c >> 1
            table.append(c)
    else:
        # MSB-first; widths below 8 run in an 8-bit register shifted left.
        reg = max(width, 8)
        p = poly << (reg - width)
        top = 1 << (reg - 1)
        mask = (1 << reg) - 1
        for i in range(256):
            c = i << (reg - 8)
            for _ in range(8):
                c = ((c << 1) ^ p) & mask if c & top else (c << 1) & mask
            table.append(c)
    return tuple(table)


def crc(data: bytes, *, width: int, poly: int, init: int, refin: bool,
        refout: bool, xorout: int) -> int:
    """Generic Rocksoft-model CRC (table-driven, tables cached)."""
    if not isinstance(width, int) or not 1 <= width <= 64:
        raise ValueError(f"unsupported CRC width {width!r}")
    mask = (1 << width) - 1
    poly &= mask
    table = _table(width, poly, bool(refin))
    if refin:
        c = _reflect(init & mask, width)
        for b in data:
            c = (c >> 8) ^ table[(c ^ b) & 0xFF]
        if not refout:
            c = _reflect(c, width)
    else:
        reg = max(width, 8)
        shift = reg - width
        rmask = (1 << reg) - 1
        c = (init & mask) << shift
        top_shift = reg - 8
        for b in data:
            c = ((c << 8) & rmask) ^ table[((c >> top_shift) ^ b) & 0xFF]
        c >>= shift
        if refout:
            c = _reflect(c, width)
    return (c ^ xorout) & mask


CRC_PRESETS: dict[str, dict[str, Any]] = {
    "CRC-8/SMBUS": dict(width=8, poly=0x07, init=0x00, refin=False, refout=False,
                        xorout=0x00, check=0xF4),
    "CRC-16/ARC": dict(width=16, poly=0x8005, init=0x0000, refin=True, refout=True,
                       xorout=0x0000, check=0xBB3D),
    "CRC-16/MODBUS": dict(width=16, poly=0x8005, init=0xFFFF, refin=True, refout=True,
                          xorout=0x0000, check=0x4B37),
    "CRC-16/KERMIT": dict(width=16, poly=0x1021, init=0x0000, refin=True, refout=True,
                          xorout=0x0000, check=0x2189),
    "CRC-16/XMODEM": dict(width=16, poly=0x1021, init=0x0000, refin=False, refout=False,
                          xorout=0x0000, check=0x31C3),
    # a.k.a. CRC-16/CCITT-FALSE
    "CRC-16/IBM-3740": dict(width=16, poly=0x1021, init=0xFFFF, refin=False, refout=False,
                            xorout=0x0000, check=0x29B1),
    # zlib-compatible
    "CRC-32": dict(width=32, poly=0x04C11DB7, init=0xFFFFFFFF, refin=True, refout=True,
                   xorout=0xFFFFFFFF, check=0xCBF43926),
    "CRC-32/BZIP2": dict(width=32, poly=0x04C11DB7, init=0xFFFFFFFF, refin=False,
                         refout=False, xorout=0xFFFFFFFF, check=0xFC891918),
    "CRC-32C": dict(width=32, poly=0x1EDC6F41, init=0xFFFFFFFF, refin=True, refout=True,
                    xorout=0xFFFFFFFF, check=0xE3069283),
}


def crc_preset(name: str, data: bytes) -> int:
    """CRC of ``data`` using the named entry of :data:`CRC_PRESETS`."""
    params = {k: v for k, v in CRC_PRESETS[name].items() if k != "check"}
    return crc(data, **params)


def sum8(data: bytes) -> int:
    """Byte sum mod 2**8."""
    return sum(data) & 0xFF


def sum8_neg(data: bytes) -> int:
    """Two's-complement byte sum: ``sum8(data + bytes([result])) == 0``."""
    return (-sum(data)) & 0xFF


def sum16(data: bytes) -> int:
    """Byte sum mod 2**16."""
    return sum(data) & 0xFFFF


def sum32(data: bytes) -> int:
    """Byte sum mod 2**32."""
    return sum(data) & 0xFFFFFFFF


def _words(data: bytes, order: str) -> Iterable[int]:
    if len(data) % 2:
        data = bytes(data) + b"\x00"
    for i in range(0, len(data), 2):
        yield int.from_bytes(data[i:i + 2], order)


def sum16_words_le(data: bytes) -> int:
    """Sum of little-endian 16-bit words mod 2**16 (odd length padded with 0x00)."""
    return sum(_words(data, "little")) & 0xFFFF


def sum16_words_be(data: bytes) -> int:
    """Sum of big-endian 16-bit words mod 2**16 (odd length padded with 0x00)."""
    return sum(_words(data, "big")) & 0xFFFF


def xor8(data: bytes) -> int:
    """XOR of all bytes."""
    out = 0
    for b in data:
        out ^= b
    return out


def adler32(data: bytes) -> int:
    """Adler-32 (zlib)."""
    return zlib.adler32(data) & 0xFFFFFFFF


def fletcher16(data: bytes) -> int:
    """Fletcher-16 (mod 255): ``(sum2 << 8) | sum1``."""
    s1 = s2 = 0
    for b in data:
        s1 = (s1 + b) % 255
        s2 = (s2 + s1) % 255
    return (s2 << 8) | s1


def _preset_fn(name: str) -> Callable[[bytes], int]:
    params = {k: v for k, v in CRC_PRESETS[name].items() if k != "check"}

    def fn(data: bytes) -> int:
        return crc(data, **params)

    fn.__name__ = name
    return fn


ALGORITHMS: dict[str, tuple[Callable[[bytes], int], int]] = {
    **{name: (_preset_fn(name), p["width"]) for name, p in CRC_PRESETS.items()},
    "sum8": (sum8, 8),
    "sum8_neg": (sum8_neg, 8),
    "sum16": (sum16, 16),
    "sum32": (sum32, 32),
    "sum16_words_le": (sum16_words_le, 16),
    "sum16_words_be": (sum16_words_be, 16),
    "xor8": (xor8, 8),
    "adler32": (adler32, 32),
    "fletcher16": (fletcher16, 16),
}


class ChecksumMatch(NamedTuple):
    """An algorithm whose checksum over ``data[start:end]`` equals the target."""

    name: str
    start: int
    end: int


def find_checksum(data: bytes, target: int, *,
                  ranges: Iterable[tuple[int, int]] | None = None,
                  algorithms: Iterable[str] | None = None,
                  max_ranges: int = 200_000) -> list[ChecksumMatch]:
    """Brute-force which algorithm over which range produces ``target``.

    Development tool. Default ranges: every ``(start, end)`` with start in
    ``[0, min(32, len)]`` and end in ``[max(0, len-32), len]``, start < end.
    At most ``max_ranges`` ranges are tried. Algorithms narrower than
    ``target.bit_length()`` are skipped. Results are sorted by
    (name, start, end). Never raises.
    """
    try:
        data = bytes(data)
        if not isinstance(target, int) or isinstance(target, bool) or target < 0:
            return []
        n = len(data)
        if ranges is None:
            ranges = ((s, e) for s in range(0, min(32, n) + 1)
                      for e in range(max(0, n - 32), n + 1) if s < e)
        limit = max_ranges if isinstance(max_ranges, int) else 200_000
        picked: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for item in ranges:
            if len(picked) >= limit:
                break
            try:
                s, e = item
            except Exception:
                continue
            if (isinstance(s, int) and isinstance(e, int)
                    and 0 <= s < e <= n and (s, e) not in seen):
                seen.add((s, e))
                picked.append((s, e))

        names = sorted(ALGORITHMS) if algorithms is None else sorted(
            {a for a in algorithms if isinstance(a, str) and a in ALGORITHMS})
        need = target.bit_length()
        matches: list[ChecksumMatch] = []
        for name in names:
            fn, width = ALGORITHMS[name]
            if width < need:
                continue
            for s, e in picked:
                try:
                    if fn(data[s:e]) == target:
                        matches.append(ChecksumMatch(name, s, e))
                except Exception:
                    continue
        matches.sort()
        return matches
    except Exception:
        return []
