"""Print the public API of salvagekit.core.* and salvagekit.formats.* (sorted).

Used to validate the Phase 0 contract: ``python tools/api_dump.py``.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGES = ("salvagekit.core", "salvagekit.formats")


def _sig(obj: object) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "(...)"


def _defining_class(cls: type, name: str) -> type | None:
    for klass in cls.__mro__:
        if name in vars(klass):
            return klass
    return None


def _class_lines(cls: type) -> list[str]:
    if issubclass(cls, tuple) and hasattr(cls, "_fields"):
        ann = getattr(cls, "__annotations__", {})
        def text(a: object) -> str:
            return getattr(a, "__forward_arg__", None) or getattr(a, "__name__", None) or str(a)
        fields = ", ".join(f"{f}: {text(ann.get(f, '?'))}" for f in cls._fields)
        return [f"class {cls.__name__}(NamedTuple): {fields}"]
    bases = ", ".join(b.__name__ for b in cls.__bases__ if b is not object)
    head = f"class {cls.__name__}({bases})" if bases else f"class {cls.__name__}"
    if issubclass(cls, enum.Enum):
        lines = [head]
        for member in cls:
            lines.append(f"    {member.name} = {member.value!r}")
    else:
        lines = [f"{head}{_sig(cls)}"]
    names = set(dir(cls))
    for klass in cls.__mro__:
        names.update(vars(klass))
    for name in sorted(names):
        if name.startswith("_"):
            continue
        owner = _defining_class(cls, name)
        if owner is None or not owner.__module__.startswith("salvage"):
            continue
        raw = vars(owner)[name]
        if isinstance(raw, property):
            lines.append(f"    @property {name}")
        elif isinstance(raw, staticmethod):
            lines.append(f"    @staticmethod {name}{_sig(raw.__func__)}")
        elif isinstance(raw, classmethod):
            lines.append(f"    @classmethod {name}{_sig(raw.__func__)}")
        elif inspect.isfunction(raw):
            lines.append(f"    def {name}{_sig(raw)}")
        elif not (issubclass(cls, enum.Enum) and isinstance(raw, cls)):
            lines.append(f"    {name} = {raw!r}")
    return lines


def dump_module(modname: str) -> list[str]:
    module = importlib.import_module(modname)
    lines = [f"== {modname}"]
    for name in sorted(vars(module)):
        if name.startswith("_"):
            continue
        obj = vars(module)[name]
        if getattr(obj, "__module__", None) != modname:
            continue
        if inspect.isclass(obj):
            lines.extend(_class_lines(obj))
        elif inspect.isfunction(obj):
            lines.append(f"def {name}{_sig(obj)}")
    return lines


def main() -> int:
    out: list[str] = []
    for pkg_name in PACKAGES:
        pkg = importlib.import_module(pkg_name)
        names = sorted(f"{pkg_name}.{m.name}" for m in pkgutil.iter_modules(pkg.__path__)
                       if not m.name.startswith("_"))
        for modname in names:
            out.extend(dump_module(modname))
            out.append("")
    print("\n".join(out).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
