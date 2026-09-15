"""Unit tests binding docker-compose to the settings the console actually reads.

A setting added to `Settings` but not forwarded by the `console` service is
invisible in the container and silently falls back to its default. That is how
ERP_COMPANY shipped unreachable: the code, `.env.example` and the docs all had
it, only compose did not. Reading the two files against each other is the only
check that catches it.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PY = REPO_ROOT / "src" / "palmgrade" / "core" / "config.py"
COMPOSE = REPO_ROOT / "docker-compose.yml"

# Settings read by the console. Line-only settings (cameras, PLC, uploads) are
# deliberately out of scope: the console service has no business carrying them.
CONSOLE_PREFIXES = ("ERP_", "CONSOLE_", "LOG_")


def _settings_env_names() -> set[str]:
    """Env vars `Settings` reads, as spelled in config.py."""
    source = CONFIG_PY.read_text(encoding="utf-8")
    names = set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', source))
    return {name for name in names if name.startswith(CONSOLE_PREFIXES)}


def _compose_env_names(service: str) -> set[str]:
    """Env vars a compose service declares, list form (`- NAME=${NAME}`)."""
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    entries = compose["services"][service]["environment"]
    return {entry.split("=", 1)[0] for entry in entries}


def test_console_service_forwards_every_console_setting():
    missing = _settings_env_names() - _compose_env_names("console")

    assert not missing, f"read by Settings but not forwarded by compose: {sorted(missing)}"


def test_settings_env_names_were_actually_found():
    # Guard against the regex silently matching nothing, which would make the
    # test above pass for the wrong reason.
    assert "ERP_URL" in _settings_env_names()
