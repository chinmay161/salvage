"""Decoder conformance suite: check every decoder in a package against the contract.

    python -m tests.conformance [NAME] [--verbose]      (or: python tools/task.py conform)

:func:`run_conformance` finds the decoders, then for each one:

* reads its source with ``ast`` (C8 static rules) and checks its golden
  cases and docs folders (C10, C11);
* runs ALL decoder code in one spawn-context worker process (C1-C6, C9).
  The worker sends ``("start", step)`` before each step and ``("done",
  payload)`` after it; the parent gives every step a deadline and kills the
  worker on a timeout or crash, skipping that decoder's remaining steps;
* decodes the clean claimed inputs in two fresh interpreters with
  PYTHONHASHSEED=1 and 2 and compares the JSON (C7).

The parent never imports decoder modules, so a hanging or crashing decoder
cannot hang or crash the suite. Check IDs C1-C11 are part of the interface;
docs/conformance.md explains each one. Not a test module itself (see
tests/core/test_conformance.py and test_conformance_selftest.py).
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import contextlib
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import math
import multiprocessing
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from salvage.core import isolate, validate
from salvage.core.limits import MAX_FILE_BYTES, PROBE_THRESHOLD
from salvage.core.model import DecodeResult, Record, Status, json_safe
from salvage.core.plugin import Decoder, discover_decoders
from salvage.core.reader import SafeReader

ROOT = Path(__file__).resolve().parent.parent

CHECKS = {
    "C1": "metadata", "C2": "probe safety", "C3": "probe precision",
    "C4": "decode safety", "C5": "honesty", "C6": "round trip",
    "C7": "determinism", "C8": "static rules", "C9": "speed",
    "C10": "tests", "C11": "docs",
}
FAIL, WARN = "FAIL", "WARN"

PROBE_SPEED_BYTES = 8 * 1024 * 1024   # C2: probe on this much random data ...
PROBE_SPEED_LIMIT = 0.5               # ... must take at most this many seconds
DECODE_SPEED_LIMIT = 2.0              # C9: seconds per clean claimed input
BIG_INPUT = 1024 * 1024               # inputs over this get fewer variants
STARTUP_TIMEOUT = 60.0                # worker start-up + decoder import
GAP_TIMEOUT = 60.0                    # worker work between steps (reading, variants)
MAX_FINDINGS_PER_CHECK = 20           # per decoder; the rest are counted
_EPS = 1e-9                           # same slack as salvage.core.identify


# -- results -----------------------------------------------------------------

@dataclass
class Finding:
    """One problem found by a check. ``input``/``variant`` say where, if known."""

    check_id: str
    severity: str
    message: str
    input: str | None = None
    variant: str | None = None


@dataclass
class DecoderReport:
    """Conformance outcome for one decoder."""

    name: str
    module: str
    verdict: str = "PASS"
    inputs: int = 0          # claimed corpus inputs
    variants: int = 0        # mutated variants decoded
    findings: list[Finding] = field(default_factory=list)
    seconds: float = 0.0
    _hidden: dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == WARN)

    def add(self, check_id: str, severity: str, message: str,
            input: str | None = None, variant: str | None = None) -> None:
        """Record a finding; past MAX_FINDINGS_PER_CHECK per check only count it."""
        shown = sum(1 for f in self.findings if f.check_id == check_id)
        if shown >= MAX_FINDINGS_PER_CHECK:
            key = f"{check_id}/{severity}"
            self._hidden[key] = self._hidden.get(key, 0) + 1
            return
        self.findings.append(Finding(check_id, severity, message, input, variant))

    def finish(self) -> None:
        for key, n in sorted(self._hidden.items()):
            check_id, severity = key.split("/")
            self.findings.append(Finding(check_id, severity,
                                         f"... and {n} more {check_id} findings like these"))
        self._hidden.clear()
        self.findings.sort(key=lambda f: (int(f.check_id[1:]), f.severity != FAIL))
        self.verdict = FAIL if any(f.severity == FAIL for f in self.findings) else "PASS"


# -- inputs ------------------------------------------------------------------

@dataclass(frozen=True)
class CorpusFile:
    """A corpus input. ``owner`` is the module name of the cases folder, if any."""

    label: str
    path: str
    owner: str | None


@dataclass(frozen=True)
class Variant:
    """A mutated copy of an input; ``changed`` are the byte ranges [start, end) it changed."""

    name: str
    data: bytes
    changed: tuple[tuple[int, int], ...]


def display(path: str | Path) -> str:
    """``path`` relative to the repository root with forward slashes, if inside it."""
    full = Path(path).resolve()
    try:
        return full.relative_to(ROOT).as_posix()
    except ValueError:
        return full.as_posix()


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def corpus(cases_root: str | Path, samples_root: str | Path | None) -> list[CorpusFile]:
    """Every file under ``samples_root`` (None: no samples) plus every case
    input, sorted by label."""
    files: dict[str, CorpusFile] = {}
    samples = _resolve(samples_root) if samples_root is not None else None
    if samples is not None and samples.is_dir():
        for p in samples.rglob("*"):
            if p.is_file() and not p.is_symlink():
                files[display(p)] = CorpusFile(display(p), str(p), None)
    cases_base = _resolve(cases_root)
    if cases_base.is_dir():
        for cases in sorted(cases_base.glob("*/cases")):
            if not cases.is_dir():
                continue
            for p in cases.iterdir():
                if p.is_file() and not p.name.endswith(".expected.json"):
                    files[display(p)] = CorpusFile(display(p), str(p), cases.parent.name)
    return [files[k] for k in sorted(files)]


def synthetic_inputs() -> list[tuple[str, bytes]]:
    """The fixed synthetic inputs (label, bytes); the random one has a fixed seed."""
    return [
        ("<empty>", b""),
        ("<1 zero byte>", b"\x00"),
        ("<64 KB of 0x00>", bytes(65536)),
        ("<64 KB of 0xFF>", b"\xff" * 65536),
        ("<64 KB random>", random.Random("salvage-conformance/64k").randbytes(65536)),
    ]


def variants(data: bytes, decoder_name: str, quick: bool = False) -> Iterator[Variant]:
    """Mutated variants of ``data``, reproducible from (data, decoder_name, quick).

    Full: truncate (16 cuts, 8 over 1 MB), bitflip (20 bits, 10 over 1 MB),
    zero (3 x 64 bytes: start, middle, seeded), overwrite (3 x 16 random
    bytes), append (100 random bytes). Quick: truncate 8, bitflip 8, zero 2
    (start, middle), overwrite 2, append 1. All randomness is drawn up
    front from ``Random(sha256(data) + name)``. ``changed`` lists only bytes
    that really differ; variants equal to ``data`` or to an earlier variant
    are skipped.
    """
    n = len(data)
    rng = random.Random(hashlib.sha256(data).digest() + decoder_name.encode("utf-8"))
    big = n > BIG_INPUT
    plan: list[tuple[str, int, bytes]] = []
    if n:
        k = 8 if big or quick else 16
        cuts = sorted({(i * (n - 1)) // (k - 1) for i in range(k)})
        plan += [("truncate", c, b"") for c in cuts]
        flips = sorted(rng.sample(range(8 * n), min(8 if quick else 10 if big else 20, 8 * n)))
        plan += [("bitflip", p, b"") for p in flips]
        spots = [0, max(0, n // 2 - 32)]
        if not quick:
            spots.append(rng.randrange(max(1, n - 63)))
        plan += [("zero", s, bytes(min(64, n - s))) for s in spots]
        for _ in range(2 if quick else 3):
            s = rng.randrange(max(1, n - 15))
            plan.append(("overwrite", s, rng.randbytes(min(16, n - s))))
    plan.append(("append", n, rng.randbytes(100)))

    seen = {hashlib.sha256(data).digest()}
    for kind, pos, extra in plan:
        if kind == "truncate":
            v = Variant(f"truncate@{pos}", data[:pos], ((pos, n),))
        elif kind == "bitflip":
            i, bit = divmod(pos, 8)
            buf = bytearray(data)
            buf[i] ^= 1 << bit
            v = Variant(f"bitflip@{i}.{bit}", bytes(buf), ((i, i + 1),))
        elif kind == "append":
            v = Variant(f"append@{n}", data + extra, ((n, n + len(extra)),))
        else:
            changed = _diff_ranges(data, pos, extra)
            if not changed:
                continue
            v = Variant(f"{kind}@{pos}", data[:pos] + extra + data[pos + len(extra):], changed)
        digest = hashlib.sha256(v.data).digest()
        if digest in seen:
            continue
        seen.add(digest)
        yield v


def _diff_ranges(data: bytes, pos: int, block: bytes) -> tuple[tuple[int, int], ...]:
    out: list[tuple[int, int]] = []
    for i, b in enumerate(block):
        if data[pos + i] != b:
            if out and out[-1][1] == pos + i:
                out[-1] = (out[-1][0], pos + i + 1)
            else:
                out.append((pos + i, pos + i + 1))
    return tuple(out)


# -- C8: static rules ----------------------------------------------------------

FORBIDDEN_MODULES = frozenset({
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "subprocess",
    "multiprocessing", "threading", "asyncio", "ctypes", "os", "shutil", "pathlib",
    "tempfile", "glob", "random", "secrets", "time", "uuid", "locale"})
FORBIDDEN_CALLS = frozenset({
    "open", "eval", "exec", "compile", "__import__", "input", "hash", "id", "breakpoint"})
FORBIDDEN_ATTRS = frozenset({"now", "today", "utcnow"})


def static_problems(module: str, package: str) -> list[str]:
    """C8 violations in ``module`` and the private helpers it imports.

    Each is ``"<file>:<line>: <rule>"``. Code under ``if __name__ ==
    "__main__":`` is exempt. Locating a module imports its parent packages
    only, never the module itself.
    """
    problems: list[str] = []
    queue, seen = [module], set()
    while queue:
        mod = queue.pop(0)
        if mod in seen:
            continue
        seen.add(mod)
        try:
            spec = importlib.util.find_spec(mod)
            path = spec.origin if spec is not None else None
            if not path or not os.path.isfile(path):
                raise ImportError("source file not found")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (Exception, SystemExit) as exc:
            problems.append(f"{mod}: cannot read the source: {_exc_text(exc)}")
            continue
        is_pkg = os.path.basename(path) == "__init__.py"
        checker = _StaticChecker(mod, package, is_pkg)
        checker.visit(tree)
        problems += [f"{display(path)}:{line}: {rule}" for line, rule in checker.problems]
        queue += sorted(checker.helpers - seen)
    return problems


class _StaticChecker(ast.NodeVisitor):
    def __init__(self, module: str, package: str, is_pkg: bool) -> None:
        self.module, self.package = module, package
        self.base = module if is_pkg else module.rpartition(".")[0]
        self.problems: list[tuple[int, str]] = []
        self.helpers: set[str] = set()

    def _bad(self, node: ast.AST, rule: str) -> None:
        self.problems.append((getattr(node, "lineno", 0), rule))

    def visit_If(self, node: ast.If) -> None:
        if _is_main_guard(node.test):
            for child in node.orelse:   # only the guarded body is exempt
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(node, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            parts = self.base.split(".")
            keep = len(parts) - (node.level - 1)
            if keep <= 0:
                self._bad(node, "relative import goes above the top-level package")
                return
            base = ".".join(parts[:keep])
            full = f"{base}.{node.module}" if node.module else base
        else:
            full = node.module or ""
        if full == self.package or not node.module:
            for alias in node.names:   # "from pkg import x": x is a module
                self._check_import(node, f"{full}.{alias.name}")
        else:
            self._check_import(node, full)

    def _check_import(self, node: ast.AST, full: str) -> None:
        top = full.split(".")[0]
        if top in FORBIDDEN_MODULES:
            self._bad(node, f"forbidden import {full}")
        elif full == "salvage.core" or full.startswith("salvage.core."):
            return
        elif full.startswith(self.package + "."):
            short = full[len(self.package) + 1:].split(".")[0]
            if short.startswith("_"):
                self.helpers.add(f"{self.package}.{short}")
            else:
                self._bad(node, f"import {full} not allowed (another decoder's module; "
                                f"shared code goes in a private helper {self.package}._name)")
        elif top in sys.stdlib_module_names:
            return
        else:
            self._bad(node, f"import {full} not allowed (only the standard library, "
                            f"salvage.core and private helpers {self.package}._*)")

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
              and func.value.id == "builtins"):
            name = func.attr
        if name in FORBIDDEN_CALLS:
            self._bad(node, f"forbidden call {name}()")
        fname = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if fname == "fromtimestamp":
            has_tz = len(node.args) >= 2 or any(k.arg in ("tz", None) for k in node.keywords)
            if not has_tz:
                self._bad(node, "fromtimestamp() without a timezone (local time differs "
                                "between machines; pass tz=datetime.timezone.utc)")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTRS:
            self._bad(node, f"forbidden attribute .{node.attr} (the current time makes "
                            "output non-deterministic)")
        self.generic_visit(node)


def _is_main_guard(test: ast.expr) -> bool:
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1):
        return False
    sides = [test.left, test.comparators[0]]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    return has_name and has_main


# -- worker side (runs decoder code) ------------------------------------------

def load_decoder(module: str, name: str) -> Decoder:
    """Import ``module`` and instantiate its Decoder subclass called ``name``."""
    mod = importlib.import_module(module)
    for obj in list(vars(mod).values()):
        if (inspect.isclass(obj) and obj.__module__ == module and issubclass(obj, Decoder)
                and obj is not Decoder and getattr(obj, "name", None) == name):
            return obj()
    raise LookupError(f"no decoder named {name!r} in {module}")


def metadata_problems(dec: Decoder) -> list[str]:
    """C1: problems with ``name`` and ``extensions``."""
    out: list[str] = []
    name = getattr(dec, "name", None)
    if not isinstance(name, str) or not name:
        out.append("name is empty or not a string")
    elif len(name) > 32:
        out.append(f"name {name!r} is longer than 32 characters")
    elif not re.fullmatch(r"[A-Z0-9 ._-]+", name):
        out.append(f"name {name!r} may only use uppercase letters, digits, space and . - _")
    ext = getattr(dec, "extensions", None)
    if not isinstance(ext, tuple):
        out.append(f"extensions must be a tuple, got {type(ext).__name__}")
    else:
        for e in ext:
            if not isinstance(e, str) or not e.startswith(".") or e != e.lower():
                out.append(f"extension {e!r} must be a lowercase string starting with '.'")
    return out


def _exc_text(exc: BaseException) -> str:
    try:
        message = str(exc)
    except Exception:
        message = "<unprintable message>"
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _exc_where(exc: BaseException) -> str:
    """``Type: message (at file:line in func)`` for the last traceback frame."""
    text = _exc_text(exc)
    try:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        text += f" (at {display(frame.filename)}:{frame.lineno} in {frame.name})"
    except Exception:
        pass
    return text


def _probe_once(dec: Decoder, data: bytes) -> dict[str, Any]:
    try:
        value = dec.probe(data)
    except (Exception, SystemExit) as exc:
        return {"error": _exc_where(exc), "value": None, "bad": None}
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"error": None, "value": None,
                "bad": f"returned {type(value).__name__}, not an int or float"}
    value = float(value)
    if not math.isfinite(value):
        return {"error": None, "value": None, "bad": f"returned {value!r}"}
    if not 0.0 <= value <= 1.0:
        return {"error": None, "value": value, "bad": f"returned {value!r}, outside [0, 1]"}
    return {"error": None, "value": value, "bad": None}


def _short(value: Any) -> tuple[str, str]:
    """(digest, display) of a JSON value: compare by digest, show <= 60 chars."""
    text = json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False)
    shown = text if len(text) <= 60 else text[:57] + "..."
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), shown


def _walk(res: Any, depth: int = 0) -> Iterator[Record]:
    if depth > 100:
        return
    for rec in list(getattr(res, "records", None) or []):
        if isinstance(rec, Record):
            yield rec
    for member in list(getattr(res, "members", None) or []):
        if isinstance(member, DecodeResult):
            yield from _walk(member, depth + 1)


def _any_damage(res: Any, depth: int = 0) -> bool:
    if depth > 100 or not isinstance(res, DecodeResult):
        return False
    return bool(res.damage) or any(_any_damage(m, depth + 1) for m in res.members or [])


def decode_summary(dec: Decoder, data: bytes, all_fields: bool,
                   keep: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decode ``data`` directly and describe the result (plain data, picklable).

    ``fields``: ``[name, offset, length, status, digest, display]``, all
    fields if ``all_fields`` else only verified ones. The DecodeResult itself
    is stored in ``keep["result"]`` if ``keep`` is given.
    """
    out: dict[str, Any] = {"error": None, "problems": [], "fields": [], "verified": 0,
                           "damage": False, "lost": False, "records": False,
                           "empty": True, "seconds": 0.0}
    start = time.perf_counter()
    try:
        result = dec.decode(SafeReader(data))
    except (Exception, SystemExit) as exc:
        out["seconds"] = time.perf_counter() - start
        out["error"] = _exc_where(exc)
        return out
    out["seconds"] = time.perf_counter() - start
    if keep is not None:
        keep["result"] = result
    if not isinstance(result, DecodeResult):
        out["problems"] = [f"decode returned {type(result).__name__}, not a DecodeResult"]
        return out
    problems = result.validate(len(data))
    if problems:
        more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
        out["problems"].append("result.validate() reports: " + "; ".join(problems[:3]) + more)
    try:
        json.dumps(result.to_dict(), allow_nan=False)
    except Exception as exc:
        out["problems"].append(f"to_dict() is not JSON-serializable: {_exc_text(exc)}")
    out["empty"] = not result.records and not result.members
    try:
        out["damage"] = _any_damage(result)
        for rec in _walk(result):
            out["records"] = True
            if rec.status == Status.LOST:
                out["lost"] = True
            for fld in list(rec.fields or []):
                if not hasattr(fld, "status"):
                    continue
                if fld.status == Status.LOST:
                    out["lost"] = True
                verified = fld.status == Status.VERIFIED
                out["verified"] += verified
                if verified or all_fields:
                    digest, shown = _short(fld.value)
                    out["fields"].append([str(fld.name), json_safe(fld.offset),
                                          json_safe(fld.length),
                                          str(json_safe(fld.status)), digest, shown])
    except Exception as exc:  # malformed result; validate() already said why
        out["problems"].append(f"result cannot be walked: {_exc_text(exc)}")
    return out


def schema_problems(dec: Decoder, rel: str, data: bytes) -> list[str]:
    """Build the per-file output exactly as the pipeline does; return schema errors."""
    payload = isolate.process_data(rel, data, [dec])
    output = payload["output"]
    output["source"]["sha256"] = hashlib.sha256(data).hexdigest()
    return validate.errors("output", output, limit=3)


def round_trip(dec: Decoder, result: DecodeResult, data: bytes) -> dict[str, Any]:
    """C6: ``encode(result)`` compared with ``data`` (``result`` = decode(data))."""
    try:
        rebuilt = dec.encode(result)
    except (Exception, SystemExit) as exc:
        return {"error": _exc_where(exc)}
    if not isinstance(rebuilt, (bytes, bytearray)):
        return {"error": f"encode returned {type(rebuilt).__name__}, not bytes"}
    rebuilt = bytes(rebuilt)
    if rebuilt == data:
        return {"error": None, "diff": None}
    i = next((k for k in range(min(len(data), len(rebuilt))) if data[k] != rebuilt[k]),
             min(len(data), len(rebuilt)))
    return {"error": None, "diff": [i, data[i] if i < len(data) else None,
                                    rebuilt[i] if i < len(rebuilt) else None,
                                    len(data), len(rebuilt)]}


def _read(path: str) -> bytes | None:
    try:
        data = isolate.read_regular(path)
    except (OSError, ValueError):
        return None
    return data if len(data) <= MAX_FILE_BYTES else None


def _worker_main(conn: Any, job: dict[str, Any]) -> None:
    """Worker process: run every decoder-facing step, reporting each to the parent."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    except OSError:
        pass

    def step(kind: str, label: str, variant: str | None, fn: Callable[[], Any]) -> Any:
        conn.send(("start", (kind, label, variant)))
        payload = fn()
        conn.send(("done", payload))
        return payload

    try:
        try:
            dec = load_decoder(job["module"], job["name"])
        except (Exception, SystemExit) as exc:
            conn.send(("load_error", _exc_where(exc)))
            return
        can_encode = bool(dec.can_encode())
        conn.send(("hello", {"c1": metadata_problems(dec), "can_encode": can_encode}))

        # Probes (C2, C3) and claimed inputs.
        claimed: list[tuple[str, str]] = []
        for label, data in synthetic_inputs():
            step("probe", label, None, lambda: [_probe_once(dec, data), _probe_once(dec, data)])
        for label, path in job["corpus"]:
            data = _read(path)
            if data is None:
                conn.send(("unreadable", label))
                continue
            first, second = step("probe", label, None,
                                 lambda: [_probe_once(dec, data), _probe_once(dec, data)])
            score = first["value"] if first["error"] is None and first["value"] is not None else 0.0
            if min(1.0, max(0.0, score)) >= PROBE_THRESHOLD - _EPS:
                claimed.append((label, path))
        conn.send(("claimed", [label for label, _ in claimed]))

        def timed_probe() -> dict[str, Any]:
            big = random.Random("salvage-conformance/8m").randbytes(PROBE_SPEED_BYTES)
            start = time.perf_counter()
            res = _probe_once(dec, big)
            return {"seconds": time.perf_counter() - start, "error": res["error"]}
        step("probe-speed", "<8 MB random>", None, timed_probe)

        # Decodes (C4, C5, C6, C9).
        for label, path in claimed:
            data = _read(path)
            if data is None:
                conn.send(("unreadable", label))
                continue
            rel = label.rsplit("/", 1)[-1]
            kept: dict[str, Any] = {}
            clean = step("clean", label, None, lambda: decode_summary(dec, data, True, kept))
            step("clean-schema", label, None, lambda: schema_problems(dec, rel, data))
            if (can_encode and clean["error"] is None and not clean["problems"]
                    and not clean["empty"] and not clean["damage"] and not clean["lost"]):
                step("encode", label, None, lambda: round_trip(dec, kept["result"], data))
            for v in variants(data, job["name"], job["quick"]):
                step("variant", label, v.name, lambda: {
                    "summary": decode_summary(dec, v.data, False),
                    "schema": schema_problems(dec, rel, v.data),
                    "changed": v.changed})
        for label, data in synthetic_inputs():
            step("synthetic", label, None, lambda: {
                "summary": decode_summary(dec, data, False),
                "schema": schema_problems(dec, "synthetic.bin", data)})
        conn.send(("finished", None))

        # A2: the parent may ask to time a slow step again, in this same
        # (warm) process, once no other decoder is running.
        while True:
            try:
                cmd = conn.recv()
            except (EOFError, OSError):
                return
            if not (isinstance(cmd, tuple) and len(cmd) == 2 and cmd[0] == "remeasure"):
                return
            kind, label, path = cmd[1]
            if kind == "probe-speed":
                step("remeasure", label, None, timed_probe)
            else:
                data = _read(path) or b""
                step("remeasure", label, None, lambda: decode_summary(dec, data, False))
    finally:
        conn.close()


# -- parent side ----------------------------------------------------------------

class _Child:
    """One spawn-context worker process and the parent's end of its (duplex) pipe."""

    def __init__(self, target: Callable[..., None], *args: Any) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.conn, send = ctx.Pipe(duplex=True)
        self.proc = ctx.Process(target=target, args=(send, *args), daemon=True)
        try:
            self.proc.start()
        finally:
            send.close()   # a dead child then shows up as EOF, not a silent wait

    def recv(self, timeout: float) -> tuple[Any, ...]:
        """Next message, or ("timeout",), ("crash", exit code), ("bad", why)."""
        try:
            if not self.conn.poll(max(0.0, timeout)):
                return ("timeout",)
            msg = self.conn.recv()
        except (EOFError, OSError):
            self.proc.join(2)
            return ("crash", self.proc.exitcode)
        except Exception as exc:
            return ("bad", _exc_text(exc))
        return msg if isinstance(msg, tuple) and msg else ("bad", "malformed message")

    def send(self, message: Any) -> bool:
        """Send a command to the worker; False if it is gone."""
        try:
            self.conn.send(message)
            return True
        except (OSError, ValueError):
            return False

    def close(self) -> None:
        try:
            self.conn.close()   # a worker waiting for commands sees EOF and exits
        except Exception:
            pass
        try:
            if self.proc.pid is not None:
                self.proc.join(1)
                if self.proc.is_alive():
                    self.proc.terminate()
                    self.proc.join(2)
                if self.proc.is_alive():
                    self.proc.kill()
                    self.proc.join()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.proc.close()
        except Exception:
            pass


class _Gate:
    """Lets one thread time a step again while no other decoder is being checked (A2).

    Every decoder check holds a slot from :meth:`enter` to :meth:`leave`.
    :meth:`alone` gives up the caller's slot, waits until no slot is held
    and no other re-measure runs, and keeps new checks from starting until
    it is done. Checks that have not started yet do not count, so threads
    of a full pool waiting in :meth:`alone` cannot deadlock.
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._active = 0
        self._exclusive = False

    def enter(self) -> None:
        with self._cv:
            self._cv.wait_for(lambda: not self._exclusive)
            self._active += 1

    def leave(self) -> None:
        with self._cv:
            self._active -= 1
            self._cv.notify_all()

    @contextlib.contextmanager
    def alone(self) -> Iterator[None]:
        """Give up this thread's slot and run the body with nothing else running."""
        with self._cv:
            self._active -= 1
            self._cv.notify_all()
            self._cv.wait_for(lambda: self._active == 0 and not self._exclusive)
            self._exclusive = True
        try:
            yield
        finally:
            with self._cv:
                self._exclusive = False
                self._cv.notify_all()


def _discover_main(conn: Any, package: str) -> None:
    try:
        found = discover_decoders(package)
        conn.send(("discovered", {
            "decoders": [(str(d.name), type(d).__module__) for d in found.decoders],
            "errors": list(found.errors)}))
    finally:
        conn.close()


@dataclass
class _State:
    """What the parent knows about one decoder while its worker runs."""

    module_short: str
    owners: dict[str, list[str]]           # module short name -> decoder names
    corpus: dict[str, CorpusFile]
    hello: bool = False
    can_encode: bool = False
    claimed: list[str] | None = None
    baselines: dict[str, dict[str, Any]] = field(default_factory=dict)
    clean_ok: list[str] = field(default_factory=list)
    last_step: tuple[str, str, str | None] | None = None
    # Timings over a limit, to re-measure: (check id, label, kind, seconds).
    slow: list[tuple[str, str, str, float]] = field(default_factory=list)


def run_conformance(package: str = "salvage.formats", only: str | None = None,
                    cases_root: str | Path = "tests", samples_root: str | Path = "samples",
                    variant_timeout: float = 5.0, *, docs_root: str | Path = "docs",
                    jobs: int | None = None, quick: bool = False) -> list[DecoderReport]:
    """Check every decoder in ``package`` (or the one ``only`` names).

    ``only`` matches a decoder name or module name, case-insensitively.
    Relative roots are relative to the repository root. ``jobs`` decoders
    are checked at a time (default: up to 4). Reports are sorted by decoder
    name; discovery errors become reports of their own. Never raises for
    misbehaving decoders.

    ``quick`` (the merge gate in ``task.py test``): the corpus is the golden
    case inputs plus the synthetic inputs (``samples_root`` is not read),
    each claimed input gets fewer variants (see :func:`variants`), and C7
    runs on the first claimed input only. Every check still runs, with the
    same IDs and messages.
    """
    roots = (_resolve(cases_root), _resolve(samples_root), _resolve(docs_root))
    found, errors = _discover(package)
    files = corpus(roots[0], None if quick else roots[1])
    owners: dict[str, list[str]] = {}
    for name, module in found:
        owners.setdefault(module.rsplit(".", 1)[-1], []).append(name)

    def wanted(name: str, module: str) -> bool:
        if only is None:
            return True
        o = only.lower()
        return o in (name.lower(), module.lower(), module.rsplit(".", 1)[-1].lower())

    selected = [(n, m) for n, m in found if wanted(n, m)]
    workers = max(1, jobs if jobs is not None else min(4, os.cpu_count() or 1))
    gate = _Gate()
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        reports = list(pool.map(
            lambda nm: _check_decoder(nm[0], nm[1], package, files, owners, roots,
                                      variant_timeout, quick, gate), selected))

    by_module = {r.module: r for r in reports}
    for err in errors:
        module = err.split(":", 1)[0].strip()
        if not wanted("", module):
            continue
        rep = by_module.get(module)
        if rep is None:
            rep = DecoderReport(name="?", module=module)
            by_module[module] = rep
            reports.append(rep)
        rep.add("C1", FAIL, f"discovery error: {err}")
        rep.finish()
    return sorted(reports, key=lambda r: (r.name, r.module))


def _discover(package: str) -> tuple[list[tuple[str, str]], list[str]]:
    child = _Child(_discover_main, package)
    try:
        msg = child.recv(STARTUP_TIMEOUT)
    finally:
        child.close()
    if msg[0] == "discovered" and isinstance(msg[1], dict):
        return [tuple(x) for x in msg[1]["decoders"]], list(msg[1]["errors"])
    why = {"timeout": f"timed out after {STARTUP_TIMEOUT:g} s",
           "crash": f"crashed with exit code {msg[-1]}"}.get(msg[0], f"failed: {msg[-1]}")
    return [], [f"{package}: importing the decoder package {why}"]


def _check_decoder(name: str, module: str, package: str, files: list[CorpusFile],
                   owners: dict[str, list[str]], roots: tuple[Path, Path, Path],
                   variant_timeout: float, quick: bool, gate: _Gate) -> DecoderReport:
    rep = DecoderReport(name=name, module=module)
    start = time.monotonic()
    short = module.rsplit(".", 1)[-1]
    st = _State(short, owners, {f.label: f for f in files})
    child: _Child | None = None
    holding = True
    gate.enter()
    try:
        for problem in static_problems(module, package):
            rep.add("C8", FAIL, problem)
        _check_files(rep, short, roots)
        child = _Child(_worker_main, {"module": module, "name": name, "quick": quick,
                                      "corpus": [(f.label, f.path) for f in files]})
        finished = _run_worker(rep, st, child, variant_timeout)
        if st.claimed is not None:
            rep.inputs = len(st.claimed)
            if not st.claimed:
                rep.add("C10", FAIL, f"the probe claims none of the {len(files)} corpus files "
                                     f"(score >= {PROBE_THRESHOLD}); your own golden case "
                                     "inputs must be recognised by your probe")
        if st.clean_ok:
            _check_determinism(rep, st, name, module, variant_timeout, quick)
        if st.slow and finished:
            holding = False
            with gate.alone():
                _remeasure(rep, st, child, variant_timeout)
        else:
            _remeasure(rep, st, None, variant_timeout)   # worker gone: judge as measured
    except Exception as exc:  # noqa: BLE001 - the suite itself must never crash
        rep.add("C4", FAIL, f"conformance suite internal error: {_exc_where(exc)} "
                            "(not your decoder's fault; tell Core)")
    finally:
        if holding:
            gate.leave()
        if child is not None:
            child.close()
    rep.seconds = time.monotonic() - start
    rep.finish()
    return rep


def _check_files(rep: DecoderReport, short: str, roots: tuple[Path, Path, Path]) -> None:
    cases_root, _, docs_root = roots
    cases = cases_root / short / "cases"
    fix = (f"run `python tools/task.py golden-update {short}` and check every "
           ".expected.json by hand (docs/decoder-guide.md section 10)")
    if not cases.is_dir():
        rep.add("C10", FAIL, f"no golden cases: create {display(cases)}/ with at least one "
                             f"input file, then {fix}")
    else:
        names = {p.name for p in cases.iterdir() if p.is_file()}
        if not any(n + ".expected.json" in names for n in names
                   if not n.endswith(".expected.json")):
            rep.add("C10", FAIL, f"{display(cases)}/ has no input with an .expected.json; {fix}")
    spec = docs_root / "spec" / f"{short}.md"
    log = docs_root / "log" / f"{short}.md"
    if not spec.is_file():
        rep.add("C11", WARN, f"{display(spec)} is missing: write down what you know about "
                             "the format")
    if not log.is_file():
        rep.add("C11", WARN, f"{display(log)} is missing: keep a research log "
                             "(docs/decoder-guide.md section 11)")
    else:
        try:
            text = log.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            text = ""
            rep.add("C11", WARN, f"{display(log)} cannot be read: {_exc_text(exc)}")
        if text and not re.search(r"^### \d{4}-\d{2}-\d{2} \d{2}:\d{2} — \S", text, re.M):
            rep.add("C11", WARN, f"{display(log)} has no entry heading like "
                                 "'### 2026-10-15 14:30 — <title>'")


def _step_timeout(kind: str, variant_timeout: float) -> float:
    if kind in ("clean", "clean-schema"):
        return max(variant_timeout, 2 * DECODE_SPEED_LIMIT)
    return variant_timeout


def _run_worker(rep: DecoderReport, st: _State, child: _Child,
                variant_timeout: float) -> bool:
    """Judge the worker's steps; True if it finished them all (and now waits
    for re-measure commands). The caller closes ``child``."""
    timeout, step = STARTUP_TIMEOUT, None
    while True:
        msg = child.recv(timeout)
        tag = msg[0]
        if tag in ("timeout", "crash", "bad"):
            _worker_failed(rep, st, step, msg, timeout)
            return False
        if tag == "load_error":
            rep.add("C1", FAIL, f"the decoder cannot be loaded: {msg[1]}")
            return False
        if tag == "hello":
            st.hello = True
            st.can_encode = bool(msg[1]["can_encode"])
            for problem in msg[1]["c1"]:
                rep.add("C1", FAIL, problem)
        elif tag == "start":
            step = msg[1]
            timeout = _step_timeout(step[0], variant_timeout)
            continue
        elif tag == "done" and step is not None:
            _on_done(rep, st, step, msg[1])
            st.last_step, step = step, None
        elif tag == "claimed":
            st.claimed = list(msg[1])
        elif tag == "unreadable":
            rep.add("C2", WARN, "corpus file could not be read (or is over the size "
                                "limit); skipped", input=msg[1])
        elif tag == "finished":
            return True
        timeout = GAP_TIMEOUT


def _where(step: tuple[str, str, str | None] | None) -> str:
    if step is None:
        return "?"
    kind, label, variant = step
    if variant:
        return f"{variant} of {label}"
    return {"probe": f"probe of {label}", "probe-speed": "probe of 8 MB random bytes",
            "clean": f"clean decode of {label}", "clean-schema": f"pipeline output of {label}",
            "encode": f"encode() of {label}", "synthetic": f"synthetic input {label}"
            }.get(kind, f"{kind} {label}")


def _worker_failed(rep: DecoderReport, st: _State, step: tuple[str, str, str | None] | None,
                   msg: tuple[Any, ...], timeout: float) -> None:
    what = {"timeout": f"timed out (limit {timeout:g} s)",
            "crash": f"crashed the worker (exit code {msg[-1]})"}.get(
                msg[0], f"sent a bad message ({msg[-1]})")
    if not st.hello:
        rep.add("C1", FAIL, f"the decoder cannot be loaded: worker {what} while starting "
                            "(does importing the module hang or exit?)")
        return
    if step is None:
        rep.add("C4", FAIL, f"worker {what} between steps (after {_where(st.last_step)}); "
                            "remaining checks skipped")
        return
    kind, label, variant = step
    check = {"probe": "C2", "probe-speed": "C2", "encode": "C6"}.get(kind, "C4")
    on = variant or {"probe": "probe", "probe-speed": "probe of 8 MB random bytes",
                     "clean": "the clean decode", "clean-schema": "the pipeline run",
                     "encode": "encode()"}.get(kind, "decode")
    what = {"timeout": f"timed out on {on} (limit {timeout:g} s)",
            "crash": f"worker crashed on {on} (exit code {msg[-1]})"}.get(
                msg[0], f"bad message from worker on {on} ({msg[-1]})")
    rep.add(check, FAIL, f"{what}; remaining checks skipped",
            input=label if kind != "probe-speed" else None, variant=variant)
    if kind == "clean" and msg[0] == "timeout":
        rep.add("C9", FAIL, f"decode took over {timeout:g} s (limit {DECODE_SPEED_LIMIT:g} s)",
                input=label)


def _on_done(rep: DecoderReport, st: _State, step: tuple[str, str, str | None],
             payload: Any) -> None:
    kind, label, variant = step
    if kind == "probe":
        _judge_probe(rep, st, label, payload)
    elif kind == "probe-speed":
        if payload["error"] is None and payload["seconds"] > PROBE_SPEED_LIMIT:
            st.slow.append(("C2", label, kind, payload["seconds"]))   # judged by _remeasure
    elif kind == "clean":
        if _judge_decode(rep, payload, label, None):
            st.clean_ok.append(label)
            base: dict[tuple[str, int], dict[str, str]] = {}
            for name, offset, _length, _status, digest, shown in payload["fields"]:
                base.setdefault((name, offset), {})[digest] = shown
            st.baselines[label] = {"fields": base, "verified": payload["verified"]}
        if payload["seconds"] > DECODE_SPEED_LIMIT:
            st.slow.append(("C9", label, kind, payload["seconds"]))   # judged by _remeasure
    elif kind == "clean-schema":
        _judge_schema(rep, payload, label, None)
    elif kind == "encode":
        _judge_round_trip(rep, payload, label)
    elif kind == "variant":
        rep.variants += 1
        ok = _judge_decode(rep, payload["summary"], label, variant)
        _judge_schema(rep, payload["schema"], label, variant)
        if ok and label in st.baselines:
            _judge_honesty(rep, st.baselines[label], payload, label, variant)
    elif kind == "synthetic":
        _judge_decode(rep, payload["summary"], label, None)
        _judge_schema(rep, payload["schema"], label, None)


def _judge_probe(rep: DecoderReport, st: _State, label: str, payload: list[dict]) -> None:
    first, second = payload
    for res in (first, second):
        if res["error"] is not None:
            rep.add("C2", FAIL, f"probe raised {res['error']}", input=label)
            return
        if res["bad"] is not None:
            rep.add("C2", FAIL, f"probe {res['bad']}", input=label)
            return
    if first["value"] != second["value"]:
        rep.add("C2", FAIL, f"probe returned {first['value']!r}, then {second['value']!r} "
                            "on the same bytes", input=label)
    score = first["value"]
    if score < PROBE_THRESHOLD - _EPS:
        return
    if label.startswith("<"):
        rep.add("C3", FAIL, f"probe gives {score:g} to synthetic input {label} "
                            f"(must be < {PROBE_THRESHOLD})", input=label)
        return
    cf = st.corpus.get(label)
    if cf is not None and cf.owner is not None and cf.owner != st.module_short \
            and cf.owner in st.owners:
        rep.add("C3", FAIL, f"probe gives {score:g} to a golden case of "
                            f"{', '.join(st.owners[cf.owner])} (must be < {PROBE_THRESHOLD})",
                input=label)


def _judge_decode(rep: DecoderReport, summary: dict[str, Any], label: str,
                  variant: str | None) -> bool:
    """C4 on one decode; True if the result is usable for further checks."""
    if summary["error"] is not None:
        rep.add("C4", FAIL, f"decode raised {summary['error']}", input=label, variant=variant)
        return False
    for problem in summary["problems"]:
        rep.add("C4", FAIL, problem, input=label, variant=variant)
    return not summary["problems"]


def _judge_schema(rep: DecoderReport, problems: list[str], label: str,
                  variant: str | None) -> None:
    if problems:
        origin = validate.active("output").origin
        rep.add("C4", FAIL, f"the pipeline output fails the {origin} output schema: "
                            + "; ".join(problems), input=label, variant=variant)


def _judge_round_trip(rep: DecoderReport, payload: dict[str, Any], label: str) -> None:
    if payload["error"] is not None:
        rep.add("C6", FAIL, f"encode(decode(file)) raised {payload['error']}", input=label)
        return
    diff = payload["diff"]
    if diff is None:
        return
    i, want, got, n_want, n_got = diff

    def show(b: int | None) -> str:
        return "end of data" if b is None else f"0x{b:02x}"
    rep.add("C6", FAIL, f"encode(decode(file)) differs from the file at offset {i} "
                        f"(0x{i:x}): file has {show(want)}, encode gave {show(got)} "
                        f"(lengths {n_want} vs {n_got})", input=label)


def _judge_honesty(rep: DecoderReport, base: dict[str, Any], payload: dict[str, Any],
                   label: str, variant: str) -> None:
    summary, changed = payload["summary"], payload["changed"]
    for name, offset, length, _status, digest, shown in summary["fields"]:
        if any(offset < end and start < offset + length for start, end in changed):
            rep.add("C5", FAIL, f'field "{name}" @0x{offset:x} verified but bytes changed',
                    input=label, variant=variant)
            continue
        clean = base["fields"].get((name, offset))
        if clean is not None and digest not in clean:
            rep.add("C5", FAIL, f'field "{name}" @0x{offset:x} verified as {shown}, but the '
                                f"clean decode says {next(iter(clean.values()))}",
                    input=label, variant=variant)
    if summary["verified"] > base["verified"]:
        rep.add("C5", WARN, f"{summary['verified']} verified fields, more than the "
                            f"{base['verified']} of the clean decode", input=label,
                variant=variant)
    if (variant.startswith("truncate@") and summary["records"] and not summary["damage"]
            and not summary["lost"]):
        rep.add("C5", WARN, "truncation not reported: records returned, but no damage and "
                            "nothing lost", input=label, variant=variant)


# -- A2: timing re-measure (C2, C9) ------------------------------------------------

def _remeasure(rep: DecoderReport, st: _State, child: _Child | None,
               variant_timeout: float) -> None:
    """Judge each over-limit timing in ``st.slow``, timing it again first.

    The caller holds the gate alone, so no other decoder runs meanwhile.
    The re-measure runs in the same (warm) worker; with ``child`` None
    (the worker is gone) the first timing stands. FAIL only if the
    re-measure is also over the limit (the message shows both timings); a
    pass on the re-measure is a WARN that shows both.
    """
    for check, label, kind, first in st.slow:
        second, why = None, "the worker is gone"
        if child is not None:
            second, why = _time_again(child, kind, label, st, variant_timeout)
        limit = PROBE_SPEED_LIMIT if check == "C2" else DECODE_SPEED_LIMIT
        what = "probe on 8 MB of random bytes took {}" if check == "C2" else "decode took {}"
        hint = ": look at the header, do not scan the whole file" if check == "C2" else ""
        where = None if check == "C2" else label
        if second is None:
            rep.add(check, FAIL, what.format(f"{first:.2f} s") + f" (limit {limit:g} s; "
                                 f"could not re-measure: {why}){hint}", input=where)
        elif second > limit:
            rep.add(check, FAIL, what.format(f"{first:.2f} s, and {second:.2f} s when "
                                             "re-measured alone")
                    + f" (limit {limit:g} s){hint}", input=where)
        else:
            rep.add(check, WARN, what.format(f"{first:.2f} s at first, but {second:.2f} s "
                                             "when re-measured alone")
                    + f" (limit {limit:g} s); passed on the re-measure", input=where)


def _time_again(child: _Child, kind: str, label: str, st: _State,
                variant_timeout: float) -> tuple[float | None, str]:
    """``(seconds, "")`` for one re-measure in the worker, or ``(None, why)``."""
    cf = st.corpus.get(label)
    if not child.send(("remeasure", (kind, label, cf.path if cf else None))):
        return None, "the worker is gone"
    timeout = STARTUP_TIMEOUT if kind == "probe-speed" else GAP_TIMEOUT
    while True:
        msg = child.recv(timeout)
        if msg[0] == "start":
            timeout = _step_timeout(kind, variant_timeout)
            continue
        if msg[0] == "done" and isinstance(msg[1], dict):
            payload = msg[1]
            if payload.get("error") is not None:
                return None, f"it raised {payload['error']}"
            return float(payload["seconds"]), ""
        what = {"timeout": f"timed out (limit {timeout:g} s)",
                "crash": f"the worker crashed (exit code {msg[-1]})"}
        return None, what.get(msg[0], f"bad message from the worker ({msg[-1]})")


# -- C7: determinism ----------------------------------------------------------------

def _check_determinism(rep: DecoderReport, st: _State, name: str, module: str,
                       variant_timeout: float, quick: bool = False) -> None:
    labels = list(st.clean_ok[:1] if quick else st.clean_ok)
    job = json.dumps({"module": module, "name": name,
                      "paths": [st.corpus[lb].path for lb in labels]})
    limit = STARTUP_TIMEOUT + len(labels) * 2 * _step_timeout("clean", variant_timeout)

    def run(seed: str) -> tuple[str, Any]:
        env = dict(os.environ, PYTHONHASHSEED=seed)
        old = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + old if old else "")
        try:
            proc = subprocess.run([sys.executable, "-m", "tests.conformance", "--c7-child"],
                                  input=job.encode("utf-8"), capture_output=True,
                                  cwd=ROOT, env=env, timeout=limit)
        except subprocess.TimeoutExpired:
            return "error", f"timed out after {limit:g} s"
        try:
            return "ok", json.loads(proc.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["?"]
            return "error", f"exit code {proc.returncode}: {tail[0]}"

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        (s1, r1), (s2, r2) = pool.map(run, ("1", "2"))
    for seed, (status, res) in (("1", (s1, r1)), ("2", (s2, r2))):
        if status != "ok":
            rep.add("C7", FAIL, f"determinism check could not run (PYTHONHASHSEED={seed}): {res}")
            return
    for label, a, b in zip(labels, r1, r2):
        if a != b:
            rep.add("C7", FAIL, "to_dict() differs between PYTHONHASHSEED=1 and 2: "
                                + _first_diff(a, b), input=label)


def _first_diff(a: Any, b: Any, path: str = "") -> str:
    here = path or "<root>"
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if a.get(key, ...) != b.get(key, ...):
                return _first_diff(a.get(key), b.get(key), f"{path}.{key}" if path else key)
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, f"{path}[{i}]")
        if len(a) != len(b):
            return f"{here}: {len(a)} items vs {len(b)}"

    def show(v: Any) -> str:
        t = json.dumps(v, sort_keys=True, ensure_ascii=False)
        return t if len(t) <= 60 else t[:57] + "..."
    return f"{here}: seed 1 gave {show(a)}, seed 2 gave {show(b)}"


def _c7_child() -> int:
    """``--c7-child``: decode the files named on stdin, print the to_dict() list."""
    real = sys.stdout
    sys.stdout = io.StringIO()   # decoder prints must not corrupt the answer
    job = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    out: list[Any] = []
    try:
        dec = load_decoder(job["module"], job["name"])
    except (Exception, SystemExit) as exc:
        print(f"cannot load decoder: {_exc_text(exc)}", file=sys.stderr)
        return 1
    for path in job["paths"]:
        data = _read(path)
        try:
            out.append(dec.decode(SafeReader(data or b"")).to_dict())
        except (Exception, SystemExit) as exc:
            out.append({"error": _exc_text(exc)})
    real.write(json.dumps(out, sort_keys=True))
    real.flush()
    return 0


# -- runner -------------------------------------------------------------------------

def _finding_text(f: Finding) -> str:
    where = ""
    if f.variant and f.input:
        where = f" ({f.variant} of {f.input})"
    elif f.input:
        where = f" ({f.input})"
    return f"{f.check_id} {CHECKS.get(f.check_id, '?')}: {f.message}{where}"


def format_lines(reports: list[DecoderReport], verbose: bool = False) -> list[str]:
    """One line per decoder (the first FAIL finding for a failing one); with
    ``verbose`` every finding follows, indented."""
    width = max([len(r.name) for r in reports] + [4])
    lines: list[str] = []
    for r in reports:
        head = f"{r.verdict:<4}  {r.name:<{width}}  "
        fails = [f for f in r.findings if f.severity == FAIL]
        if fails and not verbose:
            lines.append(head + _finding_text(fails[0]))
            more = len(r.findings) - 1
            if more:
                lines.append(" " * (6 + width + 2) + f"(+{more} more findings; --verbose "
                                                     "lists them)")
        else:
            lines.append(head + f"{r.inputs} inputs, {r.variants} variants, "
                                f"{r.warnings} warnings")
        if verbose:
            for f in r.findings:
                lines.append(f"      {f.severity}  {_finding_text(f)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI: print one line per decoder; exit 1 if any FAILs (a dev tool)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--c7-child"]:
        return _c7_child()
    ap = argparse.ArgumentParser(prog="python tools/task.py conform",
                                 description="Decoder conformance suite (docs/conformance.md).")
    ap.add_argument("name", nargs="?", help="decoder name or module name (default: all)")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every finding")
    ap.add_argument("--package", default="salvage.formats")
    ap.add_argument("--cases-root", default=None, help="default: tests")
    ap.add_argument("--samples-root", default=None, help="default: samples")
    ap.add_argument("--docs-root", default=None, help="default: docs")
    ap.add_argument("--timeout", type=float, default=5.0, help="seconds per variant")
    ap.add_argument("--jobs", type=int, default=None, help="decoders checked at once")
    ap.add_argument("--quick", action="store_true",
                    help="the merge gate's mode: no samples/, fewer variants, C7 on one "
                         "input (default: full)")
    args = ap.parse_args(argv)

    def root(value: str | None, default: str) -> str | Path:
        return default if value is None else os.path.abspath(value)

    start = time.monotonic()
    reports = run_conformance(args.package, args.name, root(args.cases_root, "tests"),
                              root(args.samples_root, "samples"), args.timeout,
                              docs_root=root(args.docs_root, "docs"), jobs=args.jobs,
                              quick=args.quick)
    for line in format_lines(reports, args.verbose):
        print(line)
    if not reports:
        print(f"no decoder matches {args.name!r}" if args.name else "no decoders found")
    failed = sum(r.verdict == FAIL for r in reports)
    print(f"conform ({'quick' if args.quick else 'full'} mode): {len(reports) - failed} PASS, "
          f"{failed} FAIL in {time.monotonic() - start:.1f} s")
    return 1 if failed or (args.name and not reports) else 0


if __name__ == "__main__":
    from tests.conformance import main as _main   # spawn workers pickle tests.conformance.*
    sys.exit(_main())
