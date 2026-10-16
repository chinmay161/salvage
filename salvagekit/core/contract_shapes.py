"""Graded record and metadata shapes per format (kit/OUTPUT-CONTRACT.md, "Record shapes").

Used by the conformance suite (check C12) and by ``tools/task.py calibrate``;
never used to block output. Where the contract is silent the shapes follow
kit/expected_outputs/ (see docs/output-format.md, "Expected-output
decisions"):

* ``fields``: every graded record field, in contract order.
* ``conditional``: graded fields that appear only for some records (the
  expected outputs leave them out, rather than writing null, when they do
  not apply), with the condition in words.
* every other field is required on every record.
* ``nullable``: fields whose value may be null (the contract says so).
* ``enums``: allowed values of enum fields (checked when not null).
* ``metadata``: required metadata keys (only LABLOG, CVT and EBCDIC-DUMP are
  graded); extra metadata keys are allowed. ``metadata_enums`` likewise.

Records may also carry ``"verified": false`` and ``"issues": [...]``
(:data:`RECORD_EXTRAS`); nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONTRACT_FORMATS = ("LIBRA-98", "LABLOG", "VAULT", "WKS", "WPD", "BRAVO", "CVT",
                    "EBCDIC-DUMP", "WAD", "PAK")
UNKNOWN = "UNKNOWN"
FORMAT_NAMES = CONTRACT_FORMATS + (UNKNOWN,)

RECORD_EXTRAS = ("verified", "issues")


@dataclass(frozen=True)
class Shape:
    """The graded shape of one format's records and metadata."""

    fields: tuple[str, ...]
    conditional: dict[str, str] = field(default_factory=dict)
    nullable: frozenset[str] = frozenset()
    enums: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    metadata: tuple[str, ...] = ()
    metadata_enums: dict[str, tuple[Any, ...]] = field(default_factory=dict)

    @property
    def required(self) -> tuple[str, ...]:
        """Fields every record must have."""
        return tuple(f for f in self.fields if f not in self.conditional)


_ARCHIVE = Shape(fields=("name", "offset", "size", "sha256"))

SHAPES: dict[str, Shape] = {
    "LIBRA-98": Shape(
        fields=("id", "title", "author", "year", "price_cents", "copies", "isbn",
                "checked_out", "deleted", "reference_only", "due_date"),
        nullable=frozenset({"due_date"}),
    ),
    "LABLOG": Shape(
        fields=("sample", "time_ms", "values"),
        metadata=("instrument", "sample_interval_ms", "channels", "start_time_utc",
                  "declared_block_count", "events"),
    ),
    "VAULT": Shape(
        fields=("id", "name", "type", "size", "sha256", "compressed", "text", "width",
                "height"),
        conditional={"text": "type text", "width": "type bitmap", "height": "type bitmap"},
        enums={"type": ("text", "bitmap", "binary")},
    ),
    "WKS": Shape(
        fields=("cell", "row", "col", "type", "value", "alignment", "number_format",
                "iso_date", "cached_value", "formula_raw_hex"),
        conditional={"value": "not formulas", "alignment": "labels",
                     "number_format": "cells with a number format",
                     "iso_date": "date-formatted cells", "cached_value": "formulas",
                     "formula_raw_hex": "formulas"},
        enums={"type": ("label", "integer", "number", "formula", "blank"),
               "alignment": ("left", "right", "center", "repeat")},
    ),
    "WPD": Shape(
        fields=("index", "type", "text"),
        nullable=frozenset({"text"}),
        enums={"type": ("paragraph", "page_break")},
    ),
    "BRAVO": Shape(fields=("index", "text")),
    "CVT": Shape(
        fields=("slot", "text"),
        metadata=("name", "structure", "geos_type", "modified", "class_name", "author",
                  "description", "declared_blocks"),
        metadata_enums={"structure": ("seq", "vlir")},
    ),
    "EBCDIC-DUMP": Shape(
        fields=("student_id", "name", "dob", "gpa", "credits", "status", "balance"),
        metadata=("title", "run_date", "trailer_count", "trailer_credits_total"),
    ),
    "WAD": _ARCHIVE,
    "PAK": _ARCHIVE,
}


def record_problems(fmt: str, record: Any) -> list[str]:
    """Shape problems of one output record object of format ``fmt`` ([] if fine,
    or if ``fmt`` has no contract shape)."""
    shape = SHAPES.get(fmt)
    if shape is None:
        return []
    if not isinstance(record, dict):
        return ["record is not an object"]
    out: list[str] = []
    for name in shape.required:
        if name not in record:
            out.append(f"missing graded field {name!r}")
        elif record[name] is None and name not in shape.nullable:
            out.append(f"field {name!r} is null (the contract does not allow null)")
    for name in record:
        if name not in shape.fields and name not in RECORD_EXTRAS:
            out.append(f"field {name!r} is not a graded {fmt} field "
                       f"(allowed: {', '.join(shape.fields + RECORD_EXTRAS)})")
    for name, allowed in shape.enums.items():
        value = record.get(name)
        if value is not None and value not in allowed:
            out.append(f"field {name!r} is {value!r}, not one of {list(allowed)}")
    return out


def metadata_problems(fmt: str, metadata: Any) -> list[str]:
    """Problems with the graded metadata keys of format ``fmt`` ([] if fine)."""
    shape = SHAPES.get(fmt)
    if shape is None or not shape.metadata:
        return []
    if not isinstance(metadata, dict):
        return ["metadata is not an object"]
    out = [f"missing graded metadata key {name!r}" for name in shape.metadata
           if name not in metadata]
    for name, allowed in shape.metadata_enums.items():
        value = metadata.get(name)
        if value is not None and value not in allowed:
            out.append(f"metadata {name!r} is {value!r}, not one of {list(allowed)}")
    return out


def table() -> list[str]:
    """The shapes as Markdown table lines (docs, the phase report)."""
    lines = ["| format | record fields (required) | conditional | nullable | enums | "
             "graded metadata |", "|---|---|---|---|---|---|"]
    for fmt in CONTRACT_FORMATS:
        s = SHAPES[fmt]
        cond = ", ".join(f"{k} ({v})" for k, v in s.conditional.items()) or "-"
        enums = "; ".join(f"{k}: {'/'.join(map(str, v))}" for k, v in
                          {**s.enums, **{f"metadata.{k}": v
                                         for k, v in s.metadata_enums.items()}}.items()) or "-"
        lines.append(f"| {fmt} | {', '.join(s.required)} | {cond} | "
                     f"{', '.join(sorted(s.nullable)) or '-'} | {enums} | "
                     f"{', '.join(s.metadata) or '-'} |")
    return lines


if __name__ == "__main__":
    print("\n".join(table()))
