"""Janjang yang tiba sesudah truknya dilepas mengirim ulang kunjungannya (batch 2.3).

Rekap truk dikirim saat Lepas. Janjang yang masih di antrean simpan line (maks 8) atau
di outbox line (konsol sempat tidak terjangkau) datang sesudahnya; dulu tidak ada yang
mengantre ulang kunjungannya, jadi rekap di AutoERP kurang sampai kirim ulang besok,
dan tiket yang sudah final tidak pernah dibetulkan.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

PLAT = "BE 8821 KL"
WIB = ZoneInfo("Asia/Jakarta")


class _Line:
    async def assign_truck(self, line, **_kw) -> None: ...


class _Unggah:
    def put_bytes(self, body, r2_key, *, content_type) -> None: ...


class _UnggahDenganSusulan:
    """R2 palsu yang mencatat `counts.total` tiap halaman, dan menjalankan `selagi_unggah`
    di tengah unggahan halaman PERTAMA: janjang susulan tiba selagi kiriman di jalan."""

    def __init__(self) -> None:
        self.total: list[int] = []
        self.selagi_unggah = lambda: None

    def put_bytes(self, body, r2_key, *, content_type) -> None:
        if content_type != "application/json":
            return
        self.total.append(json.loads(body)["counts"]["total"])
        if len(self.total) == 1:
            self.selagi_unggah()


def _sekarang() -> str:
    return datetime.now(WIB).isoformat()


def _konsol(tmp_path, *, erp: bool = True, manifest: bool = False, unggah=None):
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    halaman = None
    if manifest:
        halaman = VisitManifestWorker(
            store, ErpOutboxStore(tmp_path / "manifest_outbox.db"), unggah or _Unggah(),
            public_url="https://captures.example", viewer_html=tmp_path / "viewer.html",
            clock=lambda: "2026-09-28T09:00:00+07:00",
        )
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"), store, _Line(),
        erp_queue=ErpQueue(store, outbox) if erp else None, manifest_queue=halaman,
    )
    return service, outbox, halaman


def _janjang(service: ConsoleService, n: int, assignment_id: str | None, status: str = "ACC") -> None:
    service.ingest({
        "event_id": f"ev-{n}", "machine_id": service.lines[0].machine_id, "timestamp": _sekarang(),
        "ripeness_status": status, "truck_id": truck_id_for(PLAT), "assignment_id": assignment_id,
    })


def _timbang_masuk(service: ConsoleService) -> str:
    tiket = asyncio.run(service.record_weighing(
        {"ref": "SCL-1", "plate_number": PLAT, "entered_at": _sekarang(), "gross_kg": 14560}
    ))
    return tiket["id"]


def _truk_dilepas(service: ConsoleService, jumlah: int = 3) -> tuple[str, str]:
    """Timbang masuk, tugaskan ke line-1, `jumlah` janjang, Lepas. (tiket, assignment)."""
    tiket = _timbang_masuk(service)
    assignment_id = asyncio.run(service.assign_truck("line-1", truck_id_for(PLAT)))["assignment_id"]
    for n in range(jumlah):
        _janjang(service, n, assignment_id)
    asyncio.run(service.release_truck("line-1"))
    return tiket, assignment_id


def _kunjungan(outbox: ErpOutboxStore) -> list:
    return [m for m in outbox.due() if m.kind == "visit"]


def _kirim_semua(outbox: ErpOutboxStore) -> None:
    for pesan in outbox.due():
        outbox.mark_sent(pesan)


def test_add_inspection_membedakan_baris_baru_dari_kiriman_ulang(tmp_path):
    service, _, _ = _konsol(tmp_path)
    baris = {
        "event_id": "ev-1", "machine_id": "m", "line_code": "line-1", "work_date": "2026-09-28",
        "timestamp": _sekarang(), "ripeness_status": "ACC", "ripeness_confidence": None,
        "capture_type": "auto", "image_path": None, "truck_id": None, "assignment_id": None,
        "prediction": "Acc", "tp_status": None, "tp_confidence": None,
    }

    assert service.store.add_inspection(baris) is True
    assert service.store.add_inspection(baris) is False


def test_tiket_ditemukan_lewat_penugasan_yang_ditautkan_saat_lepas(tmp_path):
    service, _, _ = _konsol(tmp_path)
    tiket, assignment_id = _truk_dilepas(service)

    assert service.store.weighing_for_assignment(assignment_id) == tiket
    assert service.store.weighing_for_assignment("penugasan-lain") is None


def test_janjang_sesudah_lepas_mengantre_ulang_kunjungan_dengan_hitungan_baru(tmp_path):
    service, outbox, _ = _konsol(tmp_path)
    tiket, assignment_id = _truk_dilepas(service)
    _kirim_semua(outbox)                               # rekap 3 janjang sudah di AutoERP

    _janjang(service, 99, assignment_id, status="REJ")

    [ulang] = _kunjungan(outbox)
    assert ulang.key == tiket
    assert (ulang.payload["grading"]["counts"]["total"], ulang.payload["grading"]["counts"]["rej"]) == (4, 1)


def test_janjang_yang_sama_dikirim_ulang_tidak_mengantre(tmp_path):
    service, outbox, _ = _konsol(tmp_path)
    _, assignment_id = _truk_dilepas(service)
    _kirim_semua(outbox)

    _janjang(service, 0, assignment_id)                # ev-0 sudah tersimpan

    assert _kunjungan(outbox) == []


def test_janjang_penugasan_yang_masih_berjalan_tidak_mengantre(tmp_path):
    """Rekapnya belum pernah dikirim; Lepas nanti yang mengirimnya, lengkap."""
    service, outbox, _ = _konsol(tmp_path)
    _timbang_masuk(service)
    _kirim_semua(outbox)                               # kunjungan gerbang (bruto)
    assignment_id = asyncio.run(service.assign_truck("line-1", truck_id_for(PLAT)))["assignment_id"]

    _janjang(service, 1, assignment_id)

    assert _kunjungan(outbox) == []


def test_janjang_tanpa_penugasan_tidak_mengantre(tmp_path):
    service, outbox, _ = _konsol(tmp_path)

    _janjang(service, 1, None)
    _janjang(service, 2, "")

    assert _kunjungan(outbox) == []


def test_janjang_susulan_ikut_mengantre_ulang_halaman_detail(tmp_path):
    service, _, halaman = _konsol(tmp_path, manifest=True)
    tiket, assignment_id = _truk_dilepas(service)
    _kirim_semua(halaman.outbox)

    _janjang(service, 99, assignment_id)

    [ulang] = halaman.outbox.due()
    assert (ulang.key, ulang.payload) == (tiket, {"assignment_id": assignment_id})


def test_konsol_tanpa_autoerp_tetap_menerima_janjang_susulan(tmp_path):
    service, _, _ = _konsol(tmp_path, erp=False)
    _, assignment_id = _truk_dilepas(service)

    _janjang(service, 99, assignment_id)

    assert service.store.grading_counts(assignment_id)["total"] == 4


def test_janjang_susulan_selagi_halaman_diunggah_tidak_hilang(tmp_path):
    """Isi antrean halaman selalu `{"assignment_id": X}`, jadi antrean ulangnya sama persis
    dengan yang sedang diunggah. Kiriman lama tidak boleh menandai antrean baru itu
    terkirim: halaman membeku di 3 sementara AutoERP mencatat 4."""
    unggah = _UnggahDenganSusulan()
    service, _, halaman = _konsol(tmp_path, manifest=True, unggah=unggah)
    (tmp_path / "viewer.html").write_text("<html></html>")
    _, assignment_id = _truk_dilepas(service)
    unggah.selagi_unggah = lambda: _janjang(service, 99, assignment_id)

    assert asyncio.run(halaman.drain_once()) == 1
    assert [m.payload for m in halaman.outbox.due()] == [{"assignment_id": assignment_id}]

    assert asyncio.run(halaman.drain_once()) == 1
    assert unggah.total == [3, 4]
    assert halaman.outbox.due() == []
