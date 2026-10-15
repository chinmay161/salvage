"""Decode each file in its own child process, so hangs and crashes stay contained.

The child (:func:`process_file`) does all the work and returns plain dicts.
The parent (:func:`run_isolated`) only starts it, waits with a timeout and
cleans up; it never imports decoder modules itself.
"""

from __future__ import annotations

import multiprocessing
import os
import stat
import time
from typing import Any, Callable

from salvage.core import emit, fallback, identify, report
from salvage.core.limits import MAX_FILE_BYTES
from salvage.core.model import DecodeResult
from salvage.core.plugin import Decoder, discover_decoders
from salvage.core.reader import SafeReader


def start_method() -> str:
    """"fork" where available (Linux), else "spawn" (Windows)."""
    return "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"


# -- child side ------------------------------------------------------------

def read_regular(path: str, limit: int = MAX_FILE_BYTES) -> bytes:
    """Read at most ``limit + 1`` bytes of a regular file.

    Opened non-blocking and checked with fstat, so a file swapped for a
    FIFO or device after the walk is refused instead of blocking.
    Raises OSError (or ValueError for a non-regular file).
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular file")
        chunks = []
        left = limit + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def try_candidates(candidates: list[Decoder], data: bytes
                   ) -> tuple[DecodeResult | None, Decoder | None, list[tuple[str, str]]]:
    """Decode with each candidate in order until one gives a usable result.

    Outcomes: "ok" (stop), "empty" (no records and no members; the first is
    kept as a fallback), "invalid: <first 3 problems>" and
    "error: <Type>: <msg>" (both never emitted). Returns
    ``(result, decoder, attempts)``; result is None if nothing was usable.
    """
    attempts: list[tuple[str, str]] = []
    empty: tuple[DecodeResult, Decoder] | None = None
    for dec in candidates:
        name = str(getattr(dec, "name", ""))
        try:
            result = dec.decode(SafeReader(data))
        except (Exception, SystemExit) as exc:
            attempts.append((name, f"error: {_exc_text(exc)}"))
            continue
        if not isinstance(result, DecodeResult):
            attempts.append((name, f"invalid: decode returned {type(result).__name__}, "
                                   "not a DecodeResult"))
            continue
        problems = result.validate(len(data))
        if problems:
            attempts.append((name, "invalid: " + "; ".join(problems[:3])))
            continue
        if not result.records and not result.members:
            attempts.append((name, "empty"))
            if empty is None:
                empty = (result, dec)
            continue
        attempts.append((name, "ok"))
        return result, dec, attempts
    if empty is not None:
        return empty[0], empty[1], attempts
    return None, None, attempts


def identified_info(choice: identify.Choice) -> dict[str, Any]:
    """Plain-dict summary of an identification, as sent in the "identified" message.

    ``{"ranked": [{"format", "score", "error"}], "candidates": [names in try
    order], "warnings": [...]}``.
    """
    return {
        "ranked": [{"format": r.format, "score": r.score, "error": r.error}
                   for r in choice.ranked],
        "candidates": [str(getattr(d, "name", "")) for d in choice.candidates],
        "warnings": list(choice.warnings),
    }


def identity(info: dict[str, Any] | None, used: str | None = None) -> tuple[str, float]:
    """``(format, confidence)`` for an output: the chosen candidate and its probe score.

    The chosen candidate is ``used`` (the decoder whose result is emitted)
    or else the first candidate in try order. No candidate (or no
    identification at all) gives ``("unknown", 0.0)``.
    """
    if not info or not info.get("candidates"):
        return "unknown", 0.0
    name = used if used is not None else info["candidates"][0]
    for r in info.get("ranked") or []:
        if r.get("format") == name:
            return name, float(r.get("score") or 0.0)
    return name, 0.0


def process_file(path: str, rel: str, package: str = "salvage.formats",
                 on_identified: Callable[[dict[str, Any]], None] | None = None
                 ) -> dict[str, Any]:
    """Read, identify and decode one file; return a plain-dict payload.

    Payload: ``{"output": <per-file output>, "entry": <report entry>,
    "run_errors": [decoder discovery errors]}``. ``sha256`` and the
    entry's ``output`` are left None for the parent to fill in.
    ``on_identified`` is called with :func:`identified_info` right after
    probing, before any decode starts. Never raises (everything is
    reported as data).
    """
    run_errors: list[str] = []
    info: dict[str, Any] | None = None
    try:
        try:
            data = read_regular(path)
        except (OSError, ValueError) as exc:
            why = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            return failed_payload(rel, None, f"cannot read file: {why}")
        if len(data) > MAX_FILE_BYTES:
            return failed_payload(rel, None, f"too large (> {MAX_FILE_BYTES} bytes)")

        found = discover_decoders(package)
        run_errors = list(found.errors)
        choice = identify.choose(found.decoders, data, rel.rsplit("/", 1)[-1])
        info = identified_info(choice)
        if on_identified is not None:
            try:
                on_identified(info)
            except Exception:
                pass

        if not choice.candidates:
            result = fallback.unknown(data, choice.ranked)
            return _payload(rel, data, "unknown", result, info, [], [], run_errors)

        result, dec, attempts = try_candidates(choice.candidates, data)
        if result is None:
            return _payload(rel, data, "failed", None, info, attempts,
                            ["no candidate decoder produced a valid result"], run_errors)
        return _payload(rel, data, report.file_status(result), result, info, attempts,
                        [], run_errors, used=str(getattr(dec, "name", "")))
    except BaseException as exc:  # noqa: BLE001 - the child reports everything as data
        payload = failed_payload(rel, None, f"internal error: {_exc_text(exc)}", info)
        payload["run_errors"] = run_errors
        return payload


def _ranked(info: dict[str, Any] | None) -> list[identify.Ranked]:
    return [identify.Ranked(str(r.get("format")), float(r.get("score") or 0.0), r.get("error"))
            for r in (info or {}).get("ranked") or []]


def _payload(rel: str, data: bytes, status: str, result: DecodeResult | None,
             info: dict[str, Any], attempts: list[tuple[str, str]], errors: list[str],
             run_errors: list[str], used: str | None = None) -> dict[str, Any]:
    fmt, confidence = identity(info, used)
    res_dict = result.to_dict() if result is not None else None
    output = emit.to_output(rel=rel, size=len(data), sha256=None, fmt=fmt,
                            confidence=confidence, status=status, result=res_dict,
                            warnings=info["warnings"], errors=errors)
    entry = report.make_entry(rel=rel, size=len(data), status=status, fmt=fmt,
                              confidence=confidence, candidates=_ranked(info),
                              attempts=attempts, result=result,
                              warnings=output["warnings"], errors=errors)
    return {"output": output, "entry": entry, "run_errors": run_errors}


def failed_payload(rel: str, size: int | None, reason: str,
                   info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Payload for a file that could not be decoded at all.

    ``info`` is the :func:`identified_info` if identification finished: the
    file then keeps its format, confidence, candidates and warnings.
    """
    size = size if size is not None else 0
    fmt, confidence = identity(info)
    warnings = list((info or {}).get("warnings") or [])
    output = emit.to_output(rel=rel, size=size, sha256=None, fmt=fmt,
                            confidence=confidence, status="failed",
                            warnings=warnings, errors=[reason])
    entry = report.make_entry(rel=rel, size=size, status="failed", fmt=fmt,
                              confidence=confidence, candidates=_ranked(info),
                              warnings=warnings, errors=[reason])
    return {"output": output, "entry": entry, "run_errors": []}


def _child(conn: Any, path: str, rel: str, package: str) -> None:
    """Child entry point: silence stdio, then send ("identified", info) right
    after probing and ("done", payload) at the end."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    except OSError:
        pass
    sent: dict[str, Any] = {}

    def identified(info: dict[str, Any]) -> None:
        conn.send(("identified", info))
        sent["info"] = info

    try:
        payload = process_file(path, rel, package, on_identified=identified)
        try:
            conn.send(("done", payload))
        except BaseException as exc:  # noqa: BLE001
            conn.send(("done", failed_payload(rel, None, f"cannot send result: {_exc_text(exc)}",
                                              sent.get("info"))))
    finally:
        conn.close()


# -- parent side -----------------------------------------------------------

def run_isolated(path: str, rel: str, package: str, timeout: float,
                 method: str | None = None
                 ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    """Run :func:`process_file` in a child process.

    Returns ``(payload, None, info)`` on success or ``(None, reason, info)``
    on timeout, crash or a bad message. ``info`` is the child's
    "identified" message (None if it never arrived), so a later failure
    still knows the identification. One deadline of ``timeout`` seconds
    covers both messages; ``reason`` names the stage reached ("(during
    probe)" before the "identified" message, "(during decode)" after it).
    Messages are received BEFORE joining (a large payload would otherwise
    fill the pipe and deadlock). Afterwards the child is joined, then
    terminated, then killed: no zombies, no orphans.
    """
    ctx = multiprocessing.get_context(method or start_method())
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(send_conn, path, rel, package), daemon=True)
    payload: Any = None
    info: dict[str, Any] | None = None
    reason: str | None = None
    deadline = time.monotonic() + timeout
    try:
        proc.start()
        send_conn.close()  # so a dead child shows up as EOF, not a silent wait
        while payload is None and reason is None:
            stage = _stage(info)
            try:
                if not recv_conn.poll(max(0.0, deadline - time.monotonic())):
                    reason = f"timeout after {_secs(timeout)}s ({stage})"
                    break
                message = recv_conn.recv()
            except (EOFError, OSError):
                reason = "crash"
                break
            except Exception as exc:  # unpickling a corrupt message
                reason = f"bad payload from worker: {_exc_text(exc)} ({stage})"
                break
            if not (isinstance(message, tuple) and len(message) == 2):
                reason = f"bad message from worker ({stage})"
            elif message[0] == "identified" and info is None and isinstance(message[1], dict):
                info = message[1]
            elif message[0] == "done":
                payload = message[1]
            else:
                reason = f"bad message from worker ({stage})"
    finally:
        _reap(proc)
        recv_conn.close()
    if reason == "crash":
        reason = f"worker crashed with exit code {proc.exitcode} ({_stage(info)})"
    try:
        proc.close()
    except ValueError:
        pass
    if reason is None and not (isinstance(payload, dict)
                               and isinstance(payload.get("output"), dict)
                               and isinstance(payload.get("entry"), dict)):
        reason = f"bad payload from worker ({_stage(info)})"
    return (None, reason, info) if reason else (payload, None, info)


def _stage(info: dict[str, Any] | None) -> str:
    return "during probe" if info is None else "during decode"


def _reap(proc: Any) -> None:
    try:
        if proc.pid is None:
            return
        proc.join(1)
        if proc.is_alive():
            proc.terminate()
            proc.join(2)
        if proc.is_alive():
            proc.kill()
            proc.join()
    except Exception:  # pragma: no cover - defensive
        pass


def _secs(timeout: float) -> str:
    return str(int(timeout)) if float(timeout).is_integer() else str(timeout)


def _exc_text(exc: BaseException) -> str:
    try:
        message = str(exc)
    except Exception:
        message = "<unprintable message>"
    return f"{type(exc).__name__}: {message}"
