"""End to end (batch 2.4): antrean line yang dulu menyerah sampai ke konsol, dan konsol
yang mati lalu hidup lagi, dilihat dari layar support (tab Status → Antrean line).

Semua SUNGGUHAN kecuali kabel dan kamera: berkas outbox berskema versi lama,
`OutboxStore` yang membukanya, `OutboxRetryWorker`, lane ingest konsol, router
`/internal/outbox*` line, `LineClient`, dan rute layar support dengan sesi login.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest
from antrean_line_rakit import (
    KabelKonsol,
    LinePerPort,
    app_ingest,
    app_konsol,
    berkas_outbox_versi_lama,
    masuk,
    rakit_line,
)
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.kirim_antrean_line import JEDA_SAMBUNGAN_MAKS_S
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

WEBHOOK = "kunci-webhook-e2e-palsu"
INTERNAL = "kunci-internal-e2e-palsu"
TS = "2026-09-20T03:00:00+00:00"
EPOCH_TS = 1789873200.0
HARI = "2026-09-20"


class _Jam:
    def __init__(self) -> None:
        self.sekarang = 1_000.0

    def __call__(self) -> float:
        return self.sekarang

    def maju(self, detik: float) -> None:
        self.sekarang += detik


def _event(mesin: str, nomor: int) -> dict:
    return {
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mesin}:{nomor}")), "machine_id": mesin,
        "timestamp": TS, "prediction": "Acc", "ripeness_status": "ACC", "ripeness_confidence": 0.9,
        "capture_type": "auto", "image_path": f"captures/results/{HARI}/{nomor}.webp",
    }


@pytest.fixture
def pabrik(tmp_path):
    """Konsol hidup, satu line yang BELUM dinyalakan (`nyalakan()` = boot versi ini)."""
    settings = replace(
        Settings(), repo_root=tmp_path / "konsol", webhook_secret=WEBHOOK, internal_secret=INTERNAL,
        factory_tz="Asia/Jakarta", console_line_host="http://line",
    )
    konsol = ConsoleService(settings, ConsoleStore(tmp_path / "konsol.db"), line_client=None)
    kabel = KabelKonsol(app_ingest(konsol))
    jam = _Jam()
    folder = tmp_path / "line-1"
    line_1 = konsol.lines[0]

    def nyalakan():
        line = rakit_line(
            folder, internal_secret=INTERNAL, klien_konsol=kabel.klien(), jam=jam,
            backend_url="http://testserver", webhook_secret=WEBHOOK, enable_webhook=True,
        )
        pantau = PantauAntreanLine(
            LineClient(settings, transport=LinePerPort({line_1.port: line.app})), (line_1,)
        )
        layar = masuk(app_konsol(konsol.store, pantau), konsol.store, role=ROLE_SUPPORT)
        return line, layar

    return konsol, kabel, jam, folder, line_1, nyalakan


def _antrean(layar: TestClient) -> dict:
    return layar.get("/api/console/dev/antrean/line").json()["lines"]["line-1"]


def test_upgrade_janjang_yang_dulu_menyerah_sampai_tanpa_ganda(pabrik):
    """Review focus 1: keadaan Lampung. Versi lama berhenti mencoba tiga janjang sesudah
    50 kali ke api yang sudah mati; satu di antaranya sebenarnya sudah sampai ke konsol
    (jawabannya yang hilang). Sesudah upgrade: ketiganya terhitung, tidak ada yang ganda."""
    konsol, _, _, folder, line_1, nyalakan = pabrik
    events = [_event(line_1.machine_id, n) for n in range(3)]
    berkas_outbox_versi_lama(
        folder / "state" / "outbox.db", [(e["event_id"], "failed", 50, json.dumps(e)) for e in events]
    )
    sudah = TestClient(app_ingest(konsol)).post(
        "/api/v1/internal/vision/events", json=events[0], headers={"x-webhook-secret": WEBHOOK}
    )
    assert sudah.status_code == 201

    line, layar = nyalakan()
    sebelum = _antrean(layar)
    line.worker._flush_pending()
    sesudah = _antrean(layar)

    assert (sebelum["menunggu"], sebelum["tertua_at"]) == (3, EPOCH_TS)
    assert konsol.store.inspection_count(HARI) == 3
    assert (sesudah["menunggu"], sesudah["tersambung"]) == (0, True)


def test_konsol_mati_lalu_hidup_antrean_habis_sendiri(pabrik):
    konsol, kabel, jam, _, line_1, nyalakan = pabrik
    line, layar = nyalakan()
    kabel.putus = True
    for n in range(5):
        e = _event(line_1.machine_id, n)
        line.store.add_event(e["event_id"], e["machine_id"], e)

    for _ in range(120):  # dua menit, satu putaran per detik
        line.worker._flush_pending()
        jam.maju(1)
    putus = _antrean(layar)

    assert (putus["menunggu"], putus["tersambung"], putus["sebab_putus"]) == (5, False, "tak_terjangkau")
    assert kabel.permintaan <= 120 / JEDA_SAMBUNGAN_MAKS_S + 4

    kabel.putus = False
    jam.maju(JEDA_SAMBUNGAN_MAKS_S)
    line.worker._flush_pending()

    assert konsol.store.inspection_count(HARI) == 5
    pulih = _antrean(layar)
    assert (pulih["menunggu"], pulih["tersambung"]) == (0, True)


def test_kirim_ulang_dari_layar_tidak_menunggu_jeda(pabrik):
    konsol, kabel, _, _, line_1, nyalakan = pabrik
    line, layar = nyalakan()
    kabel.putus = True
    for n in range(2):
        e = _event(line_1.machine_id, n)
        line.store.add_event(e["event_id"], e["machine_id"], e)
    line.worker._flush_pending()  # putus: jeda sambungan mulai
    kabel.putus = False
    line.worker._flush_pending()
    assert konsol.store.inspection_count(HARI) == 0  # masih dalam jeda, jam tidak maju

    jawab = layar.post("/api/console/dev/antrean/line/line-1/kirim-ulang")
    line.worker._flush_pending()

    assert (jawab.status_code, jawab.json()) == (200, {"line_code": "line-1", "dijadwalkan": 2})
    assert konsol.store.inspection_count(HARI) == 2
