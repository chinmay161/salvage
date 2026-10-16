"""Assemble FORMAT-SPEC.md, FIELD-LOG.md and the README formats table.

    python tools/build_docs.py            write the generated files
    python tools/build_docs.py --check    write nothing; exit 1 if a file is stale
    python tools/build_docs.py --strict   warnings also fail (exit 1)

Normally run as ``python tools/task.py docs [--check] [--strict]``.

Sources: ``docs/spec/<module>.md`` and ``docs/log/<module>.md`` (one per
format, written by its owner from ``docs/*/_TEMPLATE.md``),
``tools/build_docs_intro.md`` and ``docs/output-format.md``. Files whose
names start with "_" are templates and are never assembled; STUB is
test-only and excluded. The output is deterministic (no timestamps), UTF-8
with LF line endings, so running it twice changes nothing.

Errors (exit 1, nothing written): a log entry heading without a valid
"YYYY-MM-DD HH:MM", or README markers missing. Warnings (exit 0 unless
--strict): missing spec sections, a wrong first spec heading, a log entry
without a valid **Result:**, a decoder without a spec or log.
"""

from __future__ import annotations

import argparse
import difflib
import posixpath
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Section order of FORMAT-SPEC.md and tie-break order of FIELD-LOG.md (by
# module name). Modules not listed come after these, alphabetically.
FORMAT_ORDER = ("libra98", "lablog", "vault", "wks", "wpd", "bravo", "cvt", "ebcdic_dump", "wad",
                "pak")
EXCLUDED = frozenset({"stub"})   # test-only formats, never documented

SPEC_SECTIONS = ("Summary", "Identification", "Layout", "Records", "Checksums",
                 "Compression and obfuscation", "Damage handling", "Open questions")
RESULTS = ("CONFIRMED", "REJECTED", "INCONCLUSIVE")

FORMAT_SPEC = "FORMAT-SPEC.md"
FIELD_LOG = "FIELD-LOG.md"
README = "README.md"
INTRO = "tools/build_docs_intro.md"
OUTPUT_FORMAT = "docs/output-format.md"
SPEC_DIR = "docs/spec"
LOG_DIR = "docs/log"
TESTS_DIR = "tests"
MARK_START = "<!-- formats:start -->"
MARK_END = "<!-- formats:end -->"

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class FormatInfo:
    """One discovered decoder: its module's short name and class facts."""

    module: str
    name: str
    extensions: tuple[str, ...] = ()
    can_encode: bool = False


@dataclass
class Problems:
    """Warnings (fail only with --strict) and errors (always fail)."""

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# -- markdown helpers --------------------------------------------------------

_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})(?=\s|$)(.*)$")
_LINK = re.compile(r"(\]\()([^)\s]+)")


def _scan(text: str):
    """Yield ``(index, line, in_fence)`` for every line; fence lines count as in."""
    fence = None
    for i, line in enumerate(text.split("\n")):
        m = _FENCE.match(line)
        if m and (fence is None or m.group(1) == fence):
            fence = m.group(1) if fence is None else None
            yield i, line, True
        else:
            yield i, line, fence is not None


def headings(text: str) -> list[tuple[int, int, str]]:
    """``(line index, level, title)`` of every ATX heading outside code fences."""
    out = []
    for i, line, fenced in _scan(text):
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip().rstrip("#").strip()))
    return out


def demote(text: str) -> str:
    """Every heading outside code fences one level down ("# X" -> "## X"; max 6)."""
    lines = text.split("\n")
    for i, level, _ in headings(text):
        if level < 6:
            lines[i] = "#" + lines[i]
    return "\n".join(lines)


def rebase_links(text: str, src_dir: str) -> str:
    """Rewrite relative link targets written from ``src_dir`` to be repo-root relative."""
    def fix(m: re.Match) -> str:
        target = m.group(2)
        if target.startswith(("#", "/")) or ":" in target.split("/")[0]:
            return m.group(0)
        return m.group(1) + posixpath.normpath(posixpath.join(src_dir, target))

    lines = text.split("\n")
    for i, line, fenced in _scan(text):
        if not fenced:
            lines[i] = _LINK.sub(fix, line)
    return "\n".join(lines)


def slug(title: str) -> str:
    """GitHub's anchor for a heading title (before de-duplication)."""
    title = re.sub(r"[^\w\- ]", "", title.lower())
    return title.replace(" ", "-")


def anchors(text: str) -> list[tuple[int, int, str, str]]:
    """``(line, level, title, anchor)`` for every heading, de-duplicated like GitHub."""
    seen: dict[str, int] = {}
    out = []
    for i, level, title in headings(text):
        base = slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append((i, level, title, base if n == 0 else f"{base}-{n}"))
    return out


def _clean(text: str) -> str:
    """Text with LF endings and exactly one final newline (line numbers kept)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def _read(path: Path) -> str:
    return _clean(path.read_text(encoding="utf-8"))


def _rank(module: str) -> tuple[int, int, str]:
    if module in FORMAT_ORDER:
        return (0, FORMAT_ORDER.index(module), module)
    return (1, 0, module)


def doc_modules(folder: Path) -> list[str]:
    """Module names with a ``<module>.md`` in ``folder``, minus templates and
    excluded formats, in format order."""
    if not folder.is_dir():
        return []
    mods = [p.stem for p in folder.glob("*.md")
            if p.is_file() and not p.name.startswith("_") and p.stem not in EXCLUDED]
    return sorted(mods, key=_rank)


def _display(formats: dict[str, FormatInfo], module: str) -> str:
    info = formats.get(module)
    return info.name if info else module.upper()


# -- FORMAT-SPEC.md ----------------------------------------------------------

def check_spec(rel: str, text: str, info: FormatInfo | None, probs: Problems) -> None:
    """Warn about a wrong first heading and missing template sections."""
    heads = headings(text)
    if info is None:
        probs.warnings.append(f"{rel}: no decoder found for this module "
                              f"(salvagekit/formats/{Path(rel).stem}.py)")
    elif not heads or heads[0][1] != 1 or heads[0][2] != info.name:
        first = f"'{'#' * heads[0][1]} {heads[0][2]}'" if heads else "none"
        probs.warnings.append(f"{rel}: first heading must be '# {info.name}' "
                              f"(the decoder name), found {first}")
    present = {title.casefold() for _, level, title in heads if level == 2}
    for section in SPEC_SECTIONS:
        if section.casefold() not in present:
            probs.warnings.append(f"{rel}: missing section '## {section}'")


def build_format_spec(root: Path, formats: dict[str, FormatInfo],
                      probs: Problems) -> tuple[str, dict[str, str]]:
    """FORMAT-SPEC.md text, and the anchor of each format's section by module."""
    spec_dir = root / SPEC_DIR
    parts = [f"<!-- Generated by tools/build_docs.py from {SPEC_DIR}/. "
             "Do not edit by hand. -->",
             "# Salvage format specifications",
             demote(rebase_links(_read(root / INTRO), posixpath.dirname(INTRO))),
             "## Contents\n\n@@TOC@@"]
    sections: list[tuple[str, int]] = []   # (module, index into parts)
    modules = doc_modules(spec_dir)
    for module in modules:
        rel = f"{SPEC_DIR}/{module}.md"
        text = _read(spec_dir / f"{module}.md")
        check_spec(rel, text, formats.get(module), probs)
        sections.append((module, len(parts)))
        parts.append(demote(rebase_links(text, SPEC_DIR)))
    if not modules:
        parts.append("No format specifications have been written yet.")
    parts.append(demote(rebase_links(_read(root / OUTPUT_FORMAT),
                                     posixpath.dirname(OUTPUT_FORMAT))))
    lines: list[str] = []
    starts: list[int] = []        # first line of each part
    for part in parts:
        if lines:
            lines.append("")
        starts.append(len(lines))
        lines.extend(part.strip("\n").split("\n"))

    found = anchors("\n".join(lines))
    toc_line = lines.index("@@TOC@@")
    lines[toc_line] = "\n".join(f"- [{title}](#{anchor})" for i, level, title, anchor in found
                                if level == 2 and i > toc_line)
    # A format's anchor is that of its section's first (demoted) heading.
    by_line = {i: anchor for i, level, _, anchor in found if level == 2}
    module_anchor = {}
    for module, idx in sections:
        first = headings(parts[idx].strip("\n"))
        if first and starts[idx] + first[0][0] in by_line:
            module_anchor[module] = by_line[starts[idx] + first[0][0]]
    return "\n".join(lines) + "\n", module_anchor


# -- FIELD-LOG.md ------------------------------------------------------------

_ENTRY = re.compile(r"^### (.+?) — (.+)$")
_RESULT = re.compile(r"^\s*(?:[-*]\s+)?\*\*Result:\*\*\s*(.*)$")


@dataclass
class Entry:
    when: datetime
    module: str
    order: int
    title: str
    body: str
    result: str | None


def parse_log(rel: str, text: str, module: str, probs: Problems) -> list[Entry]:
    """Entries of one log file. Every "###" heading outside code fences is an
    entry; a heading of level 1-3 ends the previous one."""
    lines = text.split("\n")
    heads = [h for h in headings(text) if h[1] <= 3]
    entries = []
    for k, (i, level, _) in enumerate(heads):
        if level != 3:
            continue
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        line = lines[i].rstrip()
        m = _ENTRY.match(line)
        when = None
        if m and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", m.group(1)):
            try:
                when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                pass
        if when is None:
            probs.errors.append(f"{rel}:{i + 1}: entry heading must be "
                                f"'### YYYY-MM-DD HH:MM — <title>' with a valid date "
                                f"and time, found '{line}'")
            continue
        title = m.group(2).strip()
        body = "\n".join(lines[i + 1:end]).strip("\n")
        result = None
        for j, body_line in enumerate(lines[i + 1:end], start=i + 2):
            r = _RESULT.match(body_line)
            if r:
                word = re.match(r"[A-Za-z]*", r.group(1)).group(0)
                if word in RESULTS:
                    result = word
                else:
                    probs.warnings.append(
                        f"{rel}:{j}: Result of '{title}' must start with "
                        f"{', '.join(RESULTS[:-1])} or {RESULTS[-1]}, found "
                        f"'{r.group(1).strip()}'")
                break
        else:
            probs.warnings.append(f"{rel}:{i + 1}: entry '{title}' has no **Result:** line")
        entries.append(Entry(when, module, len(entries), title, body, result))
    return entries


def build_field_log(root: Path, formats: dict[str, FormatInfo], probs: Problems) -> str:
    """FIELD-LOG.md text."""
    log_dir = root / LOG_DIR
    modules = doc_modules(log_dir)
    entries: list[Entry] = []
    for module in modules:
        rel = f"{LOG_DIR}/{module}.md"
        entries += parse_log(rel, _read(log_dir / f"{module}.md"), module, probs)
    entries.sort(key=lambda e: (e.when, _rank(e.module), e.order))

    out = [f"<!-- Generated by tools/build_docs.py from {LOG_DIR}/. Do not edit by hand. -->",
           "# Salvage field log",
           "Every hypothesis we tested while reverse-engineering the formats, "
           "including the ones that failed, merged from each format's research "
           "log and sorted by date and time. All times are local time (IST, UTC+05:30).",
           "## Summary",
           "| Format | Entries | Confirmed | Rejected | Inconclusive |\n"
           "|--------|--------:|----------:|---------:|-------------:|"]
    rows = []
    totals = [0, 0, 0, 0]
    for module in modules:
        mine = [e for e in entries if e.module == module]
        counts = [len(mine)] + [sum(1 for e in mine if e.result == r) for r in RESULTS]
        totals = [a + b for a, b in zip(totals, counts)]
        rows.append(f"| {_display(formats, module)} | " + " | ".join(map(str, counts)) + " |")
    rows.append("| **Total** | " + " | ".join(f"**{n}**" for n in totals) + " |")
    out[-1] += "\n" + "\n".join(rows)
    out.append("## Entries")
    if not entries:
        out.append("No entries yet.")
    for e in entries:
        head = (f"### {e.when:%Y-%m-%d %H:%M} — [{_display(formats, e.module)}] {e.title}")
        out.append(head + ("\n\n" + e.body if e.body else ""))
    return "\n\n".join(out) + "\n"


# -- README formats table ----------------------------------------------------

def golden_cases(root: Path, module: str) -> int:
    """Inputs in tests/<module>/cases/ that have an .expected.json."""
    cases = root / TESTS_DIR / module / "cases"
    if not cases.is_dir():
        return 0
    names = {p.name for p in cases.iterdir() if p.is_file()}
    return sum(1 for n in names
               if not n.endswith(".expected.json") and f"{n}.expected.json" in names)


def formats_table(root: Path, formats: dict[str, FormatInfo],
                  spec_anchor: dict[str, str]) -> str:
    """The README supported-formats table (or a one-line note if there are none)."""
    mods = sorted((m for m in formats if m not in EXCLUDED), key=_rank)
    if not mods:
        return "No format decoders merged yet."
    rows = ["| Format | Extensions | Round-trip proof | Golden cases | Spec | Log |",
            "|--------|------------|------------------|-------------:|------|-----|"]
    for module in mods:
        info = formats[module]
        exts = ", ".join(f"`{e}`" for e in info.extensions) or "—"
        spec = (f"[yes]({FORMAT_SPEC}#{spec_anchor[module]})" if module in spec_anchor
                else "no")
        log = "yes" if (root / LOG_DIR / f"{module}.md").is_file() else "no"
        rows.append(f"| {info.name} | {exts} | {'yes' if info.can_encode else 'no'} | "
                    f"{golden_cases(root, module)} | {spec} | {log} |")
    return "\n".join(rows)


def replace_table(readme: str, table: str, probs: Problems) -> str:
    """``readme`` with the text between the markers replaced by ``table``."""
    if readme.count(MARK_START) != 1 or readme.count(MARK_END) != 1 \
            or readme.index(MARK_START) > readme.index(MARK_END):
        probs.errors.append(f"{README}: needs exactly one '{MARK_START}' followed by "
                            f"one '{MARK_END}'")
        return readme
    start = readme.index(MARK_START) + len(MARK_START)
    end = readme.index(MARK_END)
    return readme[:start] + "\n" + table + "\n" + readme[end:]


# -- driver ------------------------------------------------------------------

def discover(package: str = "salvagekit.formats", probs: Problems | None = None
             ) -> dict[str, FormatInfo]:
    """Decoders in ``package`` by module short name (import errors -> warnings)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from salvagekit.core.plugin import discover_decoders

    found = discover_decoders(package)
    if probs is not None:
        probs.warnings += [f"decoder discovery: {e}" for e in found.errors]
    out: dict[str, FormatInfo] = {}
    for d in found.decoders:
        module = type(d).__module__.rsplit(".", 1)[-1]
        out.setdefault(module, FormatInfo(module, d.name, tuple(d.extensions),
                                          bool(type(d).can_encode())))
    return out


def generate(root: Path, formats: dict[str, FormatInfo]) -> tuple[dict[str, str], Problems]:
    """Every generated file's full text by repo-relative path, and the problems."""
    probs = Problems()
    formats = {m: f for m, f in formats.items() if m not in EXCLUDED and f.name != "STUB"}
    spec, spec_anchor = build_format_spec(root, formats, probs)
    log = build_field_log(root, formats, probs)
    for module in sorted(formats, key=_rank):
        for folder, what in ((SPEC_DIR, "spec"), (LOG_DIR, "research log")):
            if not (root / folder / f"{module}.md").is_file():
                probs.warnings.append(f"{formats[module].name}: no {what} "
                                      f"({folder}/{module}.md)")
    readme_path = root / README
    readme = readme_path.read_bytes().decode("utf-8") if readme_path.is_file() else ""
    if not readme:
        probs.errors.append(f"{README}: missing or empty")
    readme = replace_table(readme, formats_table(root, formats, spec_anchor), probs)
    return {FORMAT_SPEC: spec, FIELD_LOG: log, README: readme}, probs


def run(root: Path, formats: dict[str, FormatInfo], *, check: bool = False,
        strict: bool = False, out=None, extra: Problems | None = None) -> int:
    """Generate (or with ``check`` compare) the files under ``root``; exit code."""
    out = out or sys.stdout
    files, probs = generate(root, formats)
    if extra is not None:
        probs.warnings = extra.warnings + probs.warnings
        probs.errors = extra.errors + probs.errors
    for w in probs.warnings:
        print(f"warning: {w}", file=out)
    for e in probs.errors:
        print(f"error: {e}", file=out)
    if probs.errors:
        print(f"docs: {len(probs.errors)} error(s); nothing written", file=out)
        return 1

    stale = []
    for rel, text in files.items():
        path = root / rel
        new = text.encode("utf-8")
        old = path.read_bytes() if path.is_file() else None
        if old == new:
            continue
        stale.append(rel)
        if check:
            print(f"stale: {rel}" + (" (missing)" if old is None else ""), file=out)
            diff = list(difflib.unified_diff(
                (old or b"").decode("utf-8", "replace").splitlines(), text.splitlines(),
                f"{rel} (committed)", f"{rel} (generated)", lineterm="", n=1))
            for line in diff[:40]:
                print(f"  {line}", file=out)
            if len(diff) > 40:
                print(f"  ... {len(diff) - 40} more diff lines", file=out)
        else:
            path.write_bytes(new)
            print(f"wrote {rel}", file=out)

    if check and stale:
        print("docs --check: stale files; run `python tools/task.py docs` and commit them",
              file=out)
        return 1
    if not stale:
        print("docs: up to date" if check else "docs: nothing changed", file=out)
    if strict and probs.warnings:
        print(f"docs --strict: {len(probs.warnings)} warning(s)", file=out)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble FORMAT-SPEC.md, FIELD-LOG.md "
                                                 "and the README formats table.")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if a generated file is stale")
    parser.add_argument("--strict", action="store_true", help="warnings also fail")
    args = parser.parse_args(argv)
    probs = Problems()
    formats = discover(probs=probs)
    return run(ROOT, formats, check=args.check, strict=args.strict, extra=probs)


if __name__ == "__main__":
    sys.exit(main())
