"""Decode each file in its own child process, so hangs and crashes stay contained.

The child (:func:`process_file`) does all the work and returns plain dicts.
The parent (:class:`Worker`, :func:`run_isolated`) only starts it, waits
with a timeout and cleans up; it never imports decoder modules itself.
:class:`Worker` never blocks, so the pipeline can drive several at once.
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.connection
import os
import signal
import stat
import time
from typing import Any, Callable, Iterable

from salvage.core import caps, emit, fallback, identify, limits, report
from salvage.core.coverage import coverage
from salvage.core.limits import MAX_FILE_BYTES
from salvage.core.model import DecodeResult
from salvage.core.plugin import Decoder, discover_decoders
from salvage.core.reader import SafeReader


def start_method() -> str:
    """"fork" where available (Linux), else "spawn" (Windows)."""
    return "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"


# -- child side ------------------------------------------------------------

MEMORY_OUTCOME = "error: memory limit"   # attempt outcome for a MemoryError
DISAPPEARED = "file disappeared"         # the input was deleted after the walk

# Address-space cap set in this process by cap_memory(), in bytes (None: no cap).
_memory_cap: int | None = None


def cap_memory(limit: int | None = None) -> int | None:
    """Cap this process's address space at ``limit`` (default MAX_WORKER_MEMORY).

    POSIX only (``resource.setrlimit(RLIMIT_AS)``); a lower existing hard
    limit is kept. Returns the cap now in force, or None where there is no
    ``resource`` module (Windows) or it cannot be set. Call it in a worker
    process only: the cap cannot be raised again.
    """
    global _memory_cap
    try:
        import resource
    except ImportError:
        return None
    want = limits.MAX_WORKER_MEMORY if limit is None else limit
    try:
        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY and 0 <= hard < want:
            want = hard
        resource.setrlimit(resource.RLIMIT_AS, (want, want))
    except (ValueError, OSError):
        return None
    _memory_cap = want
    return want


def memory_reason() -> str:
    """File-level error for a decode that ran out of memory."""
    if _memory_cap is not None:
        return f"memory limit ({_memory_cap // (1024 * 1024)} MiB)"
    return "out of memory (no memory cap in this process)"


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
    kept as a fallback), "invalid: <first 3 problems>",
    "error: <Type>: <msg>" and "error: memory limit" (a MemoryError; these
    three are never emitted). Returns
    ``(result, decoder, attempts)``; result is None if nothing was usable.
    """
    result, dec, attempts, _ = _try_candidates(candidates, data)
    return result, dec, attempts


def _try_candidates(candidates: list[Decoder], data: bytes
                    ) -> tuple[DecodeResult | None, Decoder | None, list[tuple[str, str]],
                               SafeReader | None]:
    """:func:`try_candidates` plus the SafeReader of the attempt that was kept."""
    attempts: list[tuple[str, str]] = []
    empty: tuple[DecodeResult, Decoder, SafeReader] | None = None
    for dec in candidates:
        name = str(getattr(dec, "name", ""))
        reader = SafeReader(data)
        try:
            result = dec.decode(reader)
        except MemoryError:
            attempts.append((name, MEMORY_OUTCOME))
            continue
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
                empty = (result, dec, reader)
            continue
        attempts.append((name, "ok"))
        return result, dec, attempts, reader
    if empty is not None:
        return empty[0], empty[1], attempts, empty[2]
    return None, None, attempts, None


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
    """``(format, probe score)`` of the chosen candidate.

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


def decoded_identity(name: str, result: DecodeResult) -> tuple[str | None, float]:
    """``(variant, confidence)`` for a decoded/partial file.

    ``variant`` is ``result.format`` when it is a non-empty string that
    differs from the decoder name ``name``, else None. ``confidence`` is
    ``result.confidence`` clamped to [0, 1] (0.0 if not a finite number).
    """
    fmt = result.format
    variant = fmt if isinstance(fmt, str) and fmt and fmt != name else None
    conf = result.confidence
    try:
        value = 0.0 if isinstance(conf, bool) else float(conf)
    except (TypeError, ValueError):
        value = 0.0
    if value != value:  # NaN
        value = 0.0
    return variant, min(1.0, max(0.0, value))


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
    try:
        try:
            data = read_regular(path)
        except FileNotFoundError:
            return failed_payload(rel, None, DISAPPEARED)
        except (OSError, ValueError) as exc:
            why = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            return failed_payload(rel, None, f"cannot read file: {why}")
        if len(data) > MAX_FILE_BYTES:
            return failed_payload(rel, None, f"too large (> {MAX_FILE_BYTES} bytes)")
        found = discover_decoders(package)
    except MemoryError:
        return failed_payload(rel, None, memory_reason())
    except BaseException as exc:  # noqa: BLE001 - the child reports everything as data
        return failed_payload(rel, None, f"internal error: {_exc_text(exc)}")
    return process_data(rel, data, found.decoders, found.errors, on_identified)


def process_data(rel: str, data: bytes, decoders: list[Decoder],
                 run_errors: Iterable[str] = (),
                 on_identified: Callable[[dict[str, Any]], None] | None = None
                 ) -> dict[str, Any]:
    """Identify and decode ``data`` with ``decoders``; return the payload.

    The worker-side core of :func:`process_file`, also usable in-process
    (tests, the decoder template): probing, candidate attempts, the
    record/member caps, coverage, and the output and entry dicts. Never
    raises.
    """
    errors_run = list(run_errors)
    info: dict[str, Any] | None = None
    try:
        choice = identify.choose(decoders, data, rel.rsplit("/", 1)[-1])
        info = identified_info(choice)
        if on_identified is not None:
            try:
                on_identified(info)
            except Exception:
                pass

        if not choice.candidates:
            result = fallback.unknown(data, choice.ranked)
            return _payload(rel, data, "unknown", result, info, [], [], errors_run,
                            cov=coverage(SafeReader(data)))

        result, dec, attempts, reader = _try_candidates(choice.candidates, data)
        if result is None or reader is None:
            why = (memory_reason() if any(o == MEMORY_OUTCOME for _, o in attempts)
                   else "no candidate decoder produced a valid result")
            return _payload(rel, data, "failed", None, info, attempts, [why], errors_run)
        capped = caps.enforce(result)
        status = "partial" if capped else report.file_status(result)
        return _payload(rel, data, status, result, info, attempts, [], errors_run,
                        used=str(getattr(dec, "name", "")), cov=coverage(reader))
    except BaseException as exc:  # noqa: BLE001 - the child reports everything as data
        why = (memory_reason() if isinstance(exc, MemoryError)
               else f"internal error: {_exc_text(exc)}")
        payload = failed_payload(rel, None, why, info)
        payload["run_errors"] = errors_run
        return payload


def _ranked(info: dict[str, Any] | None) -> list[identify.Ranked]:
    return [identify.Ranked(str(r.get("format")), float(r.get("score") or 0.0), r.get("error"))
            for r in (info or {}).get("ranked") or []]


def _payload(rel: str, data: bytes, status: str, result: DecodeResult | None,
             info: dict[str, Any], attempts: list[tuple[str, str]], errors: list[str],
             run_errors: list[str], used: str | None = None,
             cov: dict[str, Any] | None = None) -> dict[str, Any]:
    fmt, probe_score = identity(info, used)
    variant, confidence = None, probe_score
    if result is not None and used is not None and status in ("decoded", "partial"):
        variant, confidence = decoded_identity(fmt, result)
    res_dict = result.to_dict() if result is not None else None
    output = emit.to_output(rel=rel, size=len(data), sha256=None, fmt=fmt,
                            variant=variant, confidence=confidence, status=status,
                            result=res_dict, warnings=info["warnings"], errors=errors)
    entry = report.make_entry(rel=rel, size=len(data), status=status, fmt=fmt,
                              variant=variant, confidence=confidence,
                              probe_score=probe_score, candidates=_ranked(info),
                              attempts=attempts, result=result, coverage=cov,
                              warnings=output["warnings"], errors=errors)
    return {"output": output, "entry": entry, "run_errors": run_errors}


def failed_payload(rel: str, size: int | None, reason: str,
                   info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Payload for a file that could not be decoded at all.

    ``info`` is the :func:`identified_info` if identification finished: the
    file then keeps its format, confidence (= probe score), candidates and
    warnings. No records and ``coverage`` None.
    """
    size = size if size is not None else 0
    fmt, score = identity(info)
    warnings = list((info or {}).get("warnings") or [])
    output = emit.to_output(rel=rel, size=size, sha256=None, fmt=fmt,
                            confidence=score, status="failed",
                            warnings=warnings, errors=[reason])
    entry = report.make_entry(rel=rel, size=size, status="failed", fmt=fmt,
                              confidence=score, probe_score=score,
                              candidates=_ranked(info), warnings=warnings, errors=[reason])
    return {"output": output, "entry": entry, "run_errors": []}


def _child(conn: Any, path: str, rel: str, package: str) -> None:
    """Child entry point: silence stdio, restore default signal handling, cap
    memory, then send ("identified", info) right after probing and ("done",
    payload) at the end."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    except OSError:
        pass
    # A forked child inherits the parent's interrupt handlers: SIGTERM must
    # kill it again, and Ctrl-C (sent to the whole group) is the parent's job.
    for name, action in (("SIGTERM", signal.SIG_DFL), ("SIGINT", signal.SIG_IGN)):
        try:
            signal.signal(getattr(signal, name), action)
        except (AttributeError, ValueError, OSError):
            pass
    cap_memory()
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

EXIT_GRACE = 1.0   # seconds a worker that has answered gets to exit by itself
TERM_GRACE = 2.0   # seconds after SIGTERM (terminate) before SIGKILL (kill)


class Worker:
    """Parent-side handle of one file's worker process; never blocks.

    Drive it with :func:`drive` (or call :meth:`step` whenever one of
    :meth:`handles` is ready or :meth:`wake_at` has passed). One deadline
    of ``timeout`` seconds covers both messages: the child's ("identified",
    info) right after probing and ("done", payload). Once the outcome is
    known the child is reaped: a child that answered (or closed its pipe)
    gets EXIT_GRACE seconds to exit by itself; then, or at once on a
    timeout or a bad message, it is terminated (SIGTERM), and killed
    (SIGKILL) TERM_GRACE seconds later if it is still alive, e.g. because
    it ignores SIGTERM. No zombies, no orphans.
    """

    def __init__(self, path: str, rel: str, package: str, timeout: float,
                 method: str | None = None) -> None:
        ctx = multiprocessing.get_context(method or start_method())
        self.rel = rel
        self.timeout = timeout
        self.info: dict[str, Any] | None = None
        self.payload: Any = None
        self.reason: str | None = None
        self.done = False
        self._phase = "running"   # running -> exiting / terminating / killing -> done
        self._next = 0.0
        self._exitcode: int | None = None
        self._conn, send_conn = ctx.Pipe(duplex=False)
        self.proc = ctx.Process(target=_child, args=(send_conn, path, rel, package),
                                daemon=True)
        try:
            self.proc.start()
        except BaseException:
            send_conn.close()
            self._conn.close()
            raise
        send_conn.close()  # so a dead child shows up as EOF, not a silent wait
        self.deadline = time.monotonic() + timeout

    def handles(self) -> list[Any]:
        """What to wait on: the pipe while running, then the process sentinel."""
        if self.done:
            return []
        return [self._conn] if self._phase == "running" else [self.proc.sentinel]

    def wake_at(self) -> float:
        """Monotonic time at which :meth:`step` must run even if nothing is ready."""
        if self.done:
            return float("inf")
        return self.deadline if self._phase == "running" else self._next

    def step(self, now: float | None = None) -> bool:
        """Receive what is ready, enforce the deadline, reap; True once finished."""
        now = time.monotonic() if now is None else now
        if self._phase == "running":
            self._receive(now)
        if self._phase != "running" and not self.done:
            self._reap(now)
        return self.done

    def kill(self) -> None:
        """Stop at once (an interrupted run): terminate now, kill after TERM_GRACE."""
        now = time.monotonic()
        if self._phase == "running":
            self.reason = self.reason or "interrupted"
            self._close_conn()
            self._escalate("terminating", now)
        elif self._phase == "exiting":
            self._escalate("terminating", now)

    def result(self) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
        """``(payload, None, info)`` or ``(None, reason, info)``; see :func:`run_isolated`."""
        reason = self.reason
        if reason == "crash":
            reason = f"worker crashed with exit code {self._exitcode} ({_stage(self.info)})"
        if reason is None and not (isinstance(self.payload, dict)
                                   and isinstance(self.payload.get("output"), dict)
                                   and isinstance(self.payload.get("entry"), dict)):
            reason = f"bad payload from worker ({_stage(self.info)})"
        return (None, reason, self.info) if reason else (self.payload, None, self.info)

    # -- internals --

    def _receive(self, now: float) -> None:
        # Messages are received BEFORE reaping: a large payload would
        # otherwise fill the pipe and deadlock.
        while self.payload is None and self.reason is None:
            stage = _stage(self.info)
            try:
                if not self._conn.poll(0):
                    if time.monotonic() >= self.deadline:
                        self.reason = f"timeout after {_secs(self.timeout)}s ({stage})"
                    break
                message = self._conn.recv()
            except (EOFError, OSError):
                self.reason = "crash"
                break
            except Exception as exc:  # unpickling a corrupt message
                self.reason = f"bad payload from worker: {_exc_text(exc)} ({stage})"
                break
            if not (isinstance(message, tuple) and len(message) == 2):
                self.reason = f"bad message from worker ({stage})"
            elif message[0] == "identified" and self.info is None \
                    and isinstance(message[1], dict):
                self.info = message[1]
            elif message[0] == "done":
                self.payload = message[1]
            else:
                self.reason = f"bad message from worker ({stage})"
        if self.payload is None and self.reason is None:
            return
        self._close_conn()
        if self.payload is not None or self.reason == "crash":
            self._escalate("exiting", now)      # finishing (or gone) by itself
        else:
            self._escalate("terminating", now)  # timeout or a bad message: stop it now

    def _escalate(self, phase: str, now: float) -> None:
        self._phase = phase
        self._next = now + (EXIT_GRACE if phase == "exiting" else TERM_GRACE)
        try:
            if phase == "terminating":
                self.proc.terminate()
            elif phase == "killing":
                self.proc.kill()
        except Exception:  # pragma: no cover - defensive (already gone)
            pass

    def _reap(self, now: float) -> None:
        try:
            alive = self.proc.is_alive()
        except Exception:  # pragma: no cover - defensive
            alive = False
        if not alive:
            self._finish()
        elif now >= self._next:
            if self._phase == "exiting":
                self._escalate("terminating", now)
            elif self._phase == "terminating":
                self._escalate("killing", now)
            else:  # pragma: no cover - SIGKILL cannot be ignored; keep waiting
                self._next = now + TERM_GRACE

    def _finish(self) -> None:
        try:
            self.proc.join(0)
            self._exitcode = self.proc.exitcode
            self.proc.close()
        except Exception:  # pragma: no cover - defensive
            pass
        self.done = True
        self._phase = "done"

    def _close_conn(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - defensive
            pass


def drive(workers: list[Worker], max_wait: float | None = None) -> None:
    """Wait until one of ``workers`` needs attention (at most ``max_wait`` s), then step each.

    Never waits past the earliest :meth:`Worker.wake_at`.
    """
    live = [w for w in workers if not w.done]
    if not live:
        return
    wait = max(0.0, min(w.wake_at() for w in live) - time.monotonic())
    if max_wait is not None:
        wait = min(wait, max_wait)
    handles = [h for w in live for h in w.handles()]
    try:
        multiprocessing.connection.wait(handles, wait)
    except (OSError, ValueError):  # pragma: no cover - a handle closed under us
        pass
    now = time.monotonic()
    for w in live:
        w.step(now)


def run_isolated(path: str, rel: str, package: str, timeout: float,
                 method: str | None = None
                 ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    """Run :func:`process_file` in a child process and wait for it.

    Returns ``(payload, None, info)`` on success or ``(None, reason, info)``
    on timeout, crash or a bad message. ``info`` is the child's
    "identified" message (None if it never arrived), so a later failure
    still knows the identification. ``reason`` names the stage reached
    ("(during probe)" before the "identified" message, "(during decode)"
    after it). The child is reaped before this returns (see :class:`Worker`).
    """
    worker = Worker(path, rel, package, timeout, method)
    try:
        while not worker.done:
            drive([worker])
    finally:
        if not worker.done:  # only after an exception above
            worker.kill()
            while not worker.done:
                drive([worker])
    return worker.result()


def _stage(info: dict[str, Any] | None) -> str:
    return "during probe" if info is None else "during decode"


def _secs(timeout: float) -> str:
    return str(int(timeout)) if float(timeout).is_integer() else str(timeout)


def _exc_text(exc: BaseException) -> str:
    try:
        message = str(exc)
    except Exception:
        message = "<unprintable message>"
    return f"{type(exc).__name__}: {message}"
