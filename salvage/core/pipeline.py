"""End-to-end run: walk, decode each file in isolation, write outputs and report.json."""

from __future__ import annotations

import collections
import hashlib
import os
import signal
import stat
import sys
import threading
from typing import Any, Callable

from salvage.core import emit, isolate, report, validate, walk
from salvage.core.limits import MAX_FILE_BYTES, MAX_SECONDS_PER_FILE

Progress = Callable[[dict[str, Any]], None]

POLL = 0.2  # seconds between interrupt checks while workers run


def default_jobs() -> int:
    """Workers run at once by default: ``min(os.cpu_count() or 1, 4)``."""
    return max(1, min(os.cpu_count() or 1, 4))


def run(input_dir: str, output_dir: str, *, decoder_package: str = "salvage.formats",
        timeout: float = MAX_SECONDS_PER_FILE, progress: Progress | None = None,
        jobs: int = 1, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """Process every regular file under ``input_dir``; return the report dict.

    Writes one JSON per input plus ``report.json`` (written last, also when
    the run fails midway) into ``output_dir``. Problems are recorded in the
    report, never raised. ``progress`` is called with each finished report
    entry, in completion order. Never overwrites an input file, and never
    deletes anything in ``output_dir``.

    ``jobs`` isolated workers run at once (1 = one file at a time). The
    parent is the only process that writes files, and report entries stay
    in walk order, so the output is byte-identical for every ``jobs``.

    SIGINT and SIGTERM (Ctrl-C, ``docker stop``) are handled while this
    runs (main thread only): no new file is started, running workers are
    killed, and report.json is written with the files finished so far plus
    the run-level error "interrupted: N files not processed". Files not
    finished get no output. ``stats`` (if given) receives ``jobs``,
    ``peak_workers`` and ``files``.

    On Windows workers are started with "spawn", which re-imports the
    calling script: scripts that call run() need an
    ``if __name__ == "__main__":`` guard (``python -m salvage.cli`` has one).
    """
    jobs = max(1, int(jobs))
    rep = report.new_report()
    out_ok = _prepare_output(output_dir, rep)
    protected: set[str] = set()
    interrupt = _Interrupt()
    peak = 0
    try:
        interrupt.install()
        if not out_ok:
            return rep
        existing = _count_files(output_dir)
        if existing:
            rep["warnings"].append(f"output dir was not empty: {existing} existing files")
        if not os.path.isdir(input_dir):
            rep["errors"].append("input directory does not exist or is not a directory")
            return rep
        try:
            os.listdir(input_dir)
        except OSError as exc:
            rep["errors"].append(f"input directory is not readable: {_strerror(exc)}")
            return rep

        inputs, skipped = walk.list_inputs(input_dir, output_dir)
        rep["skipped"] = [{"input": emit.display_path(s.rel), "reason": s.reason}
                          for s in skipped]
        root = os.path.abspath(input_dir)
        protected = {_key(i.path) for i in inputs}
        protected |= {_key(os.path.join(root, *s.rel.split("/"))) for s in skipped}
        names = emit.output_names(i.rel for i in inputs)
        run_errors: list[str] = list(validate.load_problems())
        entries: list[dict[str, Any] | None] = [None] * len(inputs)

        def finish(i: int, output: dict[str, Any], entry: dict[str, Any],
                   errs: list[str]) -> None:
            item = inputs[i]
            entries[i] = entry
            try:
                output, bug = checked_output(item.rel, output, entry)
            except Exception as exc:  # noqa: BLE001 - pragma: no cover - defensive
                bug = f"internal error: validating {item.rel}: {type(exc).__name__}: {exc}"
            if bug:
                errs = [*errs, bug]
            for err in errs:
                if err not in run_errors:
                    run_errors.append(err)
            out_rel = names[item.rel]
            entry["output"] = emit.display_path(out_rel)
            target = os.path.join(output_dir, *out_rel.split("/"))
            try:
                if _key(target) in protected:
                    raise OSError(0, "refusing to overwrite an input file")
                if os.path.isdir(target):
                    raise OSError(0, "output path is an existing folder")
                emit.write_json(target, output)
            except (OSError, ValueError, TypeError) as exc:
                entry["errors"].append(f"cannot write output: {_strerror(exc)}")
                entry["output"] = None
            if progress is not None:
                try:
                    progress(entry)
                except Exception:
                    pass

        pending = collections.deque(range(len(inputs)))
        running: dict[int, tuple[isolate.Worker, str | None]] = {}
        try:
            while running or (pending and not interrupt.flag):
                if interrupt.flag:
                    for worker, _ in running.values():
                        worker.kill()
                while pending and len(running) < jobs and not interrupt.flag:
                    i = pending.popleft()
                    try:
                        worker, sha, ready = _start(inputs[i], decoder_package, timeout)
                    except Exception as exc:  # noqa: BLE001 - one file never stops the run
                        worker, sha, ready = None, None, _internal_error(inputs[i], exc)
                    if ready is not None:
                        finish(i, *ready)
                    else:
                        running[i] = (worker, sha)
                        peak = max(peak, len(running))
                if not running:
                    continue
                isolate.drive([w for w, _ in running.values()], max_wait=POLL)
                for i in sorted(running):
                    worker, sha = running[i]
                    if not worker.done:
                        continue
                    del running[i]
                    if worker.reason == "interrupted":
                        continue  # killed by the interrupt: not done, no output
                    try:
                        result = _collect(inputs[i], worker, sha)
                    except Exception as exc:  # noqa: BLE001 - one file never stops the run
                        result = _internal_error(inputs[i], exc)
                    finish(i, *result)
        finally:
            for worker, _ in running.values():  # only after an internal error
                worker.kill()
            while running:
                isolate.drive([w for w, _ in running.values()])
                running = {i: r for i, r in running.items() if not r[0].done}

        rep["files"] = [e for e in entries if e is not None]
        rep["errors"].extend(sorted(run_errors))
        missing = len(inputs) - len(rep["files"])
        if interrupt.flag and missing:
            rep["errors"].append(f"interrupted: {missing} files not processed")
    except Exception as exc:  # noqa: BLE001 - report it, keep the report
        rep["errors"].append(f"internal error: {type(exc).__name__}: {exc}")
    finally:
        report.summarize(rep)
        _check_report(rep)
        if out_ok:
            target = os.path.join(output_dir, emit.REPORT_NAME)
            try:
                if _key(target) in protected:
                    raise OSError(0, "refusing to overwrite an input file")
                emit.write_json(target, rep)
            except (OSError, ValueError, TypeError) as exc:
                rep["errors"].append(f"cannot write report: {_strerror(exc)}")
        interrupt.restore()
        if stats is not None:
            stats.update({"jobs": jobs, "peak_workers": peak, "files": len(rep["files"])})
    return rep


Done = tuple[dict[str, Any], dict[str, Any], list[str]]   # (output, entry, run errors)


def _start(item: walk.InputFile, package: str, timeout: float
           ) -> tuple[Any, str | None, Done | None]:
    """Start one file: ``(worker, sha256, None)``, or ``(None, None, result)``
    when no worker is needed.

    A file over MAX_FILE_BYTES is failed without being read (no sha256); a
    file deleted since the walk is failed as "file disappeared".
    """
    if item.size > MAX_FILE_BYTES:
        return None, None, _unpack(isolate.failed_payload(
            item.rel, item.size, f"too large ({item.size} bytes > {MAX_FILE_BYTES})"), None)
    sha = sha256_file(item.path)
    if sha is None and not os.path.lexists(item.path):
        return None, None, _unpack(isolate.failed_payload(item.rel, None, isolate.DISAPPEARED),
                                   None)
    return isolate.Worker(item.path, item.rel, package, timeout), sha, None


def _collect(item: walk.InputFile, worker: isolate.Worker, sha: str | None) -> Done:
    """The finished worker's result as ``(output, entry, run errors)``."""
    payload, reason, info = worker.result()
    if payload is None:
        # Keep what the child identified before it timed out or crashed.
        payload = isolate.failed_payload(item.rel, item.size, reason or "worker failed", info)
    return _unpack(payload, sha)


def _unpack(payload: dict[str, Any], sha: str | None) -> Done:
    output, entry = payload["output"], payload["entry"]
    output["source"]["sha256"] = sha
    entry["sha256"] = sha
    return output, entry, [str(e) for e in payload.get("run_errors") or []]


def _internal_error(item: walk.InputFile, exc: Exception) -> Done:
    payload = isolate.failed_payload(
        item.rel, item.size, f"internal error: {type(exc).__name__}: {exc}")
    return payload["output"], payload["entry"], []


class _Interrupt:
    """Turns SIGINT/SIGTERM into a flag while a run is in progress (main thread only)."""

    NAMES = ("SIGINT", "SIGTERM")

    def __init__(self) -> None:
        self.flag = False
        self._old: dict[int, Any] = {}

    def _handler(self, signum: int, frame: Any) -> None:
        self.flag = True

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for name in self.NAMES:
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                old = signal.getsignal(sig)
                signal.signal(sig, self._handler)
            except (ValueError, OSError):
                continue
            self._old[sig] = signal.SIG_DFL if old is None else old

    def restore(self) -> None:
        for sig, old in self._old.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass
        self._old.clear()


def _count_files(folder: str) -> int:
    """Number of files (anything not a folder) under ``folder``; never raises."""
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(folder):
        n += len(filenames)
    return n


REPLACED_SHOWN = 10  # validation errors listed in a replacement output


def checked_output(rel: str, output: dict[str, Any], entry: dict[str, Any]
                   ) -> tuple[dict[str, Any], str | None]:
    """Validate a per-file output against the active output schema.

    Valid: ``(output, None)``. Invalid: returns a minimal "failed"
    replacement (same format/variant/confidence, no records) whose errors
    list the first 10 validation errors, and updates ``entry`` in place to
    match it. If even the replacement is invalid that is a bug: it is still
    returned, with a run-level error as the second value.
    """
    problems = validate.errors("output", output)
    if not problems:
        return output, None
    errors = [f"decoder output failed schema validation ({len(problems)}"
              f"{'+' if len(problems) >= 50 else ''} errors); replaced by this failed "
              f"output. First {min(len(problems), REPLACED_SHOWN)}:"]
    errors += problems[:REPLACED_SHOWN]
    fmt = output.get("format")
    fmt = fmt if isinstance(fmt, str) and fmt else "unknown"
    variant = output.get("variant")
    variant = variant if isinstance(variant, str) and variant else None
    conf = output.get("confidence")
    conf = float(conf) if (isinstance(conf, (int, float)) and not isinstance(conf, bool)
                           and 0.0 <= conf <= 1.0) else 0.0
    size = entry.get("size")
    size = size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else 0
    sha = entry.get("sha256") if isinstance(entry.get("sha256"), str) else None
    replacement = emit.to_output(rel=rel, size=size, sha256=sha, fmt=fmt, variant=variant,
                                 confidence=conf, status="failed", errors=errors)
    zero = dict.fromkeys(report.TRUST, 0)
    entry.update({"status": "failed", "format": fmt, "variant": variant, "confidence": conf,
                  "records_by_status": dict(zero), "fields_by_status": dict(zero),
                  "members": 0, "damage": [], "coverage": None, "warnings": [],
                  "errors": [str(e) for e in entry.get("errors") or []
                             if isinstance(e, str)] + errors})
    still = validate.errors("output", replacement)
    if still:
        return replacement, (f"internal error: the failed replacement output for "
                             f"{emit.display_path(rel)} is itself invalid: {still[0]}")
    return replacement, None


def _check_report(rep: dict[str, Any]) -> None:
    """Validate report.json; on failure add a run-level error and tell stderr.

    The report is written either way (it must always exist).
    """
    try:
        problems = validate.errors("report", rep)
    except Exception as exc:  # pragma: no cover - defensive
        problems = [f"$: validation failed: {type(exc).__name__}"]
    if not problems:
        return
    message = (f"report.json fails schema validation ({len(problems)} errors); first: "
               + "; ".join(problems[:3]))
    rep["errors"].append(message)
    try:
        sys.stderr.write(f"salvage: error: {message}\n")
    except Exception:
        pass


def sha256_file(path: str) -> str | None:
    """SHA-256 of a regular file, streamed in 1 MB chunks; None if unreadable."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        h = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return h.hexdigest()
            h.update(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)


def _prepare_output(output_dir: str, rep: dict[str, Any]) -> bool:
    try:
        os.makedirs(output_dir, exist_ok=True)
        if not os.path.isdir(output_dir):
            raise NotADirectoryError(0, "not a directory")
        return True
    except OSError as exc:
        rep["errors"].append(f"cannot create output directory: {_strerror(exc)}")
        return False


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _strerror(exc: BaseException) -> str:
    # Never str(OSError): it embeds the absolute path.
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return f"{type(exc).__name__}: {exc}"
