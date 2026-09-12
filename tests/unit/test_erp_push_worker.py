"""Dorong event konsol → PalmOS (runbook §12.5).

Yang dikunci di sini bukan "berhasil kirim", tapi tiga cara gagal yang bedanya
menentukan: kiriman ulang bukan error, tolakan ERP permanen, dan kegagalan
jaringan TIDAK boleh membuang apa pun.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers import erp_push_worker
from palmgrade.workers.erp_push_worker import ErpPushWorker

ERP = "http://erp.local"


class FakeLineClient:
    async def assign_truck(self, *_a, **_kw) -> None: ...

    async def manual_reject(self, *_a, **_kw) -> None: ...


def _siapkan(tmp_path, monkeypatch, handler) -> tuple[ErpPushWorker, ConsoleService]:
    """Worker + service di atas satu store, dengan jaringan diganti transport.

    Seam-nya jaringan — satu-satunya kolaborator yang memang tidak boleh nyata.
    Menambal method privat worker cuma menguji tiruannya sendiri.
    """
    transport = httpx.MockTransport(handler)
    asli = httpx.AsyncClient
    monkeypatch.setattr(
        erp_push_worker.httpx,
        "AsyncClient",
        lambda **kw: asli(transport=transport, headers=kw.get("headers")),
    )
    settings = replace(
        Settings(), factory_tz="Asia/Jakarta", erp_url=ERP, erp_api_key="k", erp_api_secret="s"
    )
    store = ConsoleStore(tmp_path / "console.db")
    return ErpPushWorker(settings, store), ConsoleService(settings, store, FakeLineClient())


def _dorong(worker) -> int:
    return asyncio.run(worker.push_once())


def _event(service, **over):
    payload = {
        "event_id": "ev-1",
        "machine_id": service.lines[0].machine_id,
        "timestamp": "2026-09-09T18:30:00+00:00",
        "prediction": "Acc",
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.91,
        "capture_type": "auto",
        "image_path": "captures/results/2026-09-09/f.webp",
        "tp_status": "PASS",
        "tp_confidence": 0.4,
    }
    payload.update(over)
    return payload


def _erp_state(store, event_id):
    row = store._db.execute(
        "SELECT erp_state FROM inspections WHERE event_id = ?", (event_id,)
    ).fetchone()
    return row["erp_state"]


def test_event_mendarat_dan_tidak_dikirim_dua_kali(tmp_path, monkeypatch):
    panggilan = []

    def handler(req):
        panggilan.append(req)
        return httpx.Response(200, json={"message": {"baru": True}})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service))

    assert _dorong(worker) == 1
    # Tick kedua: barisnya sudah bertanda, jadi ERP tidak dihubungi lagi sama
    # sekali — idempotensi di ERP itu jaring pengaman, bukan alasan boros.
    assert _dorong(worker) == 0
    assert len(panggilan) == 1
    assert _erp_state(service.store, "ev-1") == "ok"


def test_kiriman_ulang_yang_sudah_ada_di_erp_bukan_error(tmp_path, monkeypatch):
    # `{"baru": false}` = event ini sudah pernah mendarat. Itu jawaban sukses:
    # outbox konsol memang mengirim ulang isinya setelah internet balik.
    worker, service = _siapkan(
        tmp_path, monkeypatch, lambda req: httpx.Response(200, json={"message": {"baru": False}})
    )
    service.ingest(_event(service))
    assert _dorong(worker) == 1
    assert _erp_state(service.store, "ev-1") == "ok"


def test_tolakan_erp_permanen_tidak_diputar_selamanya(tmp_path, monkeypatch):
    # 417 = frappe.throw. Payload cacat yang diulang tiap menit selamanya cuma
    # bikin antrean di belakangnya kelaparan.
    panggilan = []

    def handler(req):
        panggilan.append(req)
        return httpx.Response(417, json={"exception": "Event ditolak: image_path kosong"})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service, image_path=None))

    assert _dorong(worker) == 0
    assert _erp_state(service.store, "ev-1") == "tolak"
    assert _dorong(worker) == 0
    assert len(panggilan) == 1


def test_erp_mati_menahan_antrean_tanpa_membuang_apa_pun(tmp_path, monkeypatch):
    def handler(req):
        raise httpx.ConnectError("connection refused")

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service))

    assert _dorong(worker) == 0
    # Kolomnya TIDAK disentuh: tick berikutnya harus mengambilnya lagi. Menandai
    # gagal di sini akan menghapus janjang dari ERP gara-gara internet putus.
    assert _erp_state(service.store, "ev-1") is None
    assert len(service.store.belum_didorong(10)) == 1


def test_kredensial_salah_menahan_seluruh_batch(tmp_path, monkeypatch):
    # 403 itu kondisi global, bukan salah barisnya. Satu baris pun tidak boleh
    # ditandai — kalau ditandai, seluruh hari hilang gara-gara API key kedaluwarsa.
    panggilan = []

    def handler(req):
        panggilan.append(req)
        return httpx.Response(403, json={"exception": "not permitted"})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    for i in range(3):
        service.ingest(_event(service, event_id=f"ev-{i}"))

    assert _dorong(worker) == 0
    assert len(panggilan) == 1  # batch berhenti di baris pertama
    assert len(service.store.belum_didorong(10)) == 3


def test_payload_membawa_prediction_apa_adanya_bukan_diturunkan_ulang(tmp_path, monkeypatch):
    # Aturan Acc/Rej hidup di line (`vision_event.py`). Menurunkannya lagi di
    # konsol berarti dua aturan yang bisa berbeda tanpa ada yang tahu.
    dikirim = []

    def handler(req):
        dikirim.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"baru": True}})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service, prediction="Rej", ripeness_status="REJ"))
    _dorong(worker)

    assert dikirim[0]["prediction"] == "Rej"
    assert dikirim[0]["tp_status"] == "PASS"
    assert dikirim[0]["image_path"] == "captures/results/2026-09-09/f.webp"


def test_auth_pakai_token_frappe(tmp_path, monkeypatch):
    header = []

    def handler(req):
        header.append(req.headers.get("authorization"))
        return httpx.Response(200, json={"message": {"baru": True}})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service))
    _dorong(worker)
    assert header[0] == "token k:s"


def test_url_tujuan_adalah_metode_whitelisted_palmos(tmp_path, monkeypatch):
    # Nama metodenya kontrak, bukan detail: salah satu huruf = 404 diam-diam.
    url = []

    def handler(req):
        url.append(str(req.url))
        return httpx.Response(200, json={"message": {"baru": True}})

    worker, service = _siapkan(tmp_path, monkeypatch, handler)
    service.ingest(_event(service))
    _dorong(worker)
    assert url[0] == f"{ERP}/api/method/palmos.interfaces.api.terima_event"


def test_erp_url_kosong_mematikan_worker_bukan_menjatuhkan_konsol(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta", erp_url="")
    worker = ErpPushWorker(settings, ConsoleStore(tmp_path / "console.db"))
    # run_loop kembali langsung, tanpa menunggu interval dan tanpa exception.
    asyncio.run(asyncio.wait_for(worker.run_loop(), timeout=2))


@pytest.mark.parametrize("kode", [500, 502, 429])
def test_gangguan_sementara_ditahan_bukan_dibuang(tmp_path, monkeypatch, kode):
    worker, service = _siapkan(tmp_path, monkeypatch, lambda req: httpx.Response(kode))
    service.ingest(_event(service))
    assert _dorong(worker) == 0
    assert _erp_state(service.store, "ev-1") is None
