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

Uses ``sys.executable``, so it works whatever the interpreter is called.
This is a dev tool: unknown commands print usage and exit with code 2;
failed checks exit with code 1.
"""

from __future__ import annotations

import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
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


def host_path(path: str | Path) -> str:
    """Absolute path in a form ``docker -v`` accepts (C:/x/y on Windows)."""
    full = os.path.abspath(path)
    return full.replace("\\", "/") if os.name == "nt" else full


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
    if cmd == "golden-update":
        print("error: golden-update needs exactly one FORMAT (it never updates "
              "all formats at once)", file=sys.stderr)
        return 2
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
