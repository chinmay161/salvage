"""List input files deterministically, skipping anything that is not a regular file."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass


@dataclass(frozen=True)
class InputFile:
    """A regular file to process. ``rel`` is a POSIX path relative to the input dir."""

    path: str
    rel: str
    size: int


@dataclass(frozen=True)
class Skipped:
    """Something in the input tree that was not processed, and why."""

    rel: str
    reason: str


def list_inputs(input_dir: str, output_dir: str | None = None
                ) -> tuple[list[InputFile], list[Skipped]]:
    """Walk ``input_dir`` and return ``(inputs, skipped)`` in walk order.

    Directory and file names are sorted at every level, so the order is the
    same on every OS. Only regular files (by ``lstat``) are returned;
    symlinks, FIFOs, devices and sockets are listed in ``skipped`` and never
    opened. If ``output_dir`` lies strictly inside ``input_dir`` it is not
    descended into (and not listed). Never raises for file-system problems.
    """
    root = os.path.abspath(input_dir)
    out_key = _key(output_dir) if output_dir is not None else None
    if out_key == _key(root):
        out_key = None  # same folder: nothing to exclude (pipeline guards overwrites)
    inputs: list[InputFile] = []
    skipped: list[Skipped] = []

    def on_error(exc: OSError) -> None:
        rel = _rel(root, getattr(exc, "filename", None) or root)
        skipped.append(Skipped(rel or ".", f"unreadable directory: {_strerror(exc)}"))

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error, followlinks=False):
        rel_dir = _rel(root, dirpath)
        keep = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if _is_link(full):
                skipped.append(Skipped(_join(rel_dir, name), "symlink (not followed)"))
            elif out_key is not None and _key(full) == out_key:
                continue
            else:
                keep.append(name)
        dirnames[:] = keep

        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = _join(rel_dir, name)
            try:
                st = os.lstat(full)
            except OSError as exc:
                skipped.append(Skipped(rel, f"stat failed: {_strerror(exc)}"))
                continue
            if stat.S_ISREG(st.st_mode) and not _is_link(full):
                inputs.append(InputFile(full, rel, st.st_size))
            else:
                skipped.append(Skipped(rel, _kind(st.st_mode)))
    return inputs, skipped


def _kind(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink (not followed)"
    if stat.S_ISFIFO(mode):
        return "fifo (not a regular file)"
    if stat.S_ISSOCK(mode):
        return "socket (not a regular file)"
    if stat.S_ISBLK(mode):
        return "block device (not a regular file)"
    if stat.S_ISCHR(mode):
        return "character device (not a regular file)"
    if stat.S_ISDIR(mode):
        return "directory reported as file (not followed)"
    return "not a regular file"


def _is_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)  # Windows junctions
        return bool(isjunction and isjunction(path))
    except (OSError, ValueError):
        return True  # cannot tell: treat as a link, i.e. do not follow


def _key(path: str) -> str:
    """Comparable identity of a path on this OS."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _rel(root: str, path: str) -> str:
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return ""
    return "" if rel == os.curdir else rel.replace(os.sep, "/")


def _join(rel_dir: str, name: str) -> str:
    return f"{rel_dir}/{name}" if rel_dir else name


def _strerror(exc: OSError) -> str:
    # strerror only: str(exc) would leak the absolute path into the output.
    return exc.strerror or type(exc).__name__
