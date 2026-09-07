"""Unit tests for APP_VERSION exposure.

The release tag is injected as APP_VERSION at deploy time (same pattern as
palmgrade-api and palmgrade-frontend). It has to reach GET /health so the
support account can read all three service versions from the browser without
SSH — see docs/superpowers/specs/2026-09-06-error-reporting-and-version-info-design.md
"""
from __future__ import annotations

from palmgrade.core.config import Settings
from palmgrade.services.health_service import HealthService


def _service(settings: Settings) -> HealthService:
    # get_health() only reads settings; the other deps are never touched.
    return HealthService(settings=settings, state=None, camera=None, outbox=None)


def test_app_version_read_from_env(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.7.0")

    assert Settings().app_version == "v1.7.0"


def test_app_version_defaults_to_unknown(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    assert Settings().app_version == "unknown"


def test_health_exposes_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.7.0")

    assert _service(Settings()).get_health()["version"] == "v1.7.0"


def test_health_exposes_unknown_when_unset(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    # "unknown" rather than omitting the field: a missing version is
    # indistinguishable from an old image that never had one.
    assert _service(Settings()).get_health()["version"] == "unknown"
