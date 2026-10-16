"""A small JSON Schema validator (standard library only).

Supports a fixed subset of JSON Schema; see :data:`SUPPORTED_KEYWORDS`.
:func:`load_schema` walks the whole schema once and refuses any keyword
outside that subset (:class:`UnsupportedSchema`, naming every one and its
location), so a new schema that needs more than we implement is found at
load time instead of silently passing bad documents.

Validation rules follow JSON Schema: ``true``/``false`` are not numbers,
``1.0`` is an integer (``float.is_integer()``), ``1 == 1.0`` but
``true != 1`` for ``enum``/``const``/``uniqueItems``. ``$ref`` siblings are
applied too (2020-12 behaviour). ``format`` is an annotation only.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

ANNOTATIONS = frozenset({"$schema", "$id", "title", "description", "default", "examples",
                         "$comment", "format"})
SUPPORTED_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "prefixItems",
    "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "anyOf", "oneOf", "allOf", "not", "$ref", "$defs", "definitions",
}) | ANNOTATIONS

DEFAULT_LIMIT = 50


class SchemaError(ValueError):
    """The schema itself is unusable (bad JSON, malformed keyword, bad $ref)."""

    def __init__(self, problems: list[str], prefix: str = "invalid schema") -> None:
        self.problems = list(problems)
        super().__init__(f"{prefix}: " + "; ".join(self.problems))


class UnsupportedSchema(SchemaError):
    """The schema uses keywords this validator does not implement.

    ``problems`` holds one ``"<location>: <keyword>"`` line per keyword.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__(problems, "unsupported schema keywords")


# -- instance helpers --------------------------------------------------------

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_integer(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and math.isfinite(v) and v.is_integer()


_TYPE_TESTS: dict[str, Callable[[Any], bool]] = {
    "null": lambda v: v is None,
    "boolean": lambda v: v is True or v is False,
    "integer": _is_integer,
    "number": _is_number,
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, (list, tuple)),
    "object": lambda v: isinstance(v, dict),
}


def _json_type(v: Any) -> str:
    if v is None:
        return "null"
    if v is True or v is False:
        return "boolean"
    if _is_integer(v):
        return "integer"
    if _is_number(v):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return f"non-JSON {type(v).__name__}"


def _canon(v: Any) -> Any:
    """Hashable key with JSON equality: 1 == 1.0, true != 1, key order ignored."""
    if v is None:
        return ("z",)
    if v is True or v is False:
        return ("b", v)
    if _is_number(v):
        return ("n", v)
    if isinstance(v, str):
        return ("s", v)
    if isinstance(v, (list, tuple)):
        return ("a", tuple(_canon(x) for x in v))
    if isinstance(v, dict):
        return ("o", frozenset((str(k), _canon(x)) for k, x in v.items()))
    return ("?", id(v))


def _show(v: Any, width: int = 60) -> str:
    try:
        text = json.dumps(v, sort_keys=True, ensure_ascii=False,
                          default=lambda o: f"<{type(o).__name__}>")
    except Exception:
        text = f"<{type(v).__name__}>"
    return text if len(text) <= width else text[:width - 3] + "..."


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

# A path is a linked tuple (parent, key) or None for the root; it is only
# turned into text when an error is reported, which keeps validation fast.
Path = Any


def _fmt_path(path: Path) -> str:
    keys: list[Any] = []
    while path is not None:
        path, key = path
        keys.append(key)
    out = "$"
    for key in reversed(keys):
        if isinstance(key, int):
            out += f"[{key}]"
        elif isinstance(key, str) and _IDENT.match(key):
            out += "." + key
        else:
            out += "[" + _show(str(key), 200) + "]"
    return out


class _Errors:
    __slots__ = ("items", "limit")

    def __init__(self, limit: int) -> None:
        self.items: list[tuple[Path, str]] = []
        self.limit = limit

    def add(self, path: Path, message: str) -> None:
        if len(self.items) < self.limit:
            self.items.append((path, message))

    @property
    def full(self) -> bool:
        return len(self.items) >= self.limit


Validator = Callable[[Any, Path, _Errors], None]


def _passes(validator: Validator, instance: Any) -> bool:
    errs = _Errors(1)
    validator(instance, None, errs)
    return not errs.items


# -- load-time checks --------------------------------------------------------

def _ptr(loc: str, key: str) -> str:
    return loc + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _resolve(root: Any, ref: str) -> Any:
    """Resolve a local JSON pointer ("#", "#/a/b"); raises KeyError/IndexError."""
    if ref == "#":
        return root
    node = root
    for raw in ref[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node[part]
        else:
            raise KeyError(part)
    return node


_SCHEMA_MAPS = ("properties", "$defs", "definitions")
_SCHEMA_ONE = ("additionalProperties", "items", "not")
_SCHEMA_LISTS = ("prefixItems", "anyOf", "oneOf", "allOf")
_NUMBERS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
_COUNTS = ("minLength", "maxLength", "minItems", "maxItems")


class _Checker:
    """One pass over the schema: unsupported keywords, malformed values, refs."""

    def __init__(self, root: Any) -> None:
        self.root = root
        self.unsupported: list[str] = []
        self.malformed: list[str] = []
        self.nodes: list[tuple[dict[str, Any], str]] = []

    def walk(self, node: Any, loc: str) -> None:
        if node is True or node is False:
            return
        if not isinstance(node, dict):
            self.malformed.append(f"{loc}: a schema must be an object or a boolean")
            return
        self.nodes.append((node, loc))
        for key, value in node.items():
            here = _ptr(loc, key)
            if key not in SUPPORTED_KEYWORDS:
                self.unsupported.append(f"{here}: {key}")
                continue
            self._keyword(key, value, here)

    def _bad(self, here: str, why: str) -> None:
        self.malformed.append(f"{here}: {why}")

    def _keyword(self, key: str, value: Any, here: str) -> None:
        if key in ANNOTATIONS:
            return
        if key in _SCHEMA_MAPS:
            if not isinstance(value, dict):
                return self._bad(here, "must be an object")
            for name, sub in value.items():
                self.walk(sub, _ptr(here, name))
        elif key in _SCHEMA_ONE:
            if key == "items" and isinstance(value, list):
                self.unsupported.append(f"{here}: items (array form; use prefixItems)")
                return
            self.walk(value, here)
        elif key in _SCHEMA_LISTS:
            if not isinstance(value, list) or not value:
                return self._bad(here, "must be a non-empty array of schemas")
            for i, sub in enumerate(value):
                self.walk(sub, _ptr(here, str(i)))
        elif key == "type":
            names = value if isinstance(value, list) else [value]
            if (not names or len(set(map(str, names))) != len(names)
                    or not all(isinstance(n, str) and n in _TYPE_TESTS for n in names)):
                self._bad(here, f"invalid type {_show(value)}")
        elif key == "required":
            if not (isinstance(value, list) and all(isinstance(n, str) for n in value)):
                self._bad(here, "must be an array of strings")
        elif key == "enum":
            if not isinstance(value, list):
                self._bad(here, "must be an array")
        elif key in _NUMBERS:
            if key.startswith("exclusive") and isinstance(value, bool):
                self.unsupported.append(f"{here}: {key} (boolean form)")
            elif not _is_number(value):
                self._bad(here, "must be a number")
        elif key in _COUNTS:
            if not _is_integer(value) or value < 0:
                self._bad(here, "must be a non-negative integer")
        elif key == "uniqueItems":
            if not isinstance(value, bool):
                self._bad(here, "must be a boolean")
        elif key == "pattern":
            try:
                re.compile(value)
            except (re.error, TypeError) as exc:
                self._bad(here, f"invalid pattern: {exc}")
        elif key == "$ref":
            if not isinstance(value, str):
                self._bad(here, "must be a string")
            elif not (value == "#" or value.startswith("#/")):
                self.unsupported.append(f"{here}: $ref (non-local {value!r})")
            else:
                try:
                    _resolve(self.root, value)
                except (KeyError, IndexError, ValueError, TypeError):
                    self._bad(here, f"unresolvable $ref {value!r}")

    def same_level_cycles(self) -> None:
        """Refuse $ref/allOf/anyOf/oneOf/not loops that never descend into the
        instance: validating them would recurse forever."""
        def edges(node: dict[str, Any]) -> list[Any]:
            out = []
            ref = node.get("$ref")
            if isinstance(ref, str) and (ref == "#" or ref.startswith("#/")):
                try:
                    out.append(_resolve(self.root, ref))
                except (KeyError, IndexError, ValueError, TypeError):
                    pass
            for key in ("allOf", "anyOf", "oneOf"):
                if isinstance(node.get(key), list):
                    out.extend(node[key])
            if "not" in node:
                out.append(node["not"])
            return [e for e in out if isinstance(e, dict)]

        locs = {id(n): loc for n, loc in self.nodes}
        state: dict[int, int] = {}  # 1 = on stack, 2 = done
        for start, _ in self.nodes:
            if id(start) in state:
                continue
            stack = [(start, iter(edges(start)))]
            state[id(start)] = 1
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    state[id(node)] = 2
                    stack.pop()
                elif state.get(id(nxt)) == 1:
                    self._bad(locs.get(id(nxt), "#"),
                              "circular $ref that never descends into the instance")
                    return
                elif id(nxt) not in state:
                    state[id(nxt)] = 1
                    stack.append((nxt, iter(edges(nxt))))


# -- compilation -------------------------------------------------------------

def _ok(instance: Any, path: Path, errs: _Errors) -> None:
    return None


def _never(instance: Any, path: Path, errs: _Errors) -> None:
    errs.add(path, "no value is allowed here (schema is false)")


class _Compiler:
    def __init__(self, root: Any) -> None:
        self.root = root
        self.cache: dict[int, Validator] = {}

    def compile(self, node: Any) -> Validator:
        if node is True:
            return _ok
        if node is False:
            return _never
        key = id(node)
        if key in self.cache:
            return self.cache[key]
        slot: list[Validator] = []

        def deferred(instance: Any, path: Path, errs: _Errors) -> None:
            slot[0](instance, path, errs)

        self.cache[key] = deferred  # recursive refs see this until built
        real = self._build(node)
        slot.append(real)
        self.cache[key] = real
        return real

    def _build(self, node: dict[str, Any]) -> Validator:
        checks: list[Validator] = []
        add = checks.append

        if "$ref" in node:
            add(self.compile(_resolve(self.root, node["$ref"])))
        if "type" in node:
            add(_type_check(node["type"]))
        if "enum" in node:
            add(_enum_check(node["enum"]))
        if "const" in node:
            add(_const_check(node["const"]))
        if any(k in node for k in _NUMBERS):
            add(_number_check(node))
        if any(k in node for k in ("minLength", "maxLength", "pattern")):
            add(_string_check(node))
        if any(k in node for k in ("properties", "required", "additionalProperties")):
            add(self._object_check(node))
        if any(k in node for k in ("items", "prefixItems", "minItems", "maxItems",
                                   "uniqueItems")):
            add(self._array_check(node))
        if "allOf" in node:
            checks.extend(self.compile(s) for s in node["allOf"])
        if "anyOf" in node:
            add(self._any_of([self.compile(s) for s in node["anyOf"]]))
        if "oneOf" in node:
            add(self._one_of([self.compile(s) for s in node["oneOf"]]))
        if "not" in node:
            add(self._not(self.compile(node["not"])))

        if not checks:
            return _ok
        if len(checks) == 1:
            return checks[0]
        frozen = tuple(checks)

        def all_checks(instance: Any, path: Path, errs: _Errors) -> None:
            for check in frozen:
                check(instance, path, errs)
        return all_checks

    def _object_check(self, node: dict[str, Any]) -> Validator:
        props = {name: self.compile(s) for name, s in (node.get("properties") or {}).items()}
        required = tuple(node.get("required") or ())
        addl = node.get("additionalProperties", True)
        forbid = addl is False
        extra = None if addl is True or forbid else self.compile(addl)

        def check(instance: Any, path: Path, errs: _Errors) -> None:
            if not isinstance(instance, dict):
                return
            for name in required:
                if name not in instance:
                    errs.add(path, f"required property {_show(name)} is missing")
            for key, value in instance.items():
                sub = props.get(key)
                if sub is not None:
                    sub(value, (path, key), errs)
                elif forbid:
                    errs.add((path, key), "additional property not allowed")
                elif extra is not None:
                    extra(value, (path, key), errs)
                if errs.full:
                    return
        return check

    def _array_check(self, node: dict[str, Any]) -> Validator:
        prefix = tuple(self.compile(s) for s in node.get("prefixItems") or ())
        items = self.compile(node["items"]) if "items" in node else None
        lo, hi = node.get("minItems"), node.get("maxItems")
        unique = node.get("uniqueItems") is True
        n_prefix = len(prefix)

        def check(instance: Any, path: Path, errs: _Errors) -> None:
            if not isinstance(instance, (list, tuple)):
                return
            n = len(instance)
            if lo is not None and n < lo:
                errs.add(path, f"array has {n} items, fewer than minItems {lo}")
            if hi is not None and n > hi:
                errs.add(path, f"array has {n} items, more than maxItems {hi}")
            for i, sub in enumerate(prefix[:n]):
                sub(instance[i], (path, i), errs)
            if items is not None and items is not _ok:
                for i in range(n_prefix, n):
                    items(instance[i], (path, i), errs)
                    if errs.full:
                        return
            if unique:
                seen: dict[Any, int] = {}
                for i, value in enumerate(instance):
                    key = _canon(value)
                    if key in seen:
                        errs.add(path, f"items {seen[key]} and {i} are equal (uniqueItems)")
                        break
                    seen[key] = i
        return check

    @staticmethod
    def _any_of(subs: list[Validator]) -> Validator:
        def check(instance: Any, path: Path, errs: _Errors) -> None:
            if not any(_passes(s, instance) for s in subs):
                errs.add(path, f"{_show(instance)} does not match any schema in anyOf")
        return check

    @staticmethod
    def _one_of(subs: list[Validator]) -> Validator:
        def check(instance: Any, path: Path, errs: _Errors) -> None:
            hits = 0
            for s in subs:
                if _passes(s, instance):
                    hits += 1
                    if hits > 1:
                        break
            if hits != 1:
                what = "none" if hits == 0 else "more than one"
                errs.add(path, f"{_show(instance)} matches {what} of the oneOf schemas "
                               "(exactly one required)")
        return check

    @staticmethod
    def _not(sub: Validator) -> Validator:
        def check(instance: Any, path: Path, errs: _Errors) -> None:
            if _passes(sub, instance):
                errs.add(path, f"{_show(instance)} must not match the 'not' schema")
        return check


def _type_check(spec: Any) -> Validator:
    names = tuple(spec if isinstance(spec, list) else [spec])
    tests = tuple(_TYPE_TESTS[n] for n in names)
    want = " or ".join(names)

    if len(tests) == 1:
        only = tests[0]

        def check_one(instance: Any, path: Path, errs: _Errors) -> None:
            if not only(instance):
                errs.add(path, f"expected {want}, got {_json_type(instance)}")
        return check_one

    def check(instance: Any, path: Path, errs: _Errors) -> None:
        for test in tests:
            if test(instance):
                return
        errs.add(path, f"expected {want}, got {_json_type(instance)}")
    return check


def _enum_check(values: list[Any]) -> Validator:
    allowed = frozenset(_canon(v) for v in values)

    def check(instance: Any, path: Path, errs: _Errors) -> None:
        if _canon(instance) not in allowed:
            errs.add(path, f"{_show(instance)} is not one of {_show(values)}")
    return check


def _const_check(value: Any) -> Validator:
    want = _canon(value)

    def check(instance: Any, path: Path, errs: _Errors) -> None:
        if _canon(instance) != want:
            errs.add(path, f"{_show(instance)} is not the constant {_show(value)}")
    return check


def _number_check(node: dict[str, Any]) -> Validator:
    lo, hi = node.get("minimum"), node.get("maximum")
    xlo, xhi = node.get("exclusiveMinimum"), node.get("exclusiveMaximum")

    def check(instance: Any, path: Path, errs: _Errors) -> None:
        if not _is_number(instance):
            return
        if lo is not None and instance < lo:
            errs.add(path, f"{_show(instance)} is less than minimum {lo}")
        if hi is not None and instance > hi:
            errs.add(path, f"{_show(instance)} is greater than maximum {hi}")
        if xlo is not None and instance <= xlo:
            errs.add(path, f"{_show(instance)} is not greater than exclusiveMinimum {xlo}")
        if xhi is not None and instance >= xhi:
            errs.add(path, f"{_show(instance)} is not less than exclusiveMaximum {xhi}")
    return check


def _string_check(node: dict[str, Any]) -> Validator:
    lo, hi = node.get("minLength"), node.get("maxLength")
    pattern = re.compile(node["pattern"]) if "pattern" in node else None
    source = node.get("pattern")

    def check(instance: Any, path: Path, errs: _Errors) -> None:
        if not isinstance(instance, str):
            return
        n = len(instance)
        if lo is not None and n < lo:
            errs.add(path, f"string of length {n} is shorter than minLength {lo}")
        if hi is not None and n > hi:
            errs.add(path, f"string of length {n} is longer than maxLength {hi}")
        if pattern is not None and pattern.search(instance) is None:
            errs.add(path, f"{_show(instance)} does not match pattern {_show(source)}")
    return check


# -- public API --------------------------------------------------------------

class Schema:
    """A checked, compiled schema. Build with :func:`load_schema` or ``Schema(doc)``."""

    def __init__(self, document: Any, name: str = "<schema>") -> None:
        """Check and compile ``document``.

        Raises :class:`UnsupportedSchema` if any keyword is outside
        :data:`SUPPORTED_KEYWORDS`, else :class:`SchemaError` for malformed
        keywords, unresolvable or circular ``$ref``.
        """
        checker = _Checker(document)
        checker.walk(document, "#")
        if checker.unsupported:
            raise UnsupportedSchema(checker.unsupported)
        checker.same_level_cycles()
        if checker.malformed:
            raise SchemaError(checker.malformed)
        self.document = document
        self.name = name
        self._root = _Compiler(document).compile(document)

    def errors(self, instance: Any, limit: int = DEFAULT_LIMIT) -> list[str]:
        """Up to ``limit`` problems as ``"<json path>: <message>"``; [] means valid.

        Paths look like ``$.records[0].fields[2].status``. Never raises: an
        instance nested too deeply (or any internal failure) is reported as
        an error at ``$``.
        """
        if not _is_integer(limit) or limit < 1:
            limit = DEFAULT_LIMIT
        errs = _Errors(int(limit))
        try:
            self._root(instance, None, errs)
        except RecursionError:
            errs.items.append((None, "instance is nested too deeply to validate"))
        except Exception as exc:  # pragma: no cover - defensive
            errs.items.append((None, f"validator failed: {type(exc).__name__}"))
        try:
            return [f"{_fmt_path(p)}: {m}" for p, m in errs.items[:limit]]
        except Exception:  # pragma: no cover - defensive
            return [f"$: {m}" for _, m in errs.items[:limit]]

    def is_valid(self, instance: Any) -> bool:
        """True if :meth:`errors` finds nothing."""
        return not self.errors(instance, 1)


def load_schema(path: str) -> Schema:
    """Read a UTF-8 JSON schema file and return a :class:`Schema`.

    Raises :class:`SchemaError` if the file cannot be read or parsed, and
    :class:`UnsupportedSchema` (a SchemaError) if it uses any keyword this
    validator does not implement.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
        raise SchemaError([f"cannot read schema: {reason}"]) from None
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return Schema(document, name)
