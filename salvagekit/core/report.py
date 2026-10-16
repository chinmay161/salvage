"""report.json: the contract's files/totals plus our diagnostics, and file status.

Shape: docs/output-format.md and schemas/official/report.schema.json.
No timestamps, durations, PIDs or absolute paths.
"""

from __future__ import annotations

from typing import Any, Iterable

from salvagekit import __version__
from salvagekit.core.emit import display_path, walk_results
from salvagekit.core.model import DecodeResult, Status

TRUST = ("verified", "consistent", "unverified", "lost")
FILE_STATUSES = ("ok", "partial", "unsupported", "unrecognized", "failed")

_NOT_OK = (Status.UNVERIFIED, Status.LOST)


def file_status(result: DecodeResult) -> str:
    """Status of a decoded file (members included, recursively):

    "unsupported" if ``result.unsupported``; else "partial" if there is any
    damage or any record/field is UNVERIFIED or LOST; else "ok". (A capped
    output is "partial" too; the caller knows about caps.)
    """
    if result.unsupported:
        return "unsupported"
    for res in walk_results(result):
        if res.damage:
            return "partial"
        for rec in res.records:
            if rec.status in _NOT_OK or any(f.status in _NOT_OK for f in rec.fields):
                return "partial"
    return "ok"


def make_entry(*, rel: str, size: int, status: str, fmt: str, confidence: float,
               candidates: Iterable[Any] = (), attempts: Iterable[tuple[str, str]] = (),
               result: DecodeResult | None = None, warnings: Iterable[str] = (),
               errors: Iterable[str] = (), variant: str | None = None,
               probe_score: float = 0.0, coverage: dict[str, Any] | None = None,
               facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """One diagnostics entry. ``output`` and ``sha256`` are filled in by the pipeline.

    ``candidates`` are :class:`~salvagekit.core.identify.Ranked`; ``attempts``
    are ``(format, outcome)`` pairs. Counts include members, recursively.
    ``coverage`` is :func:`salvagekit.core.coverage.coverage` (None for failed
    files); ``facts`` is the byte description of an unrecognized file
    (:func:`salvagekit.core.fallback.unknown`'s meta), else None.
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
                               "kind": getattr(d.kind, "value", d.kind), "reason": d.reason,
                               "lossy": bool(d.lossy)})
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
        "members": members, "damage": damage, "coverage": coverage, "bytes": facts,
        "warnings": list(warnings), "errors": list(errors),
    }


def file_row(output: dict[str, Any]) -> dict[str, Any]:
    """The contract's report ``files[]`` row for one per-file output."""
    return {"file": output.get("source_file"), "format": output.get("format"),
            "status": output.get("status"), "records": len(output.get("records") or []),
            "damage": len(output.get("damage") or [])}


def new_report() -> dict[str, Any]:
    """An empty report; :func:`summarize` fills in totals and the summary."""
    rep: dict[str, Any] = {
        "tool_version": __version__,
        "files": [],
        "totals": {},
        "diagnostics": {"summary": {}, "files": [], "skipped": [], "warnings": [],
                        "errors": []},
    }
    summarize(rep)
    return rep


def summarize(rep: dict[str, Any]) -> None:
    """Recompute ``totals`` (every status, zeros included) and the
    diagnostics summary from the report's rows."""
    totals = dict.fromkeys(FILE_STATUSES, 0)
    by_format: dict[str, int] = {}
    for row in rep["files"]:
        if row.get("status") in totals:
            totals[row["status"]] += 1
        fmt = str(row.get("format"))
        by_format[fmt] = by_format.get(fmt, 0) + 1
    rep["totals"] = totals
    diag = rep["diagnostics"]
    diag["summary"] = {"files": len(rep["files"]), "skipped": len(diag["skipped"]),
                       "by_format": {k: by_format[k] for k in sorted(by_format)}}
