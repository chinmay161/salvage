"""Byte coverage: how much of a file the decoder's reads explained.

Computed in the worker from the SafeReader of the attempt whose result is
emitted. Bytes claimed by any read label other than "padding" are
"explained"; bytes claimed ONLY by "padding" reads count as padding; the
rest are listed as unexplained ranges.
"""

from __future__ import annotations

from typing import Any, Iterable

from salvage.core.reader import SafeReader

PADDING = "padding"
MAX_RANGES = 100


def _union(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def _length(ranges: list[tuple[int, int]]) -> int:
    return sum(e - s for s, e in ranges)


def _pct(part: int, total: int) -> float | None:
    return None if total == 0 else round(100.0 * part / total, 2)


def coverage(reader: SafeReader) -> dict[str, Any]:
    """Coverage of ``reader``'s buffer by its claimed ranges.

    Returns ``{bytes_total, bytes_explained, bytes_padding, explained_pct,
    accounted_pct, unexplained, unexplained_truncated}``. Percentages are
    0-100 rounded to 2 decimals, or None for an empty file;
    ``accounted_pct`` = (explained + padding) / total. ``unexplained`` holds
    at most 100 merged ``[start, end)`` ranges never claimed by any read.
    """
    total = reader.size
    claims = reader.claimed()
    explained = _union((s, e) for s, e, label in claims if label != PADDING)
    claimed_all = _union((s, e) for s, e, _ in claims)
    n_explained = _length(explained)
    n_padding = _length(claimed_all) - n_explained

    gaps: list[list[int]] = []
    pos = 0
    for s, e in claimed_all:
        if s > pos:
            gaps.append([pos, s])
        pos = max(pos, e)
    if pos < total:
        gaps.append([pos, total])

    return {
        "bytes_total": total,
        "bytes_explained": n_explained,
        "bytes_padding": n_padding,
        "explained_pct": _pct(n_explained, total),
        "accounted_pct": _pct(n_explained + n_padding, total),
        "unexplained": gaps[:MAX_RANGES],
        "unexplained_truncated": len(gaps) > MAX_RANGES,
    }
