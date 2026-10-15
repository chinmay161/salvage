"""Enforce MAX_RECORDS / MAX_MEMBERS on a decoded result (worker side)."""

from __future__ import annotations

from salvage.core import limits
from salvage.core.model import DecodeResult


def enforce(result: DecodeResult, max_records: int | None = None,
            max_members: int | None = None) -> list[str]:
    """Cut ``result`` in place to the record and member limits.

    Counts include nested members at every depth, visited depth first in
    order; whatever comes after the limit is dropped. Each cap adds the
    warning "output capped at N records" / "output capped at N members" to
    ``result.warnings`` and is returned, so the caller can mark the file
    "partial". Defaults come from :mod:`salvage.core.limits` at call time.
    """
    max_records = limits.MAX_RECORDS if max_records is None else max_records
    max_members = limits.MAX_MEMBERS if max_members is None else max_members
    notes: list[str] = []

    members_left = [max_members]
    members_cut = [False]

    def cut_members(res: DecodeResult) -> None:
        keep = []
        for member in res.members:
            if members_left[0] <= 0:
                members_cut[0] = True
                break
            members_left[0] -= 1
            keep.append(member)
            cut_members(member)
        if len(keep) != len(res.members):
            res.members = keep

    records_left = [max_records]
    records_cut = [False]

    def cut_records(res: DecodeResult) -> None:
        if len(res.records) > records_left[0]:
            res.records = res.records[:records_left[0]]
            records_cut[0] = True
        records_left[0] -= len(res.records)
        for member in res.members:
            cut_records(member)

    cut_members(result)
    cut_records(result)
    if records_cut[0]:
        notes.append(f"output capped at {max_records} records")
    if members_cut[0]:
        notes.append(f"output capped at {max_members} members")
    result.warnings.extend(notes)
    return notes
