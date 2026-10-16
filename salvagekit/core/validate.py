"""Schema validation of every document Salvage writes.

Two documents are checked: each per-file output ("output") and
report.json ("report"), against the official schemas in
``schemas/official/`` (names in :data:`SCHEMA_FILES`). They encode the
organizers' output contract (kit/OUTPUT-CONTRACT.md); there is no
fallback. A schema that cannot be loaded is reported by
:func:`load_problems` (a run-level error) and that kind of document is then
not validated.

``python -m salvagekit.core.validate`` prints which schemas are active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from salvagekit.core.jsonschema_lite import Schema, SchemaError, load_schema

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

# Paths relative to SCHEMA_DIR, forward slashes.
SCHEMA_FILES: dict[str, str] = {
    "output": "official/output.schema.json",
    "report": "official/report.schema.json",
}

KINDS = tuple(SCHEMA_FILES)


@dataclass(frozen=True)
class Active:
    """The schema in use for one kind of document.

    ``file`` is relative to :data:`SCHEMA_DIR`. ``schema`` is None only if
    it could not be loaded (then nothing is validated; see ``problems``).
    """

    kind: str
    file: str
    schema: Schema | None
    problems: tuple[str, ...] = field(default=())

    @property
    def origin(self) -> str:
        """Always "official" (kept for messages that name the schema)."""
        return "official"


def _path(rel: str) -> str:
    return os.path.join(SCHEMA_DIR, *rel.split("/"))


@lru_cache(maxsize=None)
def active(kind: str) -> Active:
    """The schema used for ``kind`` ("output" or "report"); loaded once per process."""
    rel = SCHEMA_FILES[kind]
    try:
        return Active(kind, rel, load_schema(_path(rel)))
    except SchemaError as exc:
        return Active(kind, rel, None,
                      (f"official {kind} schema {rel} not usable, {kind} documents are NOT "
                       f"validated: {exc}",))


def errors(kind: str, document: object, limit: int = 50) -> list[str]:
    """Validation errors of ``document`` against the ``kind`` schema.

    [] means valid (or that the schema could not be loaded; see
    :func:`load_problems`). Never raises.
    """
    try:
        schema = active(kind).schema
    except Exception as exc:  # pragma: no cover - defensive
        return [f"$: cannot load {kind} schema: {type(exc).__name__}: {exc}"]
    return [] if schema is None else schema.errors(document, limit)


def load_problems() -> list[str]:
    """Run-level problems with the schemas (files that could not be loaded)."""
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
        print(f"{kind}: {a.origin} {a.file} ({state})")
        for problem in a.problems:
            print(f"  problem: {problem}")
    return 0


if __name__ == "__main__":
    main()
