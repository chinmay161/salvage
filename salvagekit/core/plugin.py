"""Decoder plugin interface and discovery (frozen Phase 0 contract)."""

from __future__ import annotations

import importlib
import inspect
import math
import numbers
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from salvagekit.core.model import DecodeResult

if TYPE_CHECKING:
    from salvagekit.core.reader import SafeReader


class Decoder:
    """Base class for one legacy file format.

    Rules for subclasses:

    * ``name`` is unique across all decoders and is one of the output
      contract's format names (LIBRA-98, LABLOG, VAULT, WKS, WPD, BRAVO,
      CVT, EBCDIC-DUMP, WAD, PAK): it is the output's ``format``. Only
      test-only decoders (e.g. STUB) use other names (conformance C1).
    * ``extensions`` is a weak hint only; never trust it over content.
    * :meth:`probe` must never raise and returns a confidence in 0.0-1.0.
    * :meth:`decode` must never raise; it reads only through the given
      SafeReader and returns the best partial result it can, marking
      anything unproven ``unverified`` or ``lost`` and reporting damage.
    * :meth:`encode` is optional; override it to enable round-trip checks.
    """

    name: str = ""
    extensions: tuple[str, ...] = ()

    def probe(self, data: bytes) -> float:
        """Return how likely ``data`` is this format, 0.0-1.0. Never raises."""
        return 0.0

    def decode(self, reader: "SafeReader") -> DecodeResult:
        """Decode everything reachable via ``reader``. Never raises."""
        raise NotImplementedError

    def encode(self, result: DecodeResult) -> bytes:
        """Rebuild file bytes from a DecodeResult (optional)."""
        raise NotImplementedError

    @classmethod
    def can_encode(cls) -> bool:
        """True if this class overrides :meth:`encode`."""
        return getattr(cls, "encode", None) is not Decoder.encode


def safe_probe(decoder: Decoder, data: bytes) -> tuple[float, str | None]:
    """Call ``decoder.probe(data)`` defensively.

    Returns ``(score, reason)``; ``reason`` is None when the probe behaved.
    Exceptions, non-numbers, bools and NaN give ``(0.0, reason)``; numbers
    outside [0, 1] are clamped with a reason.
    """
    try:
        result = decoder.probe(data)
    except (Exception, SystemExit) as exc:
        return 0.0, f"probe raised {_exc_text(exc)}"
    if isinstance(result, bool):
        return 0.0, "probe returned bool"
    if not isinstance(result, numbers.Real):
        return 0.0, f"probe returned non-number {type(result).__name__}"
    try:
        score = float(result)
    except Exception as exc:
        return 0.0, f"probe result not convertible to float: {_exc_text(exc)}"
    if math.isnan(score):
        return 0.0, "probe returned NaN"
    if score < 0.0:
        return 0.0, f"probe returned {score!r}, clamped to 0.0"
    if score > 1.0:
        return 1.0, f"probe returned {score!r}, clamped to 1.0"
    return score, None


@dataclass
class DiscoveryResult:
    """Decoders found by :func:`discover_decoders`, plus per-module errors."""

    decoders: list[Decoder] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def discover_decoders(package: str = "salvagekit.formats") -> DiscoveryResult:
    """Import every public module in ``package`` and collect its decoders.

    Modules are visited in name order; names starting with "_" are skipped.
    A module that fails to import, or a class that fails to instantiate, is
    reported in ``errors`` and skipped. Only Decoder subclasses defined in
    the module itself with a non-empty ``name`` count. On a duplicate name
    the first (by module name) wins. Decoders are returned sorted by name.
    """
    result = DiscoveryResult()
    try:
        pkg = importlib.import_module(package)
        paths = list(getattr(pkg, "__path__", []))
        module_names = sorted(info.name for info in pkgutil.iter_modules(paths))
    except (Exception, SystemExit) as exc:
        result.errors.append(f"{package}: {_exc_text(exc)}")
        return result

    owners: dict[str, str] = {}
    found: dict[str, Decoder] = {}
    for short in module_names:
        if short.startswith("_"):
            continue
        modname = f"{package}.{short}"
        try:
            module = importlib.import_module(modname)
        except (Exception, SystemExit) as exc:
            result.errors.append(f"{modname}: {_exc_text(exc)}")
            continue

        classes = []
        for obj in list(vars(module).values()):
            if (inspect.isclass(obj)
                    and obj.__module__ == modname
                    and issubclass(obj, Decoder)
                    and obj is not Decoder):
                classes.append(obj)
        classes.sort(key=lambda c: c.__qualname__)

        for cls in classes:
            name = getattr(cls, "name", "")
            if not isinstance(name, str) or not name:
                continue
            if name in owners:
                result.errors.append(
                    f"{modname}: duplicate decoder name {name!r} in {cls.__qualname__}; "
                    f"keeping the one from {owners[name]}")
                continue
            try:
                instance = cls()
            except (Exception, SystemExit) as exc:
                result.errors.append(f"{modname}: {cls.__qualname__}(): {_exc_text(exc)}")
                continue
            owners[name] = modname
            found[name] = instance

    result.decoders = [found[n] for n in sorted(found)]
    return result


def _exc_text(exc: BaseException) -> str:
    try:
        message = str(exc)
    except Exception:
        message = "<unprintable message>"
    return f"{type(exc).__name__}: {message}"
