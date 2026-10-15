"""Decode result data model (part of the frozen Phase 0 contract).

Every decoder returns a :class:`DecodeResult`. Offsets and lengths are
ABSOLUTE positions in the input file. For a value that came from
transformed data (decompressed, XOR-decoded, ...), point at the source bytes
in the file and say so in ``evidence``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Iterable

JSONValue = Any  # None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]


class Status(str, Enum):
    """How much a decoded value can be trusted.

    Rank: VERIFIED 3 > CONSISTENT 2 > UNVERIFIED 1 > LOST 0.
    ``verified`` needs real evidence (checksum, round trip, exact magic match).
    """

    VERIFIED = "verified"
    CONSISTENT = "consistent"
    UNVERIFIED = "unverified"
    LOST = "lost"

    @property
    def rank(self) -> int:
        """Numeric trust rank: 3 (verified) down to 0 (lost)."""
        return _STATUS_RANK[self]

    @staticmethod
    def worst(statuses: Iterable[Any]) -> "Status":
        """Return the lowest-ranked status; an empty input gives UNVERIFIED.

        Values that are not valid statuses count as LOST. Never raises.
        """
        worst: Status | None = None
        try:
            for item in statuses:
                try:
                    status = Status(item)
                except Exception:
                    status = Status.LOST
                if worst is None or status.rank < worst.rank:
                    worst = status
        except Exception:
            return Status.LOST if worst is None else Status.worst([worst, Status.LOST])
        return Status.UNVERIFIED if worst is None else worst


_STATUS_RANK = {
    Status.VERIFIED: 3,
    Status.CONSISTENT: 2,
    Status.UNVERIFIED: 1,
    Status.LOST: 0,
}


class DamageKind(str, Enum):
    """Category of a damaged byte range."""

    TRUNCATED = "truncated"
    CHECKSUM = "checksum"
    BOUNDS = "bounds"
    UNPARSED = "unparsed"
    OTHER = "other"


@dataclass
class Field:
    """One decoded value.

    ``offset``/``length`` are absolute positions of the source bytes in the
    input file. ``value`` must be JSON-safe (see :func:`json_safe`).
    """

    name: str
    value: JSONValue
    offset: int
    length: int
    status: Status
    evidence: str = ""


@dataclass
class Record:
    """A group of fields starting at an absolute file offset."""

    offset: int
    status: Status
    kind: str = "record"
    fields: list[Field] = field(default_factory=list)


@dataclass
class Damage:
    """A damaged byte range ``[start, end)`` in the input file."""

    start: int
    end: int
    kind: DamageKind
    reason: str


@dataclass
class DecodeResult:
    """Everything a decoder recovered from one file (or archive member).

    ``members`` holds archive entries, each a nested DecodeResult whose
    ``name`` is the member file name inside the archive.
    """

    format: str
    confidence: float
    records: list[Record] = field(default_factory=list)
    members: list["DecodeResult"] = field(default_factory=list)
    damage: list[Damage] = field(default_factory=list)
    meta: dict[str, JSONValue] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    name: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a plain, JSON-safe dict. Deterministic; never raises.

        Key order follows dataclass field order; enums become their string
        values; nested members are included.
        """
        try:
            out = _to_plain(self)
            return out if isinstance(out, dict) else {"format": json_safe(out)}
        except Exception as exc:  # pragma: no cover - defensive
            return {"format": json_safe(getattr(self, "format", None)),
                    "error": f"<to_dict failed: {type(exc).__name__}>"}

    def validate(self, file_size: int) -> list[str]:
        """Return a list of contract problems (empty if valid). Never raises.

        Checks confidence in [0, 1], that every Field/Record lies within
        ``[0, file_size]``, lengths are non-negative, damage ranges satisfy
        ``0 <= start <= end <= file_size``, statuses are :class:`Status`
        members, and recurses into ``members``.
        """
        problems: list[str] = []
        try:
            _validate_result(self, file_size, "", problems)
        except Exception as exc:  # pragma: no cover - defensive
            problems.append(f"validate failed: {type(exc).__name__}")
        return problems


def json_safe(value: Any) -> JSONValue:
    """Convert ``value`` to something ``json.dumps`` accepts. Never raises.

    None/bool/int/str pass through; finite floats pass through; NaN/inf
    become "nan"/"inf"/"-inf"; bytes become lowercase hex; lists/tuples
    become lists; dicts get str keys; enums become their ``.value``;
    anything else becomes ``"<unserializable TypeName>"``.
    """
    try:
        return _json_safe(value, set(), 0)
    except Exception:
        return _unserializable(value)


_MAX_DEPTH = 100  # deeper (or cyclic) containers are reported as unserializable


def _unserializable(value: Any) -> str:
    try:
        return f"<unserializable {type(value).__name__}>"
    except Exception:  # pragma: no cover - defensive
        return "<unserializable ?>"


def _json_safe(value: Any, active: set[int], depth: int) -> JSONValue:
    if value is None or value is True or value is False:
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value, active, depth + 1)
    if isinstance(value, bool):  # pragma: no cover - bool subclasses are impossible
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple, dict)):
        if id(value) in active or depth >= _MAX_DEPTH:
            return _unserializable(value)
        active.add(id(value))
        try:
            if isinstance(value, dict):
                return {_json_key(k): _json_safe(v, active, depth + 1)
                        for k, v in value.items()}
            return [_json_safe(v, active, depth + 1) for v in value]
        finally:
            active.discard(id(value))
    return _unserializable(value)


def _json_key(key: Any) -> str:
    if isinstance(key, str) and not isinstance(key, Enum):
        return str(key)
    safe = json_safe(key)
    if isinstance(safe, str):
        return safe
    if safe is None:
        return "null"
    if safe is True or safe is False:
        return "true" if safe else "false"
    if isinstance(safe, (int, float)):
        return repr(safe)
    return _unserializable(key)


def _to_plain(obj: Any) -> JSONValue:
    if is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, JSONValue] = {}
        for f in fields(obj):
            out[f.name] = _to_plain(getattr(obj, f.name, None))
        return out
    if isinstance(obj, (list, tuple)) and any(is_dataclass(v) for v in obj):
        return [_to_plain(v) for v in obj]
    return json_safe(obj)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_result(res: Any, file_size: int, path: str, problems: list[str]) -> None:
    if not isinstance(res, DecodeResult):
        problems.append(f"{path or 'result'}: not a DecodeResult")
        return
    p = path

    conf = res.confidence
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        problems.append(f"{p}confidence: not a number")
    elif math.isnan(conf) or conf < 0 or conf > 1:
        problems.append(f"{p}confidence: {conf!r} outside [0, 1]")

    if not _is_int(file_size) or file_size < 0:
        problems.append(f"{p}file_size: invalid {type(file_size).__name__}")
        return

    for attr in ("records", "members", "damage", "warnings"):
        if not isinstance(getattr(res, attr, None), list):
            problems.append(f"{p}{attr}: not a list")
    if not isinstance(res.meta, dict):
        problems.append(f"{p}meta: not a dict")

    for ri, rec in enumerate(_as_list(res.records)):
        rp = f"{p}records[{ri}]"
        if not isinstance(rec, Record):
            problems.append(f"{rp}: not a Record")
            continue
        _check_status(rec.status, rp, problems)
        if not _is_int(rec.offset):
            problems.append(f"{rp}.offset: not an int")
        elif not 0 <= rec.offset <= file_size:
            problems.append(f"{rp}.offset: {rec.offset} outside [0, {file_size}]")
        for fi, fld in enumerate(_as_list(rec.fields)):
            fp = f"{rp}.fields[{fi}]"
            if not isinstance(fld, Field):
                problems.append(f"{fp}: not a Field")
                continue
            _check_status(fld.status, fp, problems)
            ok = True
            if not _is_int(fld.offset):
                problems.append(f"{fp}.offset: not an int")
                ok = False
            elif not 0 <= fld.offset <= file_size:
                problems.append(f"{fp}.offset: {fld.offset} outside [0, {file_size}]")
                ok = False
            if not _is_int(fld.length):
                problems.append(f"{fp}.length: not an int")
                ok = False
            elif fld.length < 0:
                problems.append(f"{fp}.length: {fld.length} is negative")
                ok = False
            if ok and fld.offset + fld.length > file_size:
                problems.append(
                    f"{fp}: offset+length {fld.offset + fld.length} beyond file size {file_size}")

    for di, dmg in enumerate(_as_list(res.damage)):
        dp = f"{p}damage[{di}]"
        if not isinstance(dmg, Damage):
            problems.append(f"{dp}: not a Damage")
            continue
        if not isinstance(dmg.kind, DamageKind):
            problems.append(f"{dp}.kind: not a DamageKind")
        if not (_is_int(dmg.start) and _is_int(dmg.end)):
            problems.append(f"{dp}: start/end not ints")
        elif not 0 <= dmg.start <= dmg.end <= file_size:
            problems.append(
                f"{dp}: range [{dmg.start}, {dmg.end}) violates 0 <= start <= end <= {file_size}")

    for mi, member in enumerate(_as_list(res.members)):
        _validate_result(member, file_size, f"{p}members[{mi}].", problems)


def _check_status(status: Any, path: str, problems: list[str]) -> None:
    if not isinstance(status, Status):
        problems.append(f"{path}.status: {json_safe(status)!r} is not a Status member")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []
