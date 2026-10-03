"""The droplet kit for the internet demo console (`deploy/demo`).

The demo shares its disk and RAM with AutoERP production, so its limits are pinned here, and
it must forward every setting the factory console gets or a later release boots half-configured.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from test_console_compose_env import COMPOSE_PROD, _compose_env_names

KIT = Path(__file__).resolve().parents[2] / "deploy" / "demo"
COMPOSE = KIT / "docker-compose.yml"
ENV_EXAMPLE = KIT / ".env.example"
SCRIPT_TESTS = KIT / "demo-autograde.test.sh"


def _console() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["console"]


def _environment() -> dict:
    return dict(item.split("=", 1) for item in _console()["environment"])


def _env_example() -> dict:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    pairs = [line.split("=", 1) for line in lines if line.strip() and not line.startswith("#")]
    return {key.strip(): value.strip() for key, value in pairs}


def test_runs_the_console_on_loopback_only():
    console = _console()
    assert _environment()["APP_MODE"] == "console"
    assert _environment()["APP_PORT"] == "8100"
    assert console["ports"] == ["127.0.0.1:${DEMO_PORT:-8100}:8100"]
    assert "network_mode" not in console


def test_memory_and_cpu_are_capped():
    """No swap on the droplet: an uncapped demo would take MariaDB down with it."""
    console = _console()
    assert console["mem_limit"] == "700m"
    assert float(console["cpus"]) <= 1.0


def test_forwards_every_setting_the_factory_console_gets():
    missing = _compose_env_names("console", COMPOSE_PROD) - _compose_env_names("console", COMPOSE)
    assert not missing, f"factory console gets these, demo does not: {sorted(missing)}"


def test_never_offers_update_now():
    """The demo upgrades with demo-autograde; no watcher answers a request.json there."""
    assert _environment()["UPDATE_DIR"] == "/app/update"
    assert not [v for v in _console()["volumes"] if v.split(":")[1:2] == ["/app/update"]]


def test_image_and_name_come_from_the_kit():
    console = _console()
    assert console["image"] == "${PALMGRADE_AUTOGRADE_IMAGE}"
    assert console["container_name"] == "autograde_demo_console"
    assert console["restart"] == "unless-stopped"


def test_console_data_lives_on_the_host():
    assert "./state/console:/app/state" in _console()["volumes"]


def test_seeder_can_write_the_demo_photos():
    """No camera lines here: the seeder writes the photos, so artifacts cannot be read-only."""
    volumes = _console()["volumes"]
    for line in ("line-1", "line-2", "line-3"):
        assert f"./artifacts/{line}:/app/artifacts/{line}" in volumes


def test_env_example_defines_every_variable_compose_reads():
    read = set(re.findall(r"\$\{([A-Z0-9_]+)\}", COMPOSE.read_text(encoding="utf-8")))
    assert read - set(_env_example()) == set()


def test_env_example_is_safe_to_expose_to_the_internet():
    env = _env_example()
    assert re.fullmatch(r"ghcr\.io/delta-anugrah/autograde:v\d+\.\d+\.\d+-cpu", env["PALMGRADE_AUTOGRADE_IMAGE"])
    assert env["APP_ENV"] == "production", "production refuses to boot on a default secret"
    assert env["WEBHOOK_SECRET"] == "", "each droplet generates its own"
    assert env["ERP_ALLOWED_ROLES"] == "", "no AutoERP account may open the support screens"
    assert env["LICENSE_ENABLED"] == "false"


def test_erp_company_is_named_not_left_to_the_site_default():
    """demo.smagri.id carries three companies and defaults to the wrong one.

    Empty means AutoERP books against its default, whose cost center then belongs to another
    company: every visit is rejected with HTTP 417, and only the outbox screen shows it.
    """
    assert _env_example()["ERP_COMPANY"] == "PT Sawit Rambang Lestari"


def test_kit_never_names_the_production_site():
    for path in KIT.iterdir():
        assert "app.smagri.id" not in path.read_text(encoding="utf-8"), path.name


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_demo_autograde_script_suite_passes():
    result = subprocess.run(["bash", str(SCRIPT_TESTS)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
