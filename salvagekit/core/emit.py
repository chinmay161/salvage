"""Output JSON: the ONLY module that knows the per-file output shape.

The shape is the organizers' contract (kit/OUTPUT-CONTRACT.md, with the
decisions taken from kit/expected_outputs/), written down in
docs/output-format.md and salvagekit/core/schemas/official/output.schema.json.
"""

from __future__ import annotations

import errno
import json
import os
from typing import Any, Iterable, Iterator

from salvagekit.core.model import DecodeResult, Record, Status, json_safe

REPORT_NAME = "report.json"
UNKNOWN_FORMAT = "UNKNOWN"   # contract format name for "not identified"

# Record/field statuses that make a record carry "verified": false.
_NOT_VERIFIED = (Status.UNVERIFIED, Status.LOST)


def to_output(*, source_file: str, fmt: str, status: str,
              result: DecodeResult | None = None) -> dict[str, Any]:
    """Build one per-file output document, keys in contract order.

    ``result`` (None for a failed or unrecognized file) gives ``metadata``
    (its ``meta``), ``records`` (:func:`record_object` of each top-level
    record) and ``damage`` (:func:`damage_objects`, members included).
    Members' own records are not emitted (archive entries are records).
    """
    return {
        "source_file": display_path(source_file),
        "format": fmt,
        "status": status,
        "metadata": canonical(json_safe(result.meta)) if result is not None else {},
        "records": [record_object(r) for r in result.records] if result is not None else [],
        "damage": damage_objects(result) if result is not None else [],
    }


def record_object(rec: Record) -> dict[str, Any]:
    """One record as a flat object: ``{field.name: value}`` in field order, then
    ``"verified": false`` if the record or any of its fields is UNVERIFIED or
    LOST, then ``"issues": [kinds]`` (de-duplicated, in order) if any.

    Verified/consistent records carry no "verified" key (as in
    kit/expected_outputs/). Dict values are key-sorted (determinism).
    """
    out: dict[str, Any] = {}
    for fld in rec.fields:
        out[str(fld.name)] = canonical(json_safe(fld.value))
    if rec.status in _NOT_VERIFIED or any(f.status in _NOT_VERIFIED for f in rec.fields):
        out["verified"] = False
    issues = list(dict.fromkeys(json_safe(k) for k in rec.issues))
    if issues:
        out["issues"] = issues
    return out


def walk_results(result: DecodeResult) -> Iterator[DecodeResult]:
    """``result`` and all nested members, depth first."""
    yield result
    for member in result.members:
        yield from walk_results(member)


def damage_objects(result: DecodeResult) -> list[dict[str, Any]]:
    """Every damage of ``result`` and its members (depth first) as
    ``{"kind", "offset", "detail", "lossy"}``; ``offset`` is the absolute
    start of the damaged range in the input file."""
    return [{"kind": json_safe(d.kind), "offset": d.start, "detail": str(d.reason),
             "lossy": bool(d.lossy)}
            for res in walk_results(result) for d in res.damage]


def canonical(value: Any) -> Any:
    """``value`` with every dict's keys sorted (recursively); lists keep their order.

    Decoder-made dicts (metadata, dict values) are sorted so their order
    never depends on how they were built (e.g. from a set).
    """
    if isinstance(value, dict):
        return {k: canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def dumps(obj: Any) -> str:
    """Canonical text: indented, keys in insertion order, real UTF-8 characters,
    final LF. Every builder inserts keys in a fixed order (see :func:`canonical`)."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


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


def output_names(names: Iterable[str], case_insensitive: bool = True) -> dict[str, str]:
    """Map each input file name (inputs are top-level files only) to its
    output file name.

    Default: exactly ``"<name>.json"`` (the contract). Only on a collision
    is ``~2``, ``~3``, ... inserted before ``.json``, assigned in sorted input
    order: with ``report.json`` (an input named ``report``), or, when the
    output folder's file system is ``case_insensitive``, with a name that
    differs only in case (compared with ``casefold()``).
    """
    def key(name: str) -> str:
        return name.casefold() if case_insensitive else name

    taken = {key(REPORT_NAME)}
    out: dict[str, str] = {}
    for name in sorted(set(names)):
        target = name + ".json"
        n = 1
        while key(target) in taken:
            n += 1
            target = f"{name}~{n}.json"
        taken.add(key(target))
        out[name] = target
    return out


PROBE_NAME = ".salvage-case-probe"


def is_case_insensitive(folder: str) -> bool:
    """True if file names in ``folder`` are case-insensitive (Windows, macOS
    default, some Docker bind mounts). Checked once per run by creating a
    probe file (exclusively, so nothing is ever overwritten) and looking it up
    with its case swapped; the probe is removed again. If the folder cannot
    be probed the answer is True: the safe side (more ``~N`` renames, never
    an overwrite)."""
    for n in range(100):
        name = f"{PROBE_NAME}-{n}.tmp"
        path = os.path.join(folder, name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        except OSError:
            return True
        os.close(fd)
        try:
            swapped = os.path.join(folder, name.upper())
            try:
                return os.path.samefile(path, swapped)
            except OSError as exc:
                if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                    return False
                return True
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return True


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
