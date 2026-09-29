"""Tutup line tidak menunggu batch upload R2 yang sedang jalan (batch 2.2).

Menunggu 500 foto naik ke R2 bisa memakan menit, jauh melewati batas tutup
line. Batch itu aman diputus di tengah (`test_batch_upload_crash.py`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import UTC, datetime

from palmgrade.core.config import Settings
from palmgrade.integrations.scheduler.upload_scheduler import UploadScheduler


def _penjadwal_dengan_batch_berjalan(tmp_path):
    mulai, lepas = threading.Event(), threading.Event()

    def batch() -> None:
        mulai.set()
        lepas.wait(10)

    penjadwal = UploadScheduler(settings=replace(Settings(), repo_root=tmp_path), run_batch=batch)
    penjadwal.start()
    # Jalankan tick sekarang, bukan menunggu menit UPLOAD_MINUTE berikutnya.
    penjadwal._scheduler.get_jobs()[0].modify(next_run_time=datetime.now(UTC))
    assert mulai.wait(5), "batch tidak pernah jalan"
    return penjadwal, lepas


def test_stop_tanpa_tunggu_tidak_menahan_batch_yang_jalan(tmp_path):
    penjadwal, lepas = _penjadwal_dengan_batch_berjalan(tmp_path)
    try:
        t0 = time.monotonic()
        penjadwal.stop(tunggu=False)
        assert time.monotonic() - t0 < 1.0
    finally:
        lepas.set()


def test_stop_bawaan_tetap_menunggu_batch_selesai(tmp_path):
    penjadwal, lepas = _penjadwal_dengan_batch_berjalan(tmp_path)
    threading.Timer(0.3, lepas.set).start()
    t0 = time.monotonic()
    penjadwal.stop()
    assert time.monotonic() - t0 >= 0.25
