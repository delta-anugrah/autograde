"""`DevService.version()` — kartu Versi & Lisensi di tab Support.

Yang dijaga di sini bukan aritmetika tanggal (itu `test_license_summary.py`), tapi
tiga hal yang cuma ada di lapisan service:

1. konsol memverifikasi tokennya SENDIRI, tidak bertanya ke line kamera;
2. lisensi yang rusak tidak boleh menjatuhkan layar — justru layar itu yang harus
   menjelaskan kenapa kamera berhenti;
3. rahasia tidak pernah ikut keluar di jawaban ini.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from palmgrade.license.manager import LicenseManager
from palmgrade.license.summary import SEVERITY_BLOCKED, SEVERITY_NONE, SEVERITY_WARNING
from palmgrade.services.dev_service import DevService

SECONDS_PER_DAY = 86_400
COMPANY = "PT Sawit Rambang Lestari"


@dataclass
class FakeSettings:
    """Cuma field yang dibaca `version()`. Settings sungguhan menyeret seluruh env."""

    app_version: str = "v1.9.0"
    machine_id: str = "11111111-1111-1111-1111-111111111111"
    environment: str = "production"
    lic_enabled: bool = True
    lic_token: str = "dummy"
    # Sengaja ada di sini: test di bawah membuktikan nilai ini TIDAK ikut keluar.
    webhook_secret: str = "rahasia-yang-tidak-boleh-bocor"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _manager_for(expires_in_days: float, *, grace_days: int = 60, warning_days: int = 30):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    now = int(time.time())
    expires_at = now + int(expires_in_days * SECONDS_PER_DAY)
    payload = {
        "company_id": COMPANY,
        "company_name": COMPANY,
        "status": "ACTIVE",
        "iat": now,
        "nbf": now,
        "license_expires_at": expires_at,
        "grace_days_after_expiry": grace_days,
        "warning_days_before_expiry": warning_days,
        "exp": expires_at + grace_days * SECONDS_PER_DAY,
        "server_time": now,
        "nonce": "n" * 32,
        "kid": "v1",
    }
    header = _b64(json.dumps({"alg": "EdDSA", "typ": "JWT", "kid": "v1"}).encode())
    body = _b64(json.dumps(payload).encode())
    token = f"{header}.{body}.{_b64(key.sign(f'{header}.{body}'.encode()))}"
    return LicenseManager(pub, None, token)


class ManagerYangMeledak:
    """Lisensi yang melempar saat dibaca — misalnya SQLite ratchet rusak."""

    async def get_effective_license(self):
        raise RuntimeError("database lisensi rusak")


def _service(manager, settings: FakeSettings | None = None) -> DevService:
    # `log_store=None`: `version()` tidak menyentuhnya sama sekali, dan LogStore
    # sungguhan akan membuat berkas SQLite di mesin developer.
    return DevService(
        None, settings=settings or FakeSettings(), license_manager=manager
    )


def test_versi_membawa_tanggal_langganan():
    out = asyncio.run(_service(_manager_for(180)).version())

    assert out["versi"] == "v1.9.0"
    assert out["lisensi"]["severity"] == SEVERITY_NONE
    assert out["lisensi"]["sisa_hari"] == 180
    assert out["lisensi"]["perusahaan"] == COMPANY
    assert out["lisensi"]["aktif_sampai"] > time.time()


def test_versi_membawa_peringatan_saat_mendekati_habis():
    out = asyncio.run(_service(_manager_for(10)).version())

    assert out["lisensi"]["severity"] == SEVERITY_WARNING
    assert out["lisensi"]["sisa_hari"] == 10


def test_lisensi_yang_melempar_tidak_menjatuhkan_layar():
    """Justru layar ini yang harus menjelaskan kenapa kamera berhenti, jadi dia
    tidak boleh ikut mati bersama lisensinya."""
    out = asyncio.run(_service(ManagerYangMeledak()).version())

    assert out["lisensi"]["severity"] == SEVERITY_BLOCKED
    assert out["versi"] == "v1.9.0"


def test_tanpa_manager_dilaporkan_berhenti_bukan_sehat():
    """Manager None dengan fitur menyala berarti kunci publiknya gagal dimuat —
    kamera pasti berhenti, jadi layar harus bilang berhenti."""
    out = asyncio.run(_service(None).version())

    assert out["lisensi"]["severity"] == SEVERITY_BLOCKED


def test_fitur_mati_tidak_memunculkan_peringatan():
    settings = FakeSettings(lic_enabled=False, lic_token="")
    out = asyncio.run(_service(None, settings).version())

    assert out["lisensi"]["severity"] == SEVERITY_NONE
    assert out["lisensi"]["aktif"] is False


def test_jawaban_tidak_pernah_membawa_rahasia():
    """Layar ini dibaca lewat AnyDesk. Token, secret, dan hash tidak boleh ikut."""
    settings = FakeSettings(lic_token="token.rahasia.jangan-bocor")
    out = asyncio.run(_service(_manager_for(180), settings).version())

    teks = json.dumps(out)
    assert "token.rahasia.jangan-bocor" not in teks
    assert settings.webhook_secret not in teks
    # Yang boleh: bendera terpasang atau tidak, bukan isinya.
    assert out["lisensi"]["token_terpasang"] is True


def test_konsol_tidak_bertanya_ke_line_untuk_lisensi():
    """Kalau ini pernah berubah jadi memanggil line, lisensi akan terlihat rusak
    setiap kali satu kamera sedang restart."""

    class LineClientYangGagal:
        async def health_detail(self, line):
            raise AssertionError("version() tidak boleh menyentuh line")

    service = DevService(
        None,
        settings=FakeSettings(),
        license_manager=_manager_for(180),
        line_client=LineClientYangGagal(),
        lines=(),
    )

    out = asyncio.run(service.version())
    assert out["lisensi"]["severity"] == SEVERITY_NONE
