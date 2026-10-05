#!/usr/bin/env python3
"""Smoke-test a built AutoGrade image before it gets its release tag (batch 4.2).

The release workflow builds the image under a temporary `candidate-*` tag, runs this
script against it on a fresh runner, and only then copies it to `vX.Y.Z` and `latest`.
An image that cannot boot is therefore never seen by a factory PC, which updates from
`latest` alone.

Checks, in order (the first failure stops the run):
  1. label     `org.opencontainers.image.version` is the expected value. The factory
               launcher reads the version from this label; without it the update is
               skipped ("image tanpa label versi").
  2. line      `src.palmgrade.main` imports (torch, ultralytics, the line app).
  3. console   `src.palmgrade.console_main` imports without pulling in torch or cv2.
  4. boot      the console starts (`APP_MODE=console`, no network) and `/health` answers
               status ok, mode console and the expected version.

The tracker check (`tests/e2e/test_image_tracker_deps.py`) runs as its own step.

Usage:
    python scripts/smoke_image.py IMAGE --version vX.Y.Z --label vX.Y.Z[-cpu]

Exit code 0 = every check passed, 1 = a check failed, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

VERSION_LABEL = "org.opencontainers.image.version"
# The console port inside the container (entrypoint.sh: APP_PORT, default 8000).
CONSOLE_PORT = 8000
BOOT_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 2.0
# One docker command (import of torch on a cold runner included) must not hang the job.
COMMAND_TIMEOUT_S = 600
LOG_TAIL_LINES = 60

IMPORT_LINE = "import src.palmgrade.main"
# Every file named in the image's own fingerprint list matches it (factory launcher check).
CEK_SIDIK = (
    "import hashlib, json; b = json.load(open('/app/.sidik-image.json'))['berkas']; "
    "beda = [p for p, s in b.items() if hashlib.sha256(open(p, 'rb').read()).hexdigest() != s]; "
    "assert len(b) > 50 and not beda, ('fingerprint list', len(b), beda[:5])"
)
IMPORT_CONSOLE = (
    "import sys, src.palmgrade.console_main\n"
    "berat = sorted(m for m in ('torch', 'cv2', 'ultralytics') if m in sys.modules)\n"
    "assert not berat, 'console imported ' + ', '.join(berat)\n"
)
READ_HEALTH = (
    "import urllib.request\n"
    f"print(urllib.request.urlopen('http://127.0.0.1:{CONSOLE_PORT}/health', timeout=4).read().decode())\n"
)


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], Result]


class SmokeFailed(Exception):
    """A check failed; the message says which and why."""


# Exit code reported for a docker command that ran past COMMAND_TIMEOUT_S (as `timeout(1)`).
EXIT_TIMEOUT = 124


def run_docker(args: Sequence[str]) -> Result:
    try:
        done = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return Result(EXIT_TIMEOUT, "", f"docker {args[0]} ran longer than {COMMAND_TIMEOUT_S} s")
    return Result(done.returncode, done.stdout, done.stderr)


def _container_name(what: str) -> str:
    # Named, so the container can be removed even when the docker CLI was killed or
    # `run -d` failed after the container was created.
    return f"autograde-smoke-{what}-{uuid.uuid4().hex[:12]}"


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-LOG_TAIL_LINES:])


def check_label(run: Runner, image: str, label: str) -> None:
    result = run(["image", "inspect", "--format", "{{json .Config.Labels}}", image])
    if result.returncode != 0:
        raise SmokeFailed(f"label: image not found locally: {_tail(result.stderr)}")
    try:
        labels = json.loads(result.stdout or "null") or {}
    except json.JSONDecodeError as exc:
        raise SmokeFailed(f"label: docker inspect returned no JSON: {exc}") from exc
    found = labels.get(VERSION_LABEL)
    if found != label:
        raise SmokeFailed(f"label: {VERSION_LABEL} is {found!r}, expected {label!r}")


def _python(run: Runner, image: str, code: str, what: str) -> None:
    name = _container_name("import")
    try:
        result = run(
            ["run", "--rm", "--name", name, "--network", "none", "--entrypoint", "python", image, "-c", code]
        )
    finally:
        run(["rm", "-f", name])
    if result.returncode != 0:
        raise SmokeFailed(f"{what}: exit {result.returncode}\n{_tail(result.stderr)}")


def check_line_import(run: Runner, image: str) -> None:
    _python(run, image, IMPORT_LINE, "line import")


def check_console_import(run: Runner, image: str) -> None:
    _python(run, image, IMPORT_CONSOLE, "console import")


def check_fingerprints(run: Runner, image: str) -> None:
    _python(run, image, CEK_SIDIK, "fingerprint list")


def _read_health(run: Runner, container: str) -> dict | None:
    result = run(["exec", container, "python", "-c", READ_HEALTH])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _still_running(run: Runner, container: str) -> bool:
    result = run(["inspect", "--format", "{{.State.Running}}", container])
    return result.returncode == 0 and result.stdout.strip() == "true"


def check_console_boot(
    run: Runner,
    image: str,
    version: str,
    *,
    timeout_s: float = BOOT_TIMEOUT_S,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    container = _container_name("console")
    try:
        started = run(
            ["run", "-d", "--name", container, "--network", "none",
             "-e", "APP_MODE=console", "-e", f"APP_PORT={CONSOLE_PORT}", image]
        )
        if started.returncode != 0:
            raise SmokeFailed(f"boot: container did not start\n{_tail(started.stderr)}")
        deadline = clock() + timeout_s
        health = _read_health(run, container)
        # A console that refuses to boot (validate_secrets, a crash at import) exits at
        # once; waiting out the whole timeout for it only delays the red job.
        while health is None and clock() < deadline and _still_running(run, container):
            sleep(interval_s)
            health = _read_health(run, container)
        if health is None:
            logs = run(["logs", container])
            reason = "stopped" if not _still_running(run, container) else f"did not answer within {timeout_s:.0f} s"
            raise SmokeFailed(f"boot: console {reason}\n{_tail(logs.stdout + logs.stderr)}")
        expected = {"status": "ok", "mode": "console", "version": version}
        wrong = {k: health.get(k) for k, v in expected.items() if health.get(k) != v}
        if wrong:
            raise SmokeFailed(f"boot: /health returned {wrong}, expected {expected}")
    finally:
        run(["rm", "-f", container])


CHECKS = ("label", "line", "console", "boot", "sidik")


def _log(line: str) -> None:
    # Flushed: stdout is a pipe in CI, and buffered lines would print after the FAIL line.
    print(line, flush=True)


def smoke(run: Runner, image: str, version: str, label: str, log: Callable[[str], None] = _log) -> None:
    steps: dict[str, Callable[[], None]] = {
        "label": lambda: check_label(run, image, label),
        "line": lambda: check_line_import(run, image),
        "console": lambda: check_console_import(run, image),
        "boot": lambda: check_console_boot(run, image, version),
        "sidik": lambda: check_fingerprints(run, image),
    }
    for name in CHECKS:
        steps[name]()
        log(f"ok   {name}")


def main(argv: Sequence[str] | None = None, run: Runner = run_docker) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", help="image reference, tag or @digest, already pulled")
    parser.add_argument("--version", required=True, help="APP_VERSION the console must report, e.g. v1.22.0")
    parser.add_argument("--label", required=True, help=f"expected {VERSION_LABEL}, e.g. v1.22.0 or v1.22.0-cpu")
    args = parser.parse_args(argv)
    try:
        smoke(run, args.image, args.version, args.label)
    except SmokeFailed as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(f"smoke passed: {args.image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
