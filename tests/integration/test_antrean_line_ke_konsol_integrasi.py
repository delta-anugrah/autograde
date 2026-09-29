"""Worker antrean line yang ASLI ke lane ingest konsol yang ASLI (SQLite sungguhan).

Yang dibuktikan di sini, bukan di unit test: konsol yang menerima event yang sama
dua kali (jawaban pertama hilang di jalan, line mati sebelum menghapus barisnya)
tetap menghitung satu janjang, dan penolakan konsol yang sungguhan (401 kunci,
400 timestamp rusak) dinilai benar oleh worker.
"""
from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from antrean_line_rakit import KabelKonsol, app_ingest
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.outbox_retry_worker import OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-webhook-palsu"
TS = "2026-09-20T03:00:00+00:00"
HARI = "2026-09-20"


def _event(machine_id: str, ts: str = TS) -> dict:
    return {
        "event_id": str(uuid.uuid4()), "machine_id": machine_id, "timestamp": ts,
        "prediction": "Acc", "ripeness_status": "ACC", "ripeness_confidence": 0.9,
        "capture_type": "auto", "image_path": f"captures/results/{HARI}/x.webp",
    }


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(
        Settings(), repo_root=tmp_path, backend_url="http://testserver",
        webhook_secret=SECRET, factory_tz="Asia/Jakarta", enable_webhook=True,
    )
    konsol = ConsoleService(settings, ConsoleStore(tmp_path / "konsol.db"), line_client=None)
    kabel = KabelKonsol(app_ingest(konsol))
    store = OutboxStore(tmp_path / "state" / "outbox.db")

    def worker(secret: str = SECRET) -> OutboxRetryWorker:
        return OutboxRetryWorker(store, replace(settings, webhook_secret=secret), RuntimeState(), client=kabel.klien())

    return konsol, store, kabel, worker


def test_jawaban_hilang_lalu_dikirim_ulang_tetap_satu_janjang(pabrik):
    """Review focus 3: konsol sudah menyimpan, jawabannya tidak pernah sampai, line
    mati sebelum `mark_delivered`. Sesudah boot baris itu terkirim lagi."""
    konsol, store, _, worker = pabrik
    body = _event(konsol.lines[0].machine_id)
    store.add_event(body["event_id"], body["machine_id"], body)
    langsung = TestClient(app_ingest(konsol)).post(
        "/api/v1/internal/vision/events", json=body, headers={"x-webhook-secret": SECRET}
    )
    assert langsung.status_code == 201

    worker()._flush_pending()

    assert konsol.store.inspection_count(HARI) == 1
    assert store.pending_count() == 0


def test_kunci_webhook_beda_menahan_antrean_tanpa_membuang(pabrik):
    konsol, store, kabel, worker = pabrik
    body = _event(konsol.lines[0].machine_id)
    store.add_event(body["event_id"], body["machine_id"], body)
    salah = worker(secret="bukan-" + SECRET)

    salah._flush_pending()
    salah._flush_pending()

    assert kabel.permintaan == 1
    assert salah.status()["sebab_putus"] == "kunci_ditolak"
    assert store.pending_count() == 1
    assert konsol.store.inspection_count(HARI) == 0


def test_timestamp_rusak_ditolak_konsol_yang_lain_tetap_sampai(pabrik):
    konsol, store, _, worker = pabrik
    mesin = konsol.lines[0].machine_id
    bagus, rusak = _event(mesin), _event(mesin, ts="bukan-waktu")
    for body in (bagus, rusak):
        store.add_event(body["event_id"], mesin, body)
    w = worker()

    w._flush_pending()

    assert konsol.store.inspection_count(HARI) == 1
    sisa = store._db.execute("SELECT event_id, last_error FROM outbox_events").fetchall()
    assert [r["event_id"] for r in sisa] == [rusak["event_id"]]
    assert sisa[0]["last_error"].startswith("HTTP 400")
    assert w.status()["tersambung"] is True
