"""Schema validation of every document Salvage writes.

Two documents are checked: each per-file output ("output") and
report.json ("report"). For each one the organizers' schema is used when
its file is present in ``schemas/official/`` (names in
:data:`SCHEMA_FILES`), else our provisional schema. An official schema that
cannot be used (unreadable, unsupported keywords) is reported by
:func:`load_problems` and the provisional one is used instead.

``python -m salvage.core.validate`` prints which schemas are active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from salvage.core.jsonschema_lite import Schema, SchemaError, load_schema

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

# Paths relative to SCHEMA_DIR, forward slashes. Rename the official entries
# here if the organizers' files are called something else.
SCHEMA_FILES: dict[str, dict[str, str]] = {
    "output": {"official": "official/output.schema.json",
               "provisional": "output.provisional.json"},
    "report": {"official": "official/report.schema.json",
               "provisional": "report.provisional.json"},
}

PROVISIONAL_VERSION = "provisional-1"
OFFICIAL_VERSION = "official"
KINDS = tuple(SCHEMA_FILES)


@dataclass(frozen=True)
class Active:
    """The schema in use for one kind of document.

    ``origin`` is "official" or "provisional"; ``file`` is relative to
    :data:`SCHEMA_DIR`; ``version`` is what that document's
    ``schema_version`` says. ``schema`` is None only if no schema could be
    loaded at all (then nothing is validated; see ``problems``).
    """

    kind: str
    origin: str
    file: str
    version: str
    schema: Schema | None
    problems: tuple[str, ...] = field(default=())


def _path(rel: str) -> str:
    return os.path.join(SCHEMA_DIR, *rel.split("/"))


@lru_cache(maxsize=None)
def active(kind: str) -> Active:
    """The schema used for ``kind`` ("output" or "report"); loaded once per process."""
    names = SCHEMA_FILES[kind]
    problems: list[str] = []
    official = names["official"]
    if os.path.isfile(_path(official)):
        try:
            return Active(kind, "official", official, OFFICIAL_VERSION,
                          load_schema(_path(official)))
        except SchemaError as exc:
            problems.append(f"official {kind} schema {official} not used: {exc}")
    provisional = names["provisional"]
    try:
        schema: Schema | None = load_schema(_path(provisional))
    except SchemaError as exc:
        schema = None
        problems.append(f"provisional {kind} schema {provisional} not usable, "
                        f"{kind} documents are NOT validated: {exc}")
    return Active(kind, "provisional", provisional, PROVISIONAL_VERSION, schema,
                  tuple(problems))


def version(kind: str) -> str:
    """``schema_version`` for documents of ``kind``."""
    return active(kind).version


def errors(kind: str, document: object, limit: int = 50) -> list[str]:
    """Validation errors of ``document`` against the active ``kind`` schema.

    [] means valid (or that no schema could be loaded; see
    :func:`load_problems`). Never raises.
    """
    try:
        schema = active(kind).schema
    except Exception as exc:  # pragma: no cover - defensive
        return [f"$: cannot load {kind} schema: {type(exc).__name__}: {exc}"]
    return [] if schema is None else schema.errors(document, limit)


def load_problems() -> list[str]:
    """Run-level problems with the schemas (unusable official/provisional files)."""
    out: list[str] = []
    for kind in KINDS:
        try:
            out.extend(active(kind).problems)
        except Exception as exc:  # pragma: no cover - defensive
            out.append(f"cannot load {kind} schema: {type(exc).__name__}: {exc}")
    return out


def main() -> int:
    """Print the active schemas and any load problems. Always returns 0."""
    for kind in KINDS:
        a = active(kind)
        state = "loaded" if a.schema is not None else "NOT LOADED"
        print(f"{kind}: {a.origin} {a.file} ({state}), schema_version {a.version!r}")
        for problem in a.problems:
            print(f"  problem: {problem}")
    return 0


if __name__ == "__main__":
    main()
