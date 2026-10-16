"""List input files deterministically: the regular files directly in the input dir.

The walk is NON-RECURSIVE (the output contract): subdirectories are never
entered; they are listed as skipped, like anything else that is not a
regular file.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass


@dataclass(frozen=True)
class InputFile:
    """A regular file to process. ``rel`` is its name (inputs are top-level only)."""

    path: str
    rel: str
    size: int


@dataclass(frozen=True)
class Skipped:
    """Something in the input dir that was not processed, and why."""

    rel: str
    reason: str


DIRECTORY = "directory (not entered: the walk is non-recursive)"


def list_inputs(input_dir: str, output_dir: str | None = None
                ) -> tuple[list[InputFile], list[Skipped]]:
    """List ``input_dir`` (one level) and return ``(inputs, skipped)`` in walk order.

    Names are sorted, so the order is the same on every OS. Only regular
    files (by ``lstat``) are returned; subdirectories, symlinks, FIFOs,
    devices and sockets are listed in ``skipped`` and never opened or
    entered. If ``output_dir`` is a subdirectory of ``input_dir`` it is not
    listed at all. Never raises for file-system problems (an unreadable
    input dir is one skipped entry ".").
    """
    root = os.path.abspath(input_dir)
    out_key = _key(output_dir) if output_dir is not None else None
    inputs: list[InputFile] = []
    skipped: list[Skipped] = []
    try:
        names = sorted(os.listdir(root))
    except OSError as exc:
        return inputs, [Skipped(".", f"unreadable directory: {_strerror(exc)}")]

    for name in names:
        full = os.path.join(root, name)
        try:
            st = os.lstat(full)
        except OSError as exc:
            skipped.append(Skipped(name, f"stat failed: {_strerror(exc)}"))
            continue
        if stat.S_ISREG(st.st_mode) and not _is_link(full):
            inputs.append(InputFile(full, name, st.st_size))
        elif stat.S_ISDIR(st.st_mode) and not _is_link(full):
            if out_key is not None and _key(full) == out_key:
                continue   # our own output folder
            skipped.append(Skipped(name, DIRECTORY))
        else:
            skipped.append(Skipped(name, _kind(st.st_mode)))
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
        return "symlink (not followed)"   # a junction or other directory link
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


def _strerror(exc: OSError) -> str:
    # strerror only: str(exc) would leak the absolute path into the output.
    return exc.strerror or type(exc).__name__
