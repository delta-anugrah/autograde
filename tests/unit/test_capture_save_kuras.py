"""Penutup line harus tahu PERSIS janjang mana yang belum tertulis (batch 2.2).

`tunggu_kosong` dulu memeriksa `empty()` + tanda sibuk. Di antara `get()` dan
tanda sibuk dipasang, janjang yang sudah dipegang penulis tidak terlihat di
keduanya: penutup line membaca "kosong", keluar, dan janjang itu hilang tanpa
foto maupun sidecar. `antrean_tersisa` dipakai log penutup untuk menyebut
janjang yang tidak sempat ditulis satu per satu.

Jalan tanpa torch/cv2: storage di-stub.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob, sebut_janjang


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")


class _Storage:
    def write_image(self, path, frame, quality: int = 80) -> None:
        pass

    def write_json(self, path, payload) -> None:
        pass

    def write_thumbnail(self, path, frame, *, max_width: int, quality: int) -> None:
        pass


class _StorageTertahan(_Storage):
    """Disk yang macet: gambar pertama baru selesai ditulis sesudah `lepas`."""

    def __init__(self) -> None:
        self.mulai = threading.Event()
        self.lepas = threading.Event()

    def write_image(self, path, frame, quality: int = 80) -> None:
        self.mulai.set()
        self.lepas.wait(10)


class _Outbox:
    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        pass


def _job(timestamp: str, assignment_id: str | None = "a3f9c201-dead-beef") -> SaveJob:
    return SaveJob(
        timestamp=timestamp,
        date_folder="2026-09-28",
        truck_folder="091432_B1234XY_a3f9c201",
        annotated_frame="ANNOTATED",
        clean_frame="CLEAN",
        ripeness_status="acc",
        ripeness_conf=0.9,
        grade_class="Ripe",
        bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        truck_id="truck-1",
        assignment_id=assignment_id,
        ffb_source="External",
        event_ts="2026-09-28T02:14:32+00:00",
    )


def test_tunggu_kosong_menghitung_janjang_yang_sedang_dipegang_penulis(settings):
    w = CaptureSaveWorker(settings, _Storage(), _Outbox())
    w.submit(_job("2026-09-28_091432_000001"))
    # Penulis sudah mengambilnya dari antrean tapi belum selesai menulis:
    # antrean kosong, tanda sibuk belum terpasang. Dulu ini terbaca "kosong".
    w._queue.get_nowait()

    assert w.tunggu_kosong(timeout=0.05) is False
    assert w.belum_selesai == 1

    w._queue.task_done()
    assert w.tunggu_kosong(timeout=0.05) is True
    assert w.belum_selesai == 0


def test_antrean_tersisa_menyebut_yang_sedang_ditulis_lalu_yang_antre(settings):
    storage = _StorageTertahan()
    w = CaptureSaveWorker(settings, storage, _Outbox())
    w.start()
    try:
        w.submit(_job("2026-09-28_091432_000001"))
        assert storage.mulai.wait(5), "penulis tidak pernah mulai"
        w.submit(_job("2026-09-28_091433_000002", assignment_id=None))

        assert w.antrean_tersisa() == [
            ("2026-09-28_091432_000001", "a3f9c201-dead-beef"),
            ("2026-09-28_091433_000002", None),
        ]
        assert w.belum_selesai == 2
    finally:
        # Tanpa assert di sini: assert yang gagal di `finally` menutupi kegagalan
        # asli di atas dengan pesan yang tidak ada hubungannya.
        storage.lepas.set()
        kosong = w.tunggu_kosong(timeout=5)
        w.stop(timeout=2)

    assert kosong
    assert w.antrean_tersisa() == []


def test_antrean_tersisa_kosong_saat_tidak_ada_apa_apa(settings):
    assert CaptureSaveWorker(settings, _Storage(), _Outbox()).antrean_tersisa() == []


# ── pintu ditutup saat line menutup ──────────────────────────────────────────
#
# Sesudah antrean dihabiskan dan penulis dihentikan, thread deteksi masih bisa
# menyerahkan janjang (link PLC mati = tahap tutup makan hampir seluruh 9
# detik). Dulu `submit` tetap menerimanya: True, masuk antrean, tidak ada yang
# menulis, dan daftar ERROR sudah dibaca. Hilang tanpa jejak.


def test_submit_sesudah_pintu_ditutup_ditolak_dan_disebut(settings, caplog):
    w = CaptureSaveWorker(settings, _Storage(), _Outbox())
    w.tutup_pintu()

    with caplog.at_level(logging.ERROR, logger="palmgrade.workers.capture_save_worker"):
        assert w.submit(_job("2026-09-28_091432_000001")) is False
        assert w.submit(_job("2026-09-28_091433_000002", assignment_id=None)) is False

    assert w.belum_selesai == 0
    assert w.antrean_tersisa() == []
    error = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error) == 2
    assert "line sedang menutup" in error[0]
    assert "2026-09-28_091432_000001 (a3f9c201)" in error[0]
    assert "2026-09-28_091433_000002 (tanpa truk)" in error[1]


def test_pintu_tertutup_tidak_dibuka_lagi_oleh_watchdog(settings):
    """Watchdog 10 detik memanggil `run_loop` langsung, yang membersihkan `_stop`.
    Itu tidak boleh membuka lagi pintu yang ditutup penutup line."""
    w = CaptureSaveWorker(settings, _Storage(), _Outbox())
    w.start()
    w.tutup_pintu()
    w.stop(timeout=2)

    ulang = threading.Thread(target=w.run_loop, daemon=True, name="capture_save")
    ulang.start()
    try:
        deadline = time.monotonic() + 2
        while w._stop.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not w._stop.is_set(), "run_loop tidak pernah jalan ulang"
        assert w.submit(_job("2026-09-28_091432_000001")) is False
        assert w.belum_selesai == 0
    finally:
        w.stop(timeout=2)


def test_pintu_terbuka_sebelum_ditutup(settings):
    w = CaptureSaveWorker(settings, _Storage(), _Outbox())
    assert w.submit(_job("2026-09-28_091432_000001")) is True
    assert w.belum_selesai == 1


def test_sebut_janjang_memakai_delapan_huruf_assignment():
    assert sebut_janjang("2026-09-28_091432_000001", "a3f9c201-dead-beef") == (
        "2026-09-28_091432_000001 (a3f9c201)"
    )
    assert sebut_janjang("2026-09-28_091432_000001", None) == "2026-09-28_091432_000001 (tanpa truk)"
