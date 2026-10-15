"""Output JSON: the ONLY module that knows the per-file output shape.

The shape is PROVISIONAL ("provisional-1") until the real schema arrives;
see docs/output-format.md.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

SCHEMA_VERSION = "provisional-1"
REPORT_NAME = "report.json"


def to_output(*, rel: str, size: int, sha256: str | None, fmt: str,
              confidence: float, status: str, result: dict[str, Any] | None = None,
              warnings: Iterable[str] = (), errors: Iterable[str] = ()) -> dict[str, Any]:
    """Build one per-file output document.

    ``result`` is ``DecodeResult.to_dict()`` (or None for a failed file);
    records/members/damage/meta/warnings are taken from it. ``warnings`` are
    pipeline warnings appended after the decoder's own.
    """
    res = result or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"path": display_path(rel), "size": size, "sha256": sha256},
        "format": fmt,
        "confidence": confidence,
        "status": status,
        "records": list(res.get("records") or []),
        "members": list(res.get("members") or []),
        "damage": list(res.get("damage") or []),
        "meta": dict(res.get("meta") or {}),
        "warnings": list(res.get("warnings") or []) + list(warnings),
        "errors": list(errors),
    }


def dumps(obj: Any) -> str:
    """Canonical text: indented, sorted keys, real UTF-8 characters, final LF."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: str, obj: Any) -> None:
    """Write ``obj`` atomically (``<path>.tmp`` then ``os.replace``).

    Creates parent folders. UTF-8, LF line endings. Raises OSError (or a
    serialisation error) on failure; the caller records it.
    """
    text = dumps(obj)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        # backslashreplace: a lone surrogate (from a decoder string) becomes a
        # JSON \\uXXXX escape instead of an encoding error.
        with open(tmp, "w", encoding="utf-8", newline="\n", errors="backslashreplace") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def output_names(rel_paths: Iterable[str]) -> dict[str, str]:
    """Map each input POSIX relative path to its output relative path.

    Default ``"<rel>.json"`` mirroring subfolders. ``report.json`` at the root
    is reserved. Names are compared with ``casefold()``; a collision (with
    an earlier name, the report, or an output folder) inserts ``~2``,
    ``~3``, ... before ``.json``, assigned in sorted input order. A root
    folder whose name casefolds to ``report.json`` is renamed
    ``<name>~dir`` so the report can always be written.
    """
    rels = sorted(set(rel_paths))
    mapped: dict[str, list[str]] = {}
    dirs: set[str] = set()
    for rel in rels:
        parts = rel.split("/")
        if len(parts) > 1 and parts[0].casefold() == REPORT_NAME:
            parts[0] += "~dir"
        mapped[rel] = parts
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]).casefold())

    taken = {REPORT_NAME}
    out: dict[str, str] = {}
    for rel in rels:
        base = "/".join(mapped[rel])
        name = base + ".json"
        n = 1
        while name.casefold() in taken or name.casefold() in dirs:
            n += 1
            name = f"{base}~{n}.json"
        taken.add(name.casefold())
        out[rel] = name
    return out


def display_path(text: str) -> str:
    """``text`` made encodable as UTF-8 (undecodable file-name bytes escaped)."""
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        pass
    try:
        raw = text.encode("utf-8", "surrogateescape")
        return raw.decode("utf-8", "backslashreplace")
    except UnicodeError:
        return text.encode("utf-8", "backslashreplace").decode("utf-8")
