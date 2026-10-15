"""Identify a file's format by probing every decoder."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from salvage.core.limits import AMBIGUITY_MARGIN, PROBE_THRESHOLD
from salvage.core.plugin import Decoder, safe_probe

_EPS = 1e-9  # float slack when comparing scores against thresholds


@dataclass(frozen=True)
class Ranked:
    """One decoder's probe outcome; ``error`` is set if the probe misbehaved."""

    format: str
    score: float
    error: str | None = None


@dataclass
class Choice:
    """Result of :func:`choose`.

    ``ranked`` covers every decoder, sorted by (-score, name).
    ``candidates`` are the decoders to try, in order.
    """

    ranked: list[Ranked] = field(default_factory=list)
    candidates: list[Decoder] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def choose(decoders: list[Decoder], data: bytes, filename: str) -> Choice:
    """Probe every decoder on ``data`` and order the candidates to try.

    Candidates score >= PROBE_THRESHOLD. Among those within AMBIGUITY_MARGIN
    of the top score, decoders whose ``extensions`` contain the file's
    suffix (case-insensitive) come first, then by name; the rest follow in
    ranked order. More than one candidate within the margin adds an
    "ambiguous: ..." warning. Never raises for misbehaving probes.
    """
    scored: list[tuple[float, str, Decoder, str | None]] = []
    for dec in decoders:
        score, error = safe_probe(dec, data)
        scored.append((score, str(getattr(dec, "name", "")), dec, error))
    scored.sort(key=lambda t: (-t[0], t[1]))

    choice = Choice(ranked=[Ranked(name, score, error) for score, name, _, error in scored])
    cands = [t for t in scored if t[0] >= PROBE_THRESHOLD - _EPS]
    if not cands:
        return choice

    top = cands[0][0]
    near = [t for t in cands if top - t[0] <= AMBIGUITY_MARGIN + _EPS]
    rest = cands[len(near):]
    suffix = os.path.splitext(filename)[1].lower()
    near.sort(key=lambda t: (not _has_ext(t[2], suffix), t[1]))
    choice.candidates = [t[2] for t in near + rest]
    if len(near) > 1:
        choice.warnings.append("ambiguous: " + ", ".join(t[1] for t in near))
    return choice


def _has_ext(decoder: Decoder, suffix: str) -> bool:
    if not suffix:
        return False
    try:
        return any(isinstance(e, str) and e.lower() == suffix
                   for e in getattr(decoder, "extensions", ()) or ())
    except Exception:
        return False
