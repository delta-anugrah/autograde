"""Unit tests untuk `license_summary` — apa yang dilihat operator saat langganan menipis.

Kenapa ini diuji terpisah dari `LicenseManager`: manager memutuskan apakah pabrik
boleh grading, summary memutuskan apa yang TERTULIS di layar. Yang kedua pernah
tidak ada sama sekali — kamera berhenti dan konsol diam, jadi operator melihat line
mati tanpa satu pun penjelasan. Test ini mengunci penjelasan itu.

Payload dibuat sungguhan lalu ditandatangani Ed25519 asli, bukan objek palsu: bentuk
`EffectiveLicense` yang salah akan lolos mock tapi tidak lolos manager.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from palmgrade.license.manager import LicenseManager
from palmgrade.license.summary import (
    SEVERITY_BLOCKED,
    SEVERITY_GRACE,
    SEVERITY_NONE,
    SEVERITY_WARNING,
    license_summary,
)
from palmgrade.license.types import EffectiveLicense

SECONDS_PER_DAY = 86_400
COMPANY = "PT Sawit Rambang Lestari"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(key: Ed25519PrivateKey, payload: dict) -> str:
    header = _b64(json.dumps({"alg": "EdDSA", "typ": "JWT", "kid": payload["kid"]}).encode())
    body = _b64(json.dumps(payload).encode())
    return f"{header}.{body}.{_b64(key.sign(f'{header}.{body}'.encode()))}"


def _payload(*, expires_in_days: float, grace_days: int = 60, warning_days: int = 30,
             status: str = "ACTIVE", now: int | None = None) -> dict:
    current = int(time.time()) if now is None else now
    expires_at = current + int(expires_in_days * SECONDS_PER_DAY)
    return {
        "company_id": COMPANY,
        "company_name": COMPANY,
        "status": status,
        "iat": current,
        "nbf": current,
        "license_expires_at": expires_at,
        "grace_days_after_expiry": grace_days,
        "warning_days_before_expiry": warning_days,
        "exp": expires_at + grace_days * SECONDS_PER_DAY,
        "server_time": current,
        "nonce": "n" * 32,
        "kid": "v1",
    }


def _effective(payload: dict) -> EffectiveLicense:
    """Lewat manager sungguhan, supaya state machine-nya yang memutuskan."""
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    manager = LicenseManager(pub, None, _token(key, payload))
    return asyncio.run(manager.get_effective_license())


def _summary(payload: dict, **kwargs) -> dict:
    return license_summary(
        _effective(payload), enabled=True, token_installed=True, **kwargs
    )


# ----------------------------------------------------------------- tahap sehat


def test_langganan_masih_lama_tidak_memunculkan_peringatan():
    block = _summary(_payload(expires_in_days=180))

    assert block["severity"] == SEVERITY_NONE
    assert block["status"] == "ACTIVE"
    assert block["sisa_hari"] == 180
    assert block["perusahaan"] == COMPANY


def test_masuk_jendela_peringatan_memunculkan_warning():
    block = _summary(_payload(expires_in_days=10, warning_days=30))

    assert block["severity"] == SEVERITY_WARNING
    assert block["status"] == "ACTIVE"
    assert block["sisa_hari"] == 10


def test_tepat_di_tepi_jendela_masih_warning():
    """Batasnya inklusif di manager; summary tidak boleh menggesernya sendiri."""
    block = _summary(_payload(expires_in_days=29.9, warning_days=30))

    assert block["severity"] == SEVERITY_WARNING


def test_sehari_sebelum_jendela_belum_warning():
    block = _summary(_payload(expires_in_days=31, warning_days=30))

    assert block["severity"] == SEVERITY_NONE


# ---------------------------------------------------------------------- grace


def test_masa_tenggang_menghitung_sisa_sampai_grading_berhenti():
    """Bukan berapa hari sudah lewat — operator butuh tahu sisa waktunya."""
    block = _summary(_payload(expires_in_days=-5, grace_days=60))

    assert block["severity"] == SEVERITY_GRACE
    assert block["status"] == "GRACE"
    assert block["sisa_hari"] == 55


def test_tenggang_hampir_habis_melaporkan_satu_hari_bukan_nol():
    """Pembulatan ke atas: 0,4 hari tersisa adalah "1 hari", bukan "0 hari"
    yang terbaca seperti sudah mati padahal kamera masih jalan."""
    block = _summary(_payload(expires_in_days=-59.6, grace_days=60))

    assert block["severity"] == SEVERITY_GRACE
    assert block["sisa_hari"] == 1


# -------------------------------------------------------------------- berhenti


def test_tenggang_habis_menandai_grading_berhenti():
    block = _summary(_payload(expires_in_days=-90, grace_days=60))

    assert block["severity"] == SEVERITY_BLOCKED
    assert block["status"] == "EXPIRED"
    assert block["sisa_hari"] == 0


def test_tanpa_tenggang_lewat_sehari_langsung_berhenti():
    block = _summary(_payload(expires_in_days=-1, grace_days=0))

    assert block["severity"] == SEVERITY_BLOCKED


def test_dibatalkan_berhenti_walau_tanggalnya_masih_jauh():
    """CANCEL itu tombol matikan; tanggal tidak boleh mengalahkannya."""
    block = _summary(_payload(expires_in_days=180, status="CANCEL"))

    assert block["severity"] == SEVERITY_BLOCKED
    assert block["status"] == "EXPIRED"


def test_token_tidak_bisa_dibaca_dilaporkan_sebagai_berhenti():
    """Fail closed. Token rusak menghentikan kamera, jadi layar harus bilang
    berhenti — bukan diam seolah semuanya baik."""
    effective = EffectiveLicense(
        status="EXPIRED", reason="invalid token", payload=None, warning=None
    )

    block = license_summary(effective, enabled=True, token_installed=True)

    assert block["severity"] == SEVERITY_BLOCKED
    assert block["aktif_sampai"] is None
    assert block["perusahaan"] is None


def test_belum_ada_token_dilaporkan_sebagai_berhenti():
    effective = EffectiveLicense(status="EXPIRED", reason="no token", payload=None, warning=None)

    block = license_summary(effective, enabled=True, token_installed=False)

    assert block["severity"] == SEVERITY_BLOCKED
    assert block["token_terpasang"] is False


# ------------------------------------------------------------------ fitur mati


def test_fitur_mati_tidak_memunculkan_apa_pun():
    """PC dev dan pabrik yang belum dilisensi. Gerbangnya tidak dipasang, jadi
    banner akan memperingatkan aturan yang tidak sedang ditegakkan."""
    effective = EffectiveLicense(status="EXPIRED", reason="no token", payload=None, warning=None)

    block = license_summary(effective, enabled=False, token_installed=False)

    assert block["severity"] == SEVERITY_NONE
    assert block["aktif"] is False
    assert block["aktif_sampai"] is None
    assert block["sisa_hari"] is None


def test_fitur_mati_tidak_membocorkan_tanggal_token_lama():
    """Token lama yang masih nyangkut di `.env` tidak boleh muncul di layar
    saat gerbangnya dimatikan — itu tanggal yang tidak berlaku lagi."""
    block = license_summary(
        _effective(_payload(expires_in_days=180)), enabled=False, token_installed=True
    )

    assert block["severity"] == SEVERITY_NONE
    assert block["aktif_sampai"] is None


# --------------------------------------------------------------------- tanggal


def test_tanggal_dibawa_apa_adanya_dari_token():
    """Layar menampilkan tanggal; summary tidak boleh menghitung ulang."""
    payload = _payload(expires_in_days=45, grace_days=60)
    block = _summary(payload)

    assert block["aktif_sampai"] == payload["license_expires_at"]
    assert block["tenggang_sampai"] == payload["exp"]


def test_sisa_hari_dihitung_dari_jam_yang_disuntik_bukan_jam_mesin():
    """`now` yang diberikan harus dipakai, bukan `time.time()`.

    Jamnya digeser relatif terhadap sekarang, bukan dipatok ke satu epoch tetap:
    `LicenseManager` selalu membaca jam sungguhan (itu bagian dari anti-rollback),
    jadi token berstempel 2023 akan sudah mati sebelum summary sempat dipanggil.
    """
    real_now = int(time.time())
    payload = _payload(expires_in_days=10, now=real_now)
    effective = _effective(payload)

    # Maju 5 hari: sisa harus ikut menyusut jadi 5.
    block = license_summary(
        effective, enabled=True, token_installed=True, now=real_now + 5 * SECONDS_PER_DAY
    )

    assert block["sisa_hari"] == 5
