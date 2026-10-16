"""Compare our outputs on kit/samples/ with the organizers' kit/expected_outputs/.

    python tools/task.py calibrate [FILE]

A dev tool for decoder owners (not part of ``task.py test``): it runs the
CLI on the samples that have an expected output (or only FILE, e.g.
``s01.dat``) and prints, per file, MATCH or the number of differences plus
up to 30 JSON-path differences. Exit code 0 only if every file matches.

The expected outputs are answer keys, not literal outputs, so the comparison
follows their keys (docs/output-format.md, "Expected-output decisions"):

* ``file`` is compared with our ``source_file``; ``format`` and ``status``
  must be equal.
* ``metadata``: every key must match exactly; keys we add or miss are
  differences.
* ``records`` are matched on the ``match_on`` keys (order does not matter);
  each matched record must have exactly the expected keys and values
  (``"verified"``/``"issues"`` included). A record we emit that is not
  expected is a difference, unless it matches ``optional_partial_records``.
* ``expected_damage``: each entry ``{"any_of": [kinds], "lossy": bool}``
  needs one damage of ours with a kind in ``any_of`` (and that ``lossy``);
  damage of ours that no entry accounts for is a difference.

Values compare as JSON: ``1 == 1.0``, ``true != 1``, floats exactly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "kit" / "samples"
EXPECTED = ROOT / "kit" / "expected_outputs"
MAX_SHOWN = 30
SUFFIX = ".json"


def _show(value: Any, width: int = 70) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= width else text[:width - 3] + "..."


def _same(a: Any, b: Any) -> bool:
    if type(a) is bool or type(b) is bool:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _diff(exp: Any, got: Any, path: str, out: list[str]) -> None:
    """Deep JSON differences, one line each (dict keys in expected order, then extras)."""
    if isinstance(exp, dict) and isinstance(got, dict):
        for key in exp:
            sub = f"{path}.{key}"
            if key not in got:
                out.append(f"{sub}: expected {_show(exp[key])}, got nothing (key missing)")
            else:
                _diff(exp[key], got[key], sub, out)
        for key in got:
            if key not in exp:
                out.append(f"{path}.{key}: not expected (extra key), got {_show(got[key])}")
        return
    if isinstance(exp, list) and isinstance(got, list):
        if len(exp) != len(got):
            out.append(f"{path}: expected {len(exp)} items, got {len(got)}")
        for i, (e, g) in enumerate(zip(exp, got)):
            _diff(e, g, f"{path}[{i}]", out)
        return
    if not _same(exp, got):
        out.append(f"{path}: expected {_show(exp)}, got {_show(got)}")


def _key(record: Any, match_on: list[str]) -> tuple | None:
    if not isinstance(record, dict) or any(k not in record for k in match_on):
        return None
    return tuple(json.dumps(record[k], sort_keys=True) for k in match_on)


def _label(record: dict[str, Any], match_on: list[str]) -> str:
    return ",".join(f"{k}={_show(record.get(k), 30)}" for k in match_on)


def compare(expected: dict[str, Any], got: dict[str, Any]) -> list[str]:
    """Every difference between one answer key and our per-file output."""
    out: list[str] = []
    if "file" in expected and expected["file"] != got.get("source_file"):
        out.append(f"source_file: expected {_show(expected['file'])}, "
                   f"got {_show(got.get('source_file'))}")
    for key in ("format", "status"):
        if key in expected and not _same(expected[key], got.get(key)):
            out.append(f"{key}: expected {_show(expected[key])}, got {_show(got.get(key))}")
    if "metadata" in expected:
        _diff(expected["metadata"], got.get("metadata"), "metadata", out)

    match_on = list(expected.get("match_on") or [])
    ours = [r for r in got.get("records") or []]
    if match_on:
        by_key: dict[tuple, list[dict[str, Any]]] = {}
        for r in ours:
            k = _key(r, match_on)
            if k is None:
                out.append(f"records: a record without the match_on keys {match_on}: {_show(r)}")
                continue
            by_key.setdefault(k, []).append(r)
        seen: set[tuple] = set()
        for exp in expected.get("records") or []:
            k = _key(exp, match_on)
            where = f"records[{_label(exp, match_on)}]"
            if k not in by_key:
                out.append(f"{where}: missing (expected {_show(exp)})")
                continue
            seen.add(k)
            if len(by_key[k]) > 1:
                out.append(f"{where}: {len(by_key[k])} records have this key")
            _diff(exp, by_key[k][0], where, out)
        optional = {_key(r, match_on) for r in expected.get("optional_partial_records") or []}
        for k, recs in by_key.items():
            if k not in seen and k not in optional:
                out.append(f"records[{_label(recs[0], match_on)}]: not expected "
                           f"(extra record) {_show(recs[0])}")
    elif "records" in expected:
        _diff(expected["records"], ours, "records", out)

    if "expected_damage" in expected:
        damage = [d for d in got.get("damage") or [] if isinstance(d, dict)]
        used = [False] * len(damage)
        for spec in expected["expected_damage"]:
            kinds = list(spec.get("any_of") or [])
            for i, d in enumerate(damage):
                if used[i] or d.get("kind") not in kinds:
                    continue
                if "lossy" in spec and d.get("lossy") is not spec["lossy"]:
                    continue
                used[i] = True
                break
            else:
                lossy = f", lossy {_show(spec['lossy'])}" if "lossy" in spec else ""
                out.append(f"damage: expected a damage of kind {' or '.join(kinds)}{lossy}, "
                           "found none")
        for i, d in enumerate(damage):
            if not used[i]:
                out.append(f"damage[{i}]: not expected (no expected_damage entry accounts for "
                           f"it) {_show(d)}")
    return out


def run_samples(names: list[str], tmp: str) -> str:
    """Copy the named samples into ``tmp``/in, run the CLI, return the output dir."""
    inp, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
    os.makedirs(inp)
    for name in names:
        shutil.copyfile(SAMPLES / name, os.path.join(inp, name))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"]
                                     if env.get("PYTHONPATH") else "")
    subprocess.run([sys.executable, "-m", "salvagekit.cli", inp, out], env=env,
                   capture_output=True, timeout=600)
    return out


def main(argv: list[str]) -> int:
    """Run the comparison; print per-file results and the summary."""
    keys = sorted(p.name for p in EXPECTED.glob("*" + SUFFIX)) if EXPECTED.is_dir() else []
    if argv:
        want = argv[0]
        want = want if want.endswith(SUFFIX) else want + SUFFIX
        if want not in keys:
            print(f"error: no expected output for {argv[0]!r} in "
                  f"{EXPECTED.relative_to(ROOT).as_posix()}/", file=sys.stderr)
            return 2
        keys = [want]
    if not keys:
        print("error: no expected outputs found", file=sys.stderr)
        return 2
    samples = [k[:-len(SUFFIX)] for k in keys]
    missing = [s for s in samples if not (SAMPLES / s).is_file()]
    if missing:
        print(f"error: samples missing from kit/samples/: {', '.join(missing)}",
              file=sys.stderr)
        return 2
    tmp = tempfile.mkdtemp(prefix="salvage-calibrate-")
    try:
        out = run_samples(samples, tmp)
        matched = 0
        width = max(len(s) for s in samples)
        for key, sample in zip(keys, samples):
            with open(EXPECTED / key, encoding="utf-8") as fh:
                expected = json.load(fh)
            try:
                with open(os.path.join(out, key), encoding="utf-8") as fh:
                    got = json.load(fh)
                diffs = compare(expected, got)
            except (OSError, ValueError) as exc:
                diffs = [f"no usable output {key}: {exc}"]
            if not diffs:
                matched += 1
                print(f"{sample:<{width}}  MATCH")
                continue
            print(f"{sample:<{width}}  {len(diffs)} difference{'s' if len(diffs) != 1 else ''}")
            for line in diffs[:MAX_SHOWN]:
                print(f"    {line}")
            if len(diffs) > MAX_SHOWN:
                print(f"    ... and {len(diffs) - MAX_SHOWN} more")
        print(f"calibrate: {matched}/{len(keys)} files match")
        return 0 if matched == len(keys) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
