"""Golden tests: run real decoders on stored inputs and compare to stored outputs.

Layout, one folder per format (owned by that format's member)::

    tests/<format>/cases/<name>                  input file (any name)
    tests/<format>/cases/<name>.expected.json    expected per-file output

Used by tests/test_golden.py (checking) and ``tools/task.py golden-update``
(regenerating one format's expectations). Not a test module itself.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from salvage.core import emit, pipeline

TESTS = Path(__file__).resolve().parent
SUFFIX = ".expected.json"
MAX_DIFFS = 20


def case_dirs(fmt: str | None = None) -> dict[str, Path]:
    """``{format: tests/<format>/cases}`` for every folder that has one, by name."""
    found = {p.parent.name: p for p in sorted(TESTS.glob("*/cases")) if p.is_dir()}
    if fmt is not None:
        return {fmt: found[fmt]} if fmt in found else {}
    return found


def split_cases(cases: Path) -> tuple[list[str], list[str]]:
    """``(inputs, expectations)``: file names in ``cases``, sorted."""
    names = sorted(p.name for p in cases.iterdir() if p.is_file())
    return ([n for n in names if not n.endswith(SUFFIX)],
            [n for n in names if n.endswith(SUFFIX)])


def run_cases(cases: Path, package: str = "salvage.formats") -> dict[str, Any]:
    """Copy every input into a fresh temp dir, run the pipeline once, and
    return ``{input name: parsed per-file output}`` (None if not written)."""
    inputs, _ = split_cases(cases)
    tmp = tempfile.mkdtemp(prefix="salvage-golden-")
    try:
        inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
        os.makedirs(inp)
        for name in inputs:
            shutil.copyfile(cases / name, os.path.join(inp, name))
        rep = pipeline.run(inp, out, decoder_package=package, jobs=1)
        got: dict[str, Any] = {}
        for entry in rep["files"]:
            rel = entry.get("output")
            if rel is None:
                got[entry["input"]] = None
                continue
            with open(os.path.join(out, *rel.split("/")), encoding="utf-8") as fh:
                got[entry["input"]] = json.load(fh)
        return got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(cases: Path, package: str = "salvage.formats") -> dict[str, str | None]:
    """Compare every case in ``cases``; return ``{case: problem or None}``.

    Problems: "missing expectation", "orphan expectation", "no output
    written", or up to 20 JSON-path differences, one per line.
    """
    inputs, expectations = split_cases(cases)
    results: dict[str, str | None] = {}
    for exp in expectations:
        if exp[:-len(SUFFIX)] not in inputs:
            results[exp] = "orphan expectation (no input file named " \
                           f"{exp[:-len(SUFFIX)]!r})"
    if not inputs:
        return results
    got = run_cases(cases, package)
    for name in inputs:
        if name + SUFFIX not in expectations:
            results[name] = f"missing expectation ({name + SUFFIX} not found)"
            continue
        if got.get(name) is None:
            results[name] = "no output written"
            continue
        with open(cases / (name + SUFFIX), encoding="utf-8") as fh:
            expected = json.load(fh)
        diffs = diff(expected, got[name])
        results[name] = format_diffs(diffs) if diffs else None
    return results


def diff(expected: Any, got: Any, path: str = "", limit: int = MAX_DIFFS) -> list[str]:
    """Differences between two parsed JSON values as ``path: expected X, got Y``.

    At most ``limit`` lines. Dict keys are visited sorted; lists element by
    element (a length change is one line, then the common prefix).
    """
    out: list[str] = []
    _diff(expected, got, path, out, limit)
    return out


def _diff(exp: Any, got: Any, path: str, out: list[str], limit: int) -> None:
    if len(out) >= limit:
        return
    here = path or "<root>"
    if isinstance(exp, dict) and isinstance(got, dict):
        for key in sorted(set(exp) | set(got)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in got:
                _add(out, limit, f"{sub}: expected {_show(exp[key])}, got nothing (key missing)")
            elif key not in exp:
                _add(out, limit, f"{sub}: expected nothing (unexpected key), got {_show(got[key])}")
            else:
                _diff(exp[key], got[key], sub, out, limit)
        return
    if isinstance(exp, list) and isinstance(got, list):
        if len(exp) != len(got):
            _add(out, limit, f"{here}: expected {len(exp)} items, got {len(got)}")
        for i, (e, g) in enumerate(zip(exp, got)):
            _diff(e, g, f"{path}[{i}]", out, limit)
        return
    # JSON equality: 1 == 1.0, but true != 1.
    if type(exp) is bool or type(got) is bool:
        same = exp is got
    else:
        same = exp == got
    if not same:
        _add(out, limit, f"{here}: expected {_show(exp)}, got {_show(got)}")


def _add(out: list[str], limit: int, line: str) -> None:
    if len(out) < limit:
        out.append(line)


def _show(value: Any, width: int = 80) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return text if len(text) <= width else text[:width - 3] + "..."


def format_diffs(diffs: list[str]) -> str:
    """Lines for a failure message (already capped at MAX_DIFFS)."""
    head = f"{len(diffs)} difference(s)" + (f" (first {MAX_DIFFS})"
                                             if len(diffs) >= MAX_DIFFS else "")
    return head + ":\n" + "\n".join("  " + d for d in diffs)


def update(fmt: str, package: str = "salvage.formats") -> dict[str, list[str]]:
    """Regenerate ``tests/<fmt>/cases/*.expected.json`` from the current decoders.

    Only that folder is touched. Returns ``{"changed": [...], "added": [...],
    "unchanged": [...], "not_written": [...]}`` (expectation file names).
    Raises ValueError if the folder does not exist.
    """
    dirs = case_dirs(fmt)
    if not dirs:
        raise ValueError(f"tests/{fmt}/cases/ does not exist")
    cases = dirs[fmt]
    got = run_cases(cases, package)
    status: dict[str, list[str]] = {"changed": [], "added": [], "unchanged": [],
                                    "not_written": []}
    inputs, _ = split_cases(cases)
    for name in inputs:
        target = cases / (name + SUFFIX)
        if got.get(name) is None:
            status["not_written"].append(target.name)
            continue
        text = emit.dumps(got[name]).encode("utf-8")
        old = target.read_bytes() if target.is_file() else None
        if old == text:
            status["unchanged"].append(target.name)
            continue
        status["added" if old is None else "changed"].append(target.name)
        target.write_bytes(text)
    return status
