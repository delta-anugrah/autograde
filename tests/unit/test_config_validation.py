"""Unit tests for production secret fail-fast (B3).

WEBHOOK_SECRET secures both directions between vision and palmgrade-api. If .env
is not filled on the production PC, the service used to start normally with the
public default 'supersecret123' (only a log warning). Now it must refuse to
start when APP_ENV=production and the secret is still the default.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from palmgrade.core.config import (
    _DEFAULT_WEBHOOK_SECRET,
    LICENSE_PUBLIC_KEY_BAKED,
    Settings,
)


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


def test_batch_upload_defaults(monkeypatch):
    for var in ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_PUBLIC_URL", "UPLOAD_API_URL",
                "UPLOAD_MAX_ITEMS_PER_TICK", "UPLOAD_RETENTION_DAYS"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.r2_bucket == ""
    assert s.upload_max_items_per_tick == 2000
    assert s.upload_retention_days == 7
    # var scheduler lama sudah dihapus dari Settings
    assert not hasattr(s, "upload_hour")
    assert not hasattr(s, "destination_upload")


def test_upload_events_url_built_from_upload_api_url(monkeypatch):
    monkeypatch.setenv("UPLOAD_API_URL", "https://api.palmgrade.ai/")
    s = Settings()
    assert s.upload_api_url == "https://api.palmgrade.ai"  # trailing slash dibuang
    assert s.upload_events_url == "https://api.palmgrade.ai/api/v1/internal/vision/events"


def test_production_empty_r2_bucket_warns_not_crash(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "bukan-default-123")
    monkeypatch.delenv("R2_BUCKET", raising=False)
    s = Settings()
    with caplog.at_level("WARNING"):
        s.validate_for_runtime()  # TIDAK raise
    assert any("R2_BUCKET" in r.message for r in caplog.records)


def test_pubkey_falls_back_to_baked_in_key(monkeypatch):
    """PC pabrik tanpa LICENSE_PUBLIC_KEY di .env tetap punya kunci.

    Ini keadaan PC Lampung berbulan-bulan: `vision/.env` tanpa `LICENSE_*` sama
    sekali, jadi guard-nya tidak pernah memeriksa apa pun.
    """
    monkeypatch.delenv("LICENSE_PUBLIC_KEY", raising=False)

    assert Settings().lic_pubkey_pem == LICENSE_PUBLIC_KEY_BAKED


def test_baked_in_key_is_a_real_ed25519_public_key():
    key = serialization.load_pem_public_key(
        LICENSE_PUBLIC_KEY_BAKED.replace("\\n", "\n").encode()
    )

    assert isinstance(key, ed25519.Ed25519PublicKey)


def test_env_pubkey_wins_over_baked_in(monkeypatch):
    """Laptop developer harus tetap bisa pakai keypair DEV-nya sendiri."""
    monkeypatch.setenv("LICENSE_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\\nDEV\\n-----END PUBLIC KEY-----")

    assert Settings().lic_pubkey_pem == (
        "-----BEGIN PUBLIC KEY-----\nDEV\n-----END PUBLIC KEY-----"
    )
