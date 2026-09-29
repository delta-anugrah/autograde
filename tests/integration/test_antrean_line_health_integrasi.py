"""`/health/detail` dan penjaga `autograde reset-data` di host, dengan antrean SUNGGUHAN.

Host membaca `outbox_pending` dengan sed (`docs/runbooks/files/autograde.sh` di repo
sawit, `antrean_tertunda`):

    sed -n 's/.*"outbox_pending":[[:space:]]*\\([0-9]\\{1,\\}\\).*/\\1/p'

Angka = boleh dijumlah; tidak cocok (null) = "tidak diketahui", reset ditolak.
Sejak batch 2.4 baris yang dulu menyerah ikut terhitung: dulu mereka cuma ada di
`outbox_failed`, yang tidak dibaca penjaga itu, jadi reset-data membuangnya.
"""
from __future__ import annotations

import re
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.services.health_service import HealthService

_SED_PENJAGA = re.compile(r'.*"outbox_pending":\s*([0-9]+).*', re.S)


def _angka_penjaga(ringkasan: dict) -> str:
    body = HealthDetailSchema(
        status="ok", environment="production", camera_type="hikrobot", camera_connected=True,
        gpu_available=True, gpu_device=None, machine_id="m", workers=[], **ringkasan,
    ).model_dump_json()
    cocok = _SED_PENJAGA.fullmatch(body)
    return cocok.group(1) if cocok else "?"


def _health(tmp_path, store: OutboxStore) -> HealthService:
    settings = replace(Settings(), repo_root=tmp_path)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return HealthService(settings=settings, state=None, camera=None, outbox=store, folder_db=settings.state_dir)


def test_baris_yang_dulu_menyerah_menahan_reset_data(tmp_path):
    jalur = tmp_path / "state" / "outbox.db"
    lama = OutboxStore(jalur)
    lama.add_event("e1", "m", {"event_id": "e1"})
    lama.add_event("e2", "m", {"event_id": "e2"})
    with lama._db:  # yang ditulis versi lama pada percobaan ke-50
        lama._db.execute("UPDATE outbox_events SET status = 'failed'")
    lama._db.close()

    ringkasan = _health(tmp_path, OutboxStore(jalur)).ringkasan_outbox()

    assert ringkasan == {"outbox_pending": 2, "outbox_failed": 0, "outbox_lama_tertinggal": False}
    assert _angka_penjaga(ringkasan) == "2"


def test_antrean_kosong_terbaca_nol(tmp_path):
    ringkasan = _health(tmp_path, OutboxStore(tmp_path / "state" / "outbox.db")).ringkasan_outbox()

    assert _angka_penjaga(ringkasan) == "0"


def test_sisa_antrean_lama_tetap_tidak_diketahui(tmp_path):
    health = _health(tmp_path, OutboxStore(tmp_path / "state" / "outbox.db"))
    (health.settings.artifacts_dir / "outbox.db").write_bytes(b"sisa")

    assert _angka_penjaga(health.ringkasan_outbox()) == "?"
