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


def test_tanpa_internal_secret_memakai_webhook_secret(monkeypatch):
    """PC Lampung hari ini: .env tanpa INTERNAL_SECRET harus tetap jalan."""
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    s = Settings()
    assert s.internal_secret == s.webhook_secret == "kunci-palsu-w"
    assert s.internal_secret_terpisah is False


@pytest.mark.parametrize("kosong", ["", "   "])
def test_internal_secret_kosong_dianggap_tidak_diisi(monkeypatch, kosong):
    """Compose meneruskan `${INTERNAL_SECRET:-}`: tidak diisi sampai sebagai string kosong."""
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.setenv("INTERNAL_SECRET", kosong)
    assert Settings().internal_secret == "kunci-palsu-w"


def test_internal_secret_diisi_terpisah_dan_dipangkas(monkeypatch):
    """Dipangkas: klien HTTP membuang spasi di ujung nilai header, jadi secret
    berspasi akan selalu ditolak line walau .env-nya sama persis."""
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.setenv("INTERNAL_SECRET", " kunci-palsu-i ")
    s = Settings()
    assert s.internal_secret == "kunci-palsu-i"
    assert s.webhook_secret == "kunci-palsu-w"
    assert s.internal_secret_terpisah is True


def test_internal_secret_sama_dengan_webhook_secret_bukan_terpisah(monkeypatch):
    """Teknisi boleh mengisi INTERNAL_SECRET dengan nilai yang sama persis dengan
    WEBHOOK_SECRET (tidak salah, cuma tidak menambah proteksi). Task 6
    (validate_secrets) memakai `internal_secret_terpisah` untuk memutuskan kapan
    memberi peringatan, jadi kasus ini harus tetap False, bukan True."""
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-sama")
    monkeypatch.setenv("INTERNAL_SECRET", "kunci-sama")
    s = Settings()
    assert s.internal_secret == s.webhook_secret == "kunci-sama"
    assert s.internal_secret_terpisah is False


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


def test_produksi_internal_secret_bawaan_ditolak(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.setenv("INTERNAL_SECRET", _DEFAULT_WEBHOOK_SECRET)
    with pytest.raises(RuntimeError, match="INTERNAL_SECRET"):
        Settings().validate_secrets()


def test_produksi_webhook_secret_kosong_ditolak(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "")
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        Settings().validate_secrets()


def test_produksi_tanpa_internal_secret_cuma_peringatan(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    with caplog.at_level("WARNING"):
        Settings().validate_secrets()
    assert any("INTERNAL_SECRET" in r.getMessage() for r in caplog.records)


def test_validate_secrets_tidak_membawa_peringatan_khusus_line(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "kunci-palsu-w")
    monkeypatch.setenv("INTERNAL_SECRET", "kunci-palsu-i")
    monkeypatch.delenv("R2_BUCKET", raising=False)
    with caplog.at_level("WARNING"):
        Settings().validate_secrets()
    assert not any("R2_BUCKET" in r.getMessage() for r in caplog.records)


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
