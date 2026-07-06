"""Unit tests for production secret fail-fast (B3).

WEBHOOK_SECRET secures both directions between vision and palmgrade-api. If .env
is not filled on the production PC, the service used to start normally with the
public default 'supersecret123' (only a log warning). Now it must refuse to
start when APP_ENV=production and the secret is still the default.
"""
from __future__ import annotations

import pytest

from palmgrade.core.config import _DEFAULT_WEBHOOK_SECRET, Settings


def test_production_with_default_secret_raises(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", _DEFAULT_WEBHOOK_SECRET)
    settings = Settings()

    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        settings.validate_for_runtime()


def test_production_with_real_secret_passes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "a-real-strong-secret")
    settings = Settings()

    settings.validate_for_runtime()  # must not raise


def test_development_with_default_secret_passes(monkeypatch):
    # Dev / opencv flow must keep working with the default secret.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WEBHOOK_SECRET", _DEFAULT_WEBHOOK_SECRET)
    settings = Settings()

    settings.validate_for_runtime()  # must not raise


def test_internal_secret_mirrors_webhook_secret(monkeypatch):
    # Both directions share one secret; internal_secret must equal webhook_secret
    # so api→vision (x-internal-secret) and vision→api (x-webhook-secret) stay in
    # sync. Guards the contract with palmgrade-api.
    monkeypatch.setenv("WEBHOOK_SECRET", "some-secret")
    settings = Settings()

    assert settings.internal_secret == settings.webhook_secret == "some-secret"
