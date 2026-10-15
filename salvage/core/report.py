"""report.json: per-file entries, file status, counts and the run summary.

The shape is PROVISIONAL until the real schema arrives; see
docs/output-format.md. No timestamps, durations, PIDs or absolute paths.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from salvage import __version__
from salvage.core import validate
from salvage.core.emit import display_path
from salvage.core.model import DecodeResult, Status

TRUST = ("verified", "consistent", "unverified", "lost")
FILE_STATUSES = ("decoded", "partial", "unknown", "failed")


def walk_results(result: DecodeResult) -> Iterator[DecodeResult]:
    """``result`` and all nested members, depth first."""
    yield result
    for member in result.members:
        yield from walk_results(member)


def file_status(result: DecodeResult) -> str:
    """"decoded" if no damage and nothing LOST anywhere (members too), else "partial"."""
    for res in walk_results(result):
        if res.damage:
            return "partial"
        for rec in res.records:
            if rec.status == Status.LOST or any(f.status == Status.LOST for f in rec.fields):
                return "partial"
    return "decoded"


def make_entry(*, rel: str, size: int, status: str, fmt: str, confidence: float,
               candidates: Iterable[Any] = (), attempts: Iterable[tuple[str, str]] = (),
               result: DecodeResult | None = None, warnings: Iterable[str] = (),
               errors: Iterable[str] = (), variant: str | None = None,
               probe_score: float = 0.0,
               coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    """One report entry. ``output`` and ``sha256`` are filled in by the pipeline.

    ``candidates`` are :class:`~salvage.core.identify.Ranked`; ``attempts``
    are ``(format, outcome)`` pairs. Counts include members, recursively.
    ``coverage`` is :func:`salvage.core.coverage.coverage` (None for failed files).
    """
    records = dict.fromkeys(TRUST, 0)
    fields = dict.fromkeys(TRUST, 0)
    members = 0
    damage: list[dict[str, Any]] = []
    if result is not None:
        for res in walk_results(result):
            if res is not result:
                members += 1
            for rec in res.records:
                records[Status(rec.status).value] += 1
                for fld in rec.fields:
                    fields[Status(fld.status).value] += 1
            for d in res.damage:
                damage.append({"start": d.start, "end": d.end,
                               "kind": getattr(d.kind, "value", d.kind), "reason": d.reason})
    cands = []
    for r in candidates:
        c: dict[str, Any] = {"format": r.format, "score": r.score}
        if r.error:
            c["error"] = r.error
        cands.append(c)
    return {
        "input": display_path(rel), "output": None, "size": size, "sha256": None,
        "status": status, "format": fmt, "variant": variant, "confidence": confidence,
        "probe_score": probe_score, "candidates": cands,
        "attempts": [{"format": f, "outcome": o} for f, o in attempts],
        "records_by_status": records, "fields_by_status": fields,
        "members": members, "damage": damage, "coverage": coverage,
        "warnings": list(warnings), "errors": list(errors),
    }


def new_report() -> dict[str, Any]:
    """An empty report; :func:`summarize` fills in the summary."""
    rep: dict[str, Any] = {
        "tool": "salvage", "version": __version__, "schema_version": validate.version("report"),
        "summary": {}, "files": [], "skipped": [], "errors": [],
    }
    summarize(rep)
    return rep


def summarize(rep: dict[str, Any]) -> None:
    """Recompute ``rep["summary"]`` from its files and skipped lists."""
    summary: dict[str, Any] = {"files": len(rep["files"])}
    summary.update(dict.fromkeys(FILE_STATUSES, 0))
    by_format: dict[str, int] = {}
    for entry in rep["files"]:
        if entry.get("status") in FILE_STATUSES:
            summary[entry["status"]] += 1
        fmt = str(entry.get("format"))
        by_format[fmt] = by_format.get(fmt, 0) + 1
    summary["skipped"] = len(rep["skipped"])
    summary["by_format"] = by_format
    rep["summary"] = summary
