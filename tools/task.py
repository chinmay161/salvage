"""Cross-platform task runner (standard library only).

    python tools/task.py test                 run the whole unittest suite
    python tools/task.py api                  print the public API (tools/api_dump.py)
    python tools/task.py run IN OUT           python -m salvage.cli IN OUT
    python tools/task.py build                docker build -t salvage:dev .
    python tools/task.py build-offline        same, with --network none
    python tools/task.py docker-run IN OUT    run the image on IN, writing to OUT
    python tools/task.py docker-test          run the unit tests inside the image
    python tools/task.py docker-smoke         host vs container end-to-end check
    python tools/task.py golden [FORMAT]      golden tests (all formats or one)
    python tools/task.py golden-update FORMAT regenerate one format's expectations
    python tools/task.py conform [NAME] [--verbose] [--quick]  decoder conformance suite
    python tools/task.py bench [--docker]     throughput, --jobs 1 vs --jobs auto
    python tools/task.py docs [--check] [--strict]  FORMAT-SPEC.md, FIELD-LOG.md, README table
    python tools/task.py check-outputs IN OUT one valid JSON per input + report.json?
    python tools/task.py lint-docker          Dockerfile: no network in RUN, FROM pinned
    python tools/task.py save-base|load-base  base image <-> dist/base-image.tar
    python tools/task.py precheck             release checklist on a clean clone of HEAD

Uses ``sys.executable``, so it works whatever the interpreter is called.
This is a dev tool: unknown commands print usage and exit with code 2;
failed checks exit with code 1.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "salvage:dev"
DOCKER_PROBE_TIMEOUT = 30      # seconds for "is the daemon there?"
DOCKER_RUN_TIMEOUT = 3600      # seconds for a container run (never hang forever)

USAGE = """usage: python tools/task.py <command>

commands:
  test                  run all tests
  api                   print the public API of salvage.core and salvage.formats
  run IN OUT            run the salvage CLI on IN, writing to OUT
  build                 docker build -t salvage:dev .
  build-offline         docker build --network none -t salvage:dev .
                        (the base image must already be pulled)
  docker-run IN OUT     run salvage:dev on IN (read-only), writing to OUT
  docker-test           run the unit tests with the image's Linux Python
  docker-smoke          run a small input set on the host and in Docker and
                        check both outputs are byte-identical
  golden [FORMAT]       run golden tests (all formats, or just FORMAT)
  golden-update FORMAT  regenerate tests/FORMAT/cases/*.expected.json
  conform [NAME] [--verbose] [--quick]
                        check every decoder (or NAME) against the contract
                        (docs/conformance.md); exit 1 if any FAILs.
                        --quick: the merge gate's smaller run (no samples/)
  bench [--docker]      time the CLI on 525 generated files with --jobs 1
                        and --jobs auto (--docker: inside the image)
  docs [--check] [--strict]
                        generate FORMAT-SPEC.md, FIELD-LOG.md and the README
                        formats table (tools/build_docs.py); --check writes
                        nothing and exits 1 if a file is stale; --strict
                        also fails on warnings
  check-outputs IN OUT  check a finished run: report.json present, one JSON
                        per input file, every file valid against the active
                        schema
  lint-docker           static Dockerfile check: no RUN step uses apt, pip,
                        curl, wget, git, npm or a URL; FROM pinned by digest
  save-base             docker save the pinned base image to dist/base-image.tar
  load-base             docker load dist/base-image.tar
  precheck              release checklist on a clean clone of HEAD: test,
                        conform, docs --check, lint-docker, offline build,
                        docker run on samples/ + golden inputs, docker-smoke
"""


def _env(**extra: str) -> dict[str, str]:
    """Environment with the repo root first on PYTHONPATH."""
    env = dict(os.environ)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + old if old else "")
    env.update(extra)
    return env


# -- docker helpers ----------------------------------------------------------

def _docker_ready() -> bool:
    """True if the docker CLI exists and the daemon answers; else print why."""
    if shutil.which("docker") is None:
        print("error: docker is not installed (no 'docker' on PATH)", file=sys.stderr)
        return False
    try:
        proc = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                              capture_output=True, text=True, timeout=DOCKER_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"error: docker did not answer within {DOCKER_PROBE_TIMEOUT}s "
              "(is Docker Desktop / the docker daemon running?)", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"error: cannot run docker: {exc}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print("error: the docker daemon is not running (start Docker Desktop or "
              "dockerd); docker said:\n  " + (proc.stderr.strip() or "no details"),
              file=sys.stderr)
        return False
    return True


def _docker(args: list[str], timeout: float = DOCKER_RUN_TIMEOUT, **kw) -> int:
    """Run ``docker <args>``; returns its exit code (124 on timeout)."""
    try:
        return subprocess.run(["docker", *args], timeout=timeout, **kw).returncode
    except subprocess.TimeoutExpired:
        print(f"error: docker {args[0]} timed out after {timeout}s", file=sys.stderr)
        return 124


def normalize_git_bash_path(path: str | Path, *, _os_name: str | None = None) -> str:
    """Normalize a Git Bash drive path (/c/x -> C:/x) on Windows before abspath."""
    p = str(path)
    current_os = os.name if _os_name is None else _os_name
    if current_os == "nt":
        normalized = p.replace("\\", "/")
        m = re.match(r"^//?([a-zA-Z])(/.*)?$", normalized)
        if m:
            drive = m.group(1).upper()
            rest = m.group(2) or "/"
            return f"{drive}:{rest}" if rest.startswith("/") else f"{drive}:/{rest}"
    return p


def host_path(path: str | Path, *, _os_name: str | None = None) -> str:
    """Absolute path in a form ``docker -v`` accepts (C:/x/y on Windows)."""
    p = normalize_git_bash_path(path, _os_name=_os_name)
    current_os = os.name if _os_name is None else _os_name
    full = os.path.abspath(p)
    return full.replace("\\", "/") if current_os == "nt" else full


def docker_run_args(inp: str | Path, out: str | Path) -> list[str]:
    """Arguments for ``docker`` that run the image on ``inp`` writing to ``out``."""
    return ["run", "--rm", "--network", "none",
            "-v", f"{host_path(inp)}:/in:ro", "-v", f"{host_path(out)}:/out",
            IMAGE, "/salvage", "/in", "/out"]


def docker_run(inp: str | Path, out: str | Path, **kw) -> int:
    """Create ``out`` and run the image on ``inp``; returns docker's exit code."""
    os.makedirs(out, exist_ok=True)
    return _docker(docker_run_args(inp, out), **kw)


def cmd_build(offline: bool) -> int:
    if not _docker_ready():
        return 1
    net = ["--network", "none"] if offline else []
    return _docker(["build", *net, "-t", IMAGE, str(ROOT)])


def cmd_docker_test() -> int:
    if not _docker_ready():
        return 1
    # Read-only source mount; tests only write to tempfile dirs (/tmp) and the
    # image sets PYTHONDONTWRITEBYTECODE, so no working copy is needed.
    return _docker(["run", "--rm", "--network", "none",
                    "-v", f"{host_path(ROOT)}:/src:ro", "-w", "/src",
                    "-e", "PYTHONPATH=/src", "--entrypoint", "python3", IMAGE,
                    "-m", "unittest", "discover", "-s", "tests", "-t", "."])


# -- docker-smoke ------------------------------------------------------------

def smoke_inputs() -> dict[str, bytes]:
    """The fixed docker-smoke input set (relative POSIX path -> bytes)."""
    magic = b"SALVAGE-STUB\x00"
    clean = magic + struct.pack("<H3I", 3, 10, 20, 30)
    return {
        "clean1.stub": clean,
        "clean2.stub": magic + struct.pack("<H2I", 2, 7, 0xFFFFFFFF),
        "truncated.stub": magic + struct.pack("<H2I", 5, 1, 2),
        "sub/nested.stub": clean,
        "empty.bin": b"",
        "random.bin": random.Random(1234).randbytes(64 * 1024),
        "report": b"a file named report\n",
    }


def _read_tree(root: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, root).replace(os.sep, "/")] = fh.read()
    return out


def cmd_docker_smoke() -> int:
    if not _docker_ready():
        return 1
    sys.path.insert(0, str(ROOT))
    from salvage.core import emit

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""),
              flush=True)

    tmp = tempfile.mkdtemp(prefix="salvage-smoke-")
    keep = False
    try:
        inp = os.path.join(tmp, "in")
        files = smoke_inputs()
        for rel, data in files.items():
            path = os.path.join(inp, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        expected = set(emit.output_names(files).values()) | {"report.json"}

        out_host, out_docker = os.path.join(tmp, "out-host"), os.path.join(tmp, "out-docker")
        host = subprocess.run([sys.executable, "-m", "salvage.cli", inp, out_host],
                              env=_env(), capture_output=True, timeout=DOCKER_RUN_TIMEOUT)
        check("host run exits 0", host.returncode == 0, f"exit {host.returncode}")
        code = docker_run(inp, out_docker, capture_output=True)
        check("docker run (--network none) exits 0", code == 0, f"exit {code}")

        trees = {"host": _read_tree(out_host), "docker": _read_tree(out_docker)}
        for side, tree in trees.items():
            check(f"{side}: report.json present", "report.json" in tree)
            check(f"{side}: one JSON per input ({len(files)} inputs)",
                  set(tree) == expected,
                  f"missing {sorted(expected - set(tree))}, extra {sorted(set(tree) - expected)}"
                  if set(tree) != expected else f"{len(tree) - 1} outputs")
        differ = sorted(rel for rel in set(trees["host"]) | set(trees["docker"])
                        if trees["host"].get(rel) != trees["docker"].get(rel))
        check("host and docker outputs byte-identical", not differ,
              f"differ: {differ}" if differ else f"{len(trees['host'])} files compared")

        code = _docker(["run", "--rm", IMAGE, "/tmp/does-not-exist", "/tmp/out"],
                       capture_output=True)
        check("docker run on a missing input dir exits 0", code == 0, f"exit {code}")
        keep = not all(ok for _, ok, _ in results)
    finally:
        if keep:
            print(f"outputs kept for inspection in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"docker-smoke: {len(results) - failed} PASS, {failed} FAIL")
    return 1 if failed else 0


# -- bench -------------------------------------------------------------------

def bench_inputs() -> dict[str, bytes]:
    """The fixed bench input set: 500 small STUB files, 20 random 1 MiB files,
    5 truncated STUB files (relative POSIX path -> bytes)."""
    magic = b"SALVAGE-STUB\x00"
    files: dict[str, bytes] = {}
    for i in range(500):
        files[f"stub/{i // 100}/s{i:03d}.stub"] = magic + struct.pack("<H3I", 3, i, i + 1, i + 2)
    rng = random.Random("salvage-bench")
    for i in range(20):
        files[f"random/r{i:02d}.bin"] = rng.randbytes(1024 * 1024)
    for i in range(5):
        files[f"truncated/t{i}.stub"] = magic + struct.pack("<H2I", 5 + i, i, i)
    return files


def _stats_line(stderr: str) -> dict[str, str]:
    for line in reversed(stderr.splitlines()):
        if line.startswith("stats: "):
            return dict(part.split("=", 1) for part in line[len("stats: "):].split())
    return {}


def cmd_bench(use_docker: bool) -> int:
    if use_docker and not _docker_ready():
        return 1
    tmp = tempfile.mkdtemp(prefix="salvage-bench-")
    try:
        inp = os.path.join(tmp, "in")
        files = bench_inputs()
        for rel, data in files.items():
            path = os.path.join(inp, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        where = "docker (salvage:dev)" if use_docker else f"host ({sys.platform})"
        print(f"bench: {len(files)} files on {where}, host cpu_count={os.cpu_count()}")
        print(f"{'jobs':<6} {'seconds':>8} {'files/s':>8} {'peak workers':>13}")
        rows, trees = [], {}
        for jobs in ("1", "auto"):
            out = os.path.join(tmp, f"out-{jobs}")
            start = time.perf_counter()
            if use_docker:
                os.makedirs(out, exist_ok=True)
                proc = subprocess.run(["docker", *docker_run_args(inp, out), "--jobs", jobs,
                                       "--stats"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace",
                                      timeout=DOCKER_RUN_TIMEOUT)
            else:
                proc = subprocess.run([sys.executable, "-m", "salvage.cli", "--jobs", jobs,
                                       "--stats", inp, out], env=_env(), capture_output=True,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=DOCKER_RUN_TIMEOUT)
            seconds = time.perf_counter() - start
            stats = _stats_line(proc.stderr)
            label = jobs if jobs == "1" else f"auto={stats.get('jobs', '?')}"
            rows.append((label, seconds, stats))
            trees[jobs] = _read_tree(out)
            print(f"{label:<6} {seconds:>8.2f} {len(files) / seconds:>8.1f} "
                  f"{stats.get('peak_workers', '?'):>13}", flush=True)
            if proc.returncode != 0 or stats.get("files") != str(len(files)):
                print(f"error: run with --jobs {jobs} exited {proc.returncode}, "
                      f"stats {stats}", file=sys.stderr)
                return 1
        same = trees["1"] == trees["auto"]
        print(f"outputs --jobs 1 vs --jobs auto: {'byte-identical' if same else 'DIFFER'}")
        auto_rate = len(files) / rows[1][1]
        if use_docker and auto_rate < 20:
            print(f"note: docker --jobs auto is under 20 files/s ({auto_rate:.1f})")
        return 0 if same else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -- check-outputs -----------------------------------------------------------

def cmd_check_outputs(inp: str, out: str) -> int:
    """Check a finished run's output folder; print one line per problem."""
    sys.path.insert(0, str(ROOT))
    import json

    from salvage.core import emit, validate, walk

    inputs, _ = walk.list_inputs(inp, out)
    rels = [i.rel for i in inputs]
    expected = set(emit.output_names(rels).values()) | {emit.REPORT_NAME}
    found = set(_read_tree(out)) if os.path.isdir(out) else set()
    problems: list[str] = []
    if emit.REPORT_NAME not in found:
        problems.append("report.json is missing")
    problems += [f"missing output: {rel}" for rel in sorted(expected - found)
                 if rel != emit.REPORT_NAME]
    problems += [f"unexpected file: {rel}" for rel in sorted(found - expected)]
    for rel in sorted(expected & found):
        kind = "report" if rel == emit.REPORT_NAME else "output"
        try:
            with open(os.path.join(out, *rel.split("/")), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            problems.append(f"{rel}: cannot read JSON: {exc}")
            continue
        problems += [f"{rel}: {e}" for e in validate.errors(kind, doc)[:3]]
    for p in problems:
        print(f"FAIL  {p}")
    print(f"check-outputs: {len(rels)} inputs, {len(found)} files in output, "
          f"{len(problems)} problems")
    return 1 if problems else 0


# -- Dockerfile lint, base image ---------------------------------------------

NETWORK_TOOLS = ("apt", "apt-get", "aptitude", "pip", "pip3", "curl", "wget", "git", "npm")
_TOOL_RE = r"(?<![\w.-])(" + "|".join(re.escape(t) for t in NETWORK_TOOLS) + r")(?![\w-])"
_URL_RE = r"\b[a-z][a-z0-9+.-]*://"
BASE_TAR = ROOT / "dist" / "base-image.tar"


def dockerfile_steps(text: str) -> list[tuple[int, str, str]]:
    """``(first line number, INSTRUCTION, arguments)`` with continuations joined."""
    steps: list[tuple[int, str, str]] = []
    buf: list[str] = []
    start = 0
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if buf and stripped.startswith("#"):
            continue  # docker drops comment lines inside a continuation
        if not buf:
            start = n
        cont = stripped.endswith("\\")
        buf.append(stripped[:-1].rstrip() if cont else stripped)
        if not cont:
            word, _, rest = " ".join(buf).partition(" ")
            steps.append((start, word.upper(), rest.strip()))
            buf = []
    if buf:
        word, _, rest = " ".join(buf).partition(" ")
        steps.append((start, word.upper(), rest.strip()))
    return steps


def lint_dockerfile(text: str) -> list[str]:
    """Problems in a Dockerfile's text, each starting with "line N:"."""
    problems = []
    steps = dockerfile_steps(text)
    if not any(word == "FROM" for _, word, _ in steps):
        problems.append("line 1: no FROM instruction")
    for n, word, args in steps:
        if word == "FROM":
            image = next((a for a in args.split() if not a.startswith("--")), "")
            if not re.search(r"@sha256:[0-9a-f]{64}$", image):
                problems.append(f"line {n}: FROM {image} is not pinned by digest "
                                "(use image:tag@sha256:<digest>)")
        if word == "RUN":
            tool = re.search(_TOOL_RE, args)
            if tool:
                problems.append(f"line {n}: RUN uses '{tool.group(1)}' (network access "
                                f"at build time): RUN {args}")
        if word in ("RUN", "ADD") and re.search(_URL_RE, args, re.I):
            problems.append(f"line {n}: {word} contains a URL: {word} {args}")
    return problems


def base_image() -> str | None:
    """The image reference of the Dockerfile's first FROM."""
    steps = dockerfile_steps((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    for _, word, args in steps:
        if word == "FROM":
            return next((a for a in args.split() if not a.startswith("--")), None)
    return None


def cmd_lint_docker() -> int:
    problems = lint_dockerfile((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    for p in problems:
        print(f"Dockerfile {p}")
    print(f"lint-docker: {'FAIL' if problems else 'PASS'} ({len(problems)} problems)")
    return 1 if problems else 0


def _image_ids(ref: str) -> tuple[str, list[str]] | None:
    """``(image id, repo digests)`` of a local image, or None if absent."""
    proc = subprocess.run(["docker", "image", "inspect", ref, "--format",
                           "{{.Id}} {{join .RepoDigests \" \"}}"],
                          capture_output=True, text=True, timeout=DOCKER_PROBE_TIMEOUT)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    image_id, *digests = proc.stdout.split()
    return image_id, digests


def _base_present(ref: str) -> bool:
    """True if the pinned image ``name:tag@sha256:...`` is available locally.

    An image loaded from a tar saved by digest has no tag; with Docker's
    containerd image store its ID is the pinned digest, and builds find it.
    """
    if _image_ids(ref) is not None:
        return True
    digest = ref.rpartition("@")[2]
    found = _image_ids(digest) if digest.startswith("sha256:") else None
    return found is not None and found[0] == digest


def cmd_save_base() -> int:
    if not _docker_ready():
        return 1
    ref = base_image()
    if not ref or not _base_present(ref):
        print(f"error: base image {ref} is not present; pull it first "
              f"(docker pull {ref})", file=sys.stderr)
        return 1
    # Save by tag when the tag is the pinned image, so `docker load` restores
    # the tag too; else by digest.
    name, _, digest = ref.partition("@")
    found = _image_ids(name)
    repo = name.rsplit(":", 1)[0] if ":" in name.rsplit("/", 1)[-1] else name
    source = name if found and (found[0] == digest or f"{repo}@{digest}" in found[1]) else ref
    BASE_TAR.parent.mkdir(exist_ok=True)
    code = _docker(["save", "-o", str(BASE_TAR), source])
    if code == 0:
        print(f"saved {source} ({digest}) to {BASE_TAR.relative_to(ROOT).as_posix()} "
              f"({BASE_TAR.stat().st_size / 1e6:.1f} MB)")
    return code


def cmd_load_base() -> int:
    if not _docker_ready():
        return 1
    if not BASE_TAR.is_file():
        print(f"error: {BASE_TAR.relative_to(ROOT).as_posix()} does not exist; run "
              "save-base on a machine that has the image", file=sys.stderr)
        return 1
    code = _docker(["load", "-i", str(BASE_TAR)])
    ref = base_image()
    if code == 0 and ref and not _base_present(ref):
        print(f"error: loaded, but {ref} is still not present", file=sys.stderr)
        return 1
    return code


# -- precheck ----------------------------------------------------------------

def cmd_precheck() -> int:
    start = time.perf_counter()
    if shutil.which("git") is None:
        print("error: git is not installed", file=sys.stderr)
        return 1
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace").stdout.splitlines()
    changed = [line for line in status if line and not line.startswith("??")]
    untracked = [line for line in status if line.startswith("??")]
    if changed:
        print(f"WARNING: precheck tests HEAD, not your working tree: {len(changed)} "
              "uncommitted change(s) are NOT checked. Commit first to include them.")
    if untracked:
        print(f"note: {len(untracked)} untracked path(s) are not in the clean clone")
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()

    tmp = tempfile.mkdtemp(prefix="salvage-precheck-")
    clone = os.path.join(tmp, "repo")
    logs = os.path.join(tmp, "logs")
    os.makedirs(logs)
    results: list[tuple[str, bool, float, str]] = []

    def step(name: str, func) -> None:
        t0 = time.perf_counter()
        print(f"--- {len(results) + 1}. {name}", flush=True)
        try:
            ok, detail = func()
        except Exception as exc:  # noqa: BLE001 - a broken step is a FAIL, not a stop
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        took = time.perf_counter() - t0
        results.append((name, ok, took, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({took:.1f} s)"
              + (f"  {detail}" if detail else ""), flush=True)

    def logged(cmd: list[str], name: str) -> tuple[bool, str]:
        """Run ``cmd`` in the clone with its output in a log file."""
        log = os.path.join(logs, f"{len(results) + 1}-{name}.log")
        with open(log, "w", encoding="utf-8", errors="replace") as fh:
            try:
                code = subprocess.call(cmd, cwd=clone, stdout=fh, stderr=subprocess.STDOUT,
                                       timeout=DOCKER_RUN_TIMEOUT)
            except subprocess.TimeoutExpired:
                code = 124
        if code != 0:
            with open(log, encoding="utf-8", errors="replace") as fh:
                tail = fh.read().splitlines()[-15:]
            print("\n".join(f"    | {line}" for line in tail))
        return code == 0, f"exit {code}" + ("" if code == 0 else f", log: {log}")

    def task(*args: str, name: str) -> tuple[bool, str]:
        """The CLONE's task.py, so HEAD's code is what gets checked."""
        return logged([sys.executable, os.path.join(clone, "tools", "task.py"), *args], name)

    keep = False
    failed = 0
    try:
        proc = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), clone],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"error: git clone failed: {proc.stderr.strip()}", file=sys.stderr)
            keep, failed = True, 1
            return 1
        print(f"precheck: HEAD {head}, clean clone in {clone}")
        # samples/ is organizer data and may not be committed: then use the
        # working tree's copy (read only).
        samples = os.path.join(clone, "samples")
        if not os.path.isdir(samples) and (ROOT / "samples").is_dir():
            samples = str(ROOT / "samples")
            print(f"note: samples/ is not in HEAD; using the working tree's {samples}")
        have_samples = os.path.isdir(samples)

        step("test", lambda: task("test", name="test"))
        step("conform (full)", lambda: task(
            "conform", *(["--samples-root", samples] if have_samples else []), name="conform"))
        step("docs --check", lambda: task("docs", "--check", name="docs"))
        step("lint-docker", lambda: task("lint-docker", name="lint-docker"))

        def build() -> tuple[bool, str]:
            if not _docker_ready():
                return False, "docker is not available"
            ref = base_image()
            if not ref or not _base_present(ref):
                return False, (f"base image {ref} is not present: run save-base/load-base "
                               "or pull it")
            return logged(["docker", "build", "--no-cache", "--network", "none",
                           "-t", IMAGE, clone], "build")

        step("build --no-cache --network none", build)
        built = results[-1][1]
        stale = (False, "not run: the build failed, and the existing salvage:dev image "
                        "may not be HEAD")

        def run_corpus() -> tuple[bool, str]:
            if not built:
                return stale
            inp, out = os.path.join(tmp, "corpus-in"), os.path.join(tmp, "corpus-out")
            os.makedirs(inp)
            if have_samples:
                shutil.copytree(samples, os.path.join(inp, "samples"))
            for case in sorted(Path(clone, "tests").glob("*/cases/*")):
                if case.is_file() and not case.name.endswith(".expected.json"):
                    dest = Path(inp, "golden", case.parent.parent.name, case.name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(case, dest)
            n = sum(len(files) for _, _, files in os.walk(inp))
            code = docker_run(inp, out, capture_output=True)
            if code != 0:
                return False, f"docker run exited {code}"
            ok, detail = task("check-outputs", inp, out, name="check-outputs")
            return ok, f"{n} inputs, exit 0; check-outputs {detail}"

        step("docker run on samples/ + golden inputs", run_corpus)
        step("docker-smoke", lambda: task("docker-smoke", name="docker-smoke") if built
             else stale)
        failed = sum(1 for _, ok, _, _ in results if not ok)
        keep = failed > 0
    finally:
        total = time.perf_counter() - start
        if results:
            print(f"\nprecheck summary (HEAD {head})")
            print("| # | step | result | seconds |\n|---|------|--------|--------:|")
            for i, (name, ok, took, _) in enumerate(results, 1):
                print(f"| {i} | {name} | {'PASS' if ok else 'FAIL'} | {took:.1f} |")
            print(f"precheck: {len(results) - failed} PASS, {failed} FAIL; "
                  f"total time {total:.1f} s")
        if keep:
            print(f"clone and logs kept for inspection in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


# -- golden ------------------------------------------------------------------

def cmd_golden(fmt: str | None) -> int:
    env = _env()
    env.pop("SALVAGE_GOLDEN", None)
    if fmt:
        env["SALVAGE_GOLDEN"] = fmt
    return subprocess.call([sys.executable, "-m", "unittest", "-v",
                            "tests.test_golden.GoldenTests"], cwd=ROOT, env=env)


def cmd_golden_update(fmt: str) -> int:
    if not fmt or fmt != os.path.basename(fmt) or fmt in (".", "..") or "/" in fmt:
        print(f"error: {fmt!r} is not a format folder name", file=sys.stderr)
        return 1
    if not (ROOT / "tests" / fmt / "cases").is_dir():
        print(f"error: tests/{fmt}/cases/ does not exist; refusing", file=sys.stderr)
        return 1
    sys.path.insert(0, str(ROOT))
    from tests import golden

    status = golden.update(fmt)
    for kind in ("changed", "added", "unchanged", "not_written"):
        for name in status[kind]:
            print(f"{kind:<11} tests/{fmt}/cases/{name}")
    print(f"golden-update {fmt}: {len(status['changed'])} changed, "
          f"{len(status['added'])} added, {len(status['unchanged'])} unchanged"
          + (f", {len(status['not_written'])} NOT WRITTEN" if status["not_written"] else ""))
    print("Check every changed/added file by hand before committing it.")
    return 1 if status["not_written"] else 0


def main(argv: list[str]) -> int:
    """Run one task; return its exit code (2 for usage errors)."""
    if not argv:
        sys.stderr.write(USAGE)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "test" and not args:
        return subprocess.call(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
            cwd=ROOT)
    if cmd == "api" and not args:
        return subprocess.call([sys.executable, str(ROOT / "tools" / "api_dump.py")], cwd=ROOT)
    if cmd == "run" and len(args) == 2:
        # Run from the caller's directory so relative IN/OUT mean what they say.
        return subprocess.call([sys.executable, "-m", "salvage.cli", *args], env=_env())
    if cmd in ("build", "build-offline") and not args:
        return cmd_build(offline=cmd == "build-offline")
    if cmd == "docker-run" and len(args) == 2:
        return docker_run(*args) if _docker_ready() else 1
    if cmd == "docker-test" and not args:
        return cmd_docker_test()
    if cmd == "docker-smoke" and not args:
        return cmd_docker_smoke()
    if cmd == "golden" and len(args) <= 1:
        return cmd_golden(args[0] if args else None)
    if cmd == "golden-update" and len(args) == 1:
        return cmd_golden_update(args[0])
    if cmd == "bench" and args in ([], ["--docker"]):
        return cmd_bench(use_docker=bool(args))
    if cmd == "docs" and set(args) <= {"--check", "--strict"}:
        return subprocess.call([sys.executable, str(ROOT / "tools" / "build_docs.py"), *args],
                               cwd=ROOT)
    if cmd == "check-outputs" and len(args) == 2:
        return cmd_check_outputs(*args)
    if cmd == "lint-docker" and not args:
        return cmd_lint_docker()
    if cmd == "save-base" and not args:
        return cmd_save_base()
    if cmd == "load-base" and not args:
        return cmd_load_base()
    if cmd == "precheck" and not args:
        return cmd_precheck()
    if cmd == "conform":
        # From the caller's directory, so relative --cases-root etc. mean what they say.
        return subprocess.call([sys.executable, "-m", "tests.conformance", *args], env=_env())
    if cmd == "golden-update":
        print("error: golden-update needs exactly one FORMAT (it never updates "
              "all formats at once)", file=sys.stderr)
        return 2
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
