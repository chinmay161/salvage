"""Shared helper for tests that run the whole pipeline in-process."""

import multiprocessing

from salvage.core import pipeline


def run_checked(*args, jobs, **kwargs):
    """``pipeline.run`` with an explicit ``jobs``, then assert no worker is left.

    Every pipeline run must reap its workers: afterwards
    ``multiprocessing.active_children()`` is empty (no zombies, no orphans).
    """
    rep = pipeline.run(*args, jobs=jobs, **kwargs)
    leftover = multiprocessing.active_children()
    if leftover:
        raise AssertionError(f"worker processes left after pipeline.run: {leftover}")
    return rep
