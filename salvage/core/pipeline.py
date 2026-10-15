"""End-to-end run: walk, decode each file in isolation, write outputs and report.json."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from typing import Any, Callable

from salvage.core import emit, isolate, report, validate, walk
from salvage.core.limits import MAX_FILE_BYTES, MAX_SECONDS_PER_FILE

Progress = Callable[[dict[str, Any]], None]


def run(input_dir: str, output_dir: str, *, decoder_package: str = "salvage.formats",
        timeout: float = MAX_SECONDS_PER_FILE, progress: Progress | None = None
        ) -> dict[str, Any]:
    """Process every regular file under ``input_dir``; return the report dict.

    Writes one JSON per input plus ``report.json`` (written last, also when
    the run fails midway) into ``output_dir``. Problems are recorded in the
    report, never raised (KeyboardInterrupt still propagates after the
    report is written). ``progress`` is called with each finished report
    entry. Never overwrites an input file.

    On Windows workers are started with "spawn", which re-imports the
    calling script: scripts that call run() need an
    ``if __name__ == "__main__":`` guard (``python -m salvage.cli`` has one).
    """
    rep = report.new_report()
    out_ok = _prepare_output(output_dir, rep)
    protected: set[str] = set()
    try:
        if not out_ok:
            return rep
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

        for item in inputs:
            try:
                output, entry, errs = _process(item, decoder_package, timeout)
            except Exception as exc:  # noqa: BLE001 - one file never stops the run
                payload = isolate.failed_payload(
                    item.rel, item.size, f"internal error: {type(exc).__name__}: {exc}")
                output, entry, errs = payload["output"], payload["entry"], []
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
                emit.write_json(target, output)
            except (OSError, ValueError, TypeError) as exc:
                entry["errors"].append(f"cannot write output: {_strerror(exc)}")
                entry["output"] = None
            rep["files"].append(entry)
            if progress is not None:
                try:
                    progress(entry)
                except Exception:
                    pass
        rep["errors"].extend(sorted(run_errors))
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
    return rep


def _process(item: walk.InputFile, package: str, timeout: float
             ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Decode one input in a child process; returns (output, entry, run errors)."""
    sha = sha256_file(item.path)
    if item.size > MAX_FILE_BYTES:
        payload: dict[str, Any] | None = isolate.failed_payload(
            item.rel, item.size, f"too large ({item.size} bytes > {MAX_FILE_BYTES})")
    else:
        payload, reason, info = isolate.run_isolated(item.path, item.rel, package, timeout)
        if payload is None:
            # Keep what the child identified before it timed out or crashed.
            payload = isolate.failed_payload(item.rel, item.size, reason or "worker failed",
                                             info)
    output, entry = payload["output"], payload["entry"]
    output["source"]["sha256"] = sha
    entry["sha256"] = sha
    errs = [str(e) for e in payload.get("run_errors") or []]
    return output, entry, errs


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
