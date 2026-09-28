"""End-to-end: the CPU demo image boots through the droplet kit, seeds, and serves a login.

Skipped unless E2E_DEMO_IMAGE names a built demo image, for example:

    docker build --build-arg TORCH_VARIANT=cpu --build-arg WITH_SDK=false \
        --build-arg APP_VERSION=v0.0.0 -t autograde-demo:test .
    E2E_DEMO_IMAGE=autograde-demo:test pytest tests/e2e/test_demo_kit_docker.py -rs
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

IMAGE = os.getenv("E2E_DEMO_IMAGE", "")
pytestmark = pytest.mark.skipif(
    not IMAGE or shutil.which("docker") is None, reason="E2E_DEMO_IMAGE not set or no docker"
)

KIT = Path(__file__).resolve().parents[2] / "deploy" / "demo"
PORT = int(os.getenv("E2E_DEMO_PORT", "18100"))
BASE = f"http://127.0.0.1:{PORT}"
CONTAINER = "autograde_demo_console"
MAX_IMAGE_BYTES = 5 * 1024**3
MEMORY_CAP_MIB = 700


def _env_file(image: str) -> str:
    lines = (KIT / ".env.example").read_text(encoding="utf-8").splitlines()
    env = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    env.update(PALMGRADE_AUTOGRADE_IMAGE=image, WEBHOOK_SECRET=secrets.token_hex(24), DEMO_PORT=str(PORT))
    return "".join(f"{key}={value}\n" for key, value in env.items())


def _health() -> dict | None:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=4) as response:
            return json.load(response)
    except OSError:
        return None


def _compose(root: Path) -> list[str]:
    return ["docker", "compose", "--project-directory", str(root), "-f", str(root / "docker-compose.yml")]


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("autograde-demo")
    shutil.copy(KIT / "docker-compose.yml", root)
    (root / ".env").write_text(_env_file(IMAGE), encoding="utf-8")
    for sub in (
        "state/console",
        "artifacts/line-1",
        "artifacts/line-2",
        "artifacts/line-3",
        "media",
        "models",
        "engines",
    ):
        (root / sub).mkdir(parents=True)
    (root / "media.env").touch()
    compose = _compose(root)
    subprocess.run([*compose, "up", "-d"], check=True, capture_output=True, timeout=300)
    try:
        deadline = time.monotonic() + 120
        while _health() is None and time.monotonic() < deadline:
            time.sleep(2)
        yield root
    finally:
        subprocess.run([*compose, "down"], capture_output=True, timeout=120)
        shutil.rmtree(root, ignore_errors=True)


def test_boots_in_console_mode(demo_dir):
    health = _health()
    assert health is not None, "console never answered /health"
    assert health["mode"] == "console"
    assert health["status"] == "ok"


def test_seeded_demo_account_signs_in_and_sees_the_ten_trucks(demo_dir):
    seed = subprocess.run(
        [*_compose(demo_dir), "exec", "-T", "console", "python", "scripts/seed-console-demo.py", "--hari", "3"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert seed.returncode == 0, seed.stdout[-2000:] + seed.stderr[-2000:]

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    login = urllib.request.Request(
        f"{BASE}/api/console/login",
        data=json.dumps({"email": "operator@demo.autoerp.test", "sandi": "sawit2026"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert opener.open(login, timeout=10).status == 200
    trucks = json.load(opener.open(f"{BASE}/api/console/trucks", timeout=10))["items"]
    assert len(trucks) >= 10


def test_status_command_sees_the_running_demo(demo_dir):
    result = subprocess.run(
        ["bash", str(KIT / "demo-autograde.sh"), "status"],
        env={**os.environ, "DEMO_DIR": str(demo_dir), "DEMO_PORT": str(PORT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert re.search(r"Serving\s+: v", result.stdout), result.stdout


def test_image_fits_next_to_autoerp_on_the_droplet():
    size = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Size}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert int(size) < MAX_IMAGE_BYTES, f"{int(size) / 1024**3:.1f} GB"


def test_memory_cap_is_applied_and_respected(demo_dir):
    usage = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", CONTAINER],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    used, limit = (float(re.match(r"([\d.]+)", part.strip()).group(1)) for part in usage.split("/"))
    assert "MiB" in usage.split("/")[1], usage
    assert limit == MEMORY_CAP_MIB, usage
    assert used < MEMORY_CAP_MIB, usage
