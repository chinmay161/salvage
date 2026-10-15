"""Result for files no decoder claims: facts about the bytes, nothing guessed."""

from __future__ import annotations

import hashlib
import math
from collections import Counter

from salvage.core.identify import Ranked
from salvage.core.model import DecodeResult

_MB = 1024 * 1024
# Above this size entropy is computed on a fixed sample, not the whole file.
ENTROPY_SAMPLE_OVER = 4 * _MB


def entropy_is_sampled(size: int) -> bool:
    """True if :func:`entropy` samples data of this size instead of reading it all."""
    return size > ENTROPY_SAMPLE_OVER


def entropy_sample(data: bytes) -> bytes:
    """The bytes :func:`entropy` measures: all of ``data`` up to 4 MB, else
    the first 1 MB + the middle 2 MB + the last 1 MB (deterministic)."""
    n = len(data)
    if not entropy_is_sampled(n):
        return data
    mid = (n - 2 * _MB) // 2
    view = memoryview(data)
    return b"".join((view[:_MB], view[mid:mid + 2 * _MB], view[n - _MB:]))


def entropy(data: bytes) -> float:
    """Shannon entropy in bits per byte, rounded to 4 decimals (0.0 if empty).

    Data over 4 MB is measured on :func:`entropy_sample` only.
    """
    data = entropy_sample(data)
    n = len(data)
    if n == 0:
        return 0.0
    counts = Counter(data)
    h = 0.0
    for byte in range(256):  # fixed order keeps the float sum deterministic
        c = counts.get(byte, 0)
        if c:
            p = c / n
            h -= p * math.log2(p)
    return round(h + 0.0, 4)


def unknown(data: bytes, ranked: list[Ranked]) -> DecodeResult:
    """Format "unknown", confidence 0.0, no records; meta describes the bytes.

    meta: size, sha256, entropy, entropy_sampled, top_candidates (best 3 of
    ``ranked``). Never carves strings or guesses records.
    """
    return DecodeResult(
        format="unknown",
        confidence=0.0,
        meta={
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "entropy": entropy(data),
            "entropy_sampled": entropy_is_sampled(len(data)),
            "top_candidates": [{"format": r.format, "score": r.score} for r in ranked[:3]],
        },
    )
