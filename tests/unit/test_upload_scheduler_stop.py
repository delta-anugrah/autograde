"""Tutup line tidak menunggu batch upload R2 yang sedang jalan (batch 2.2).

Menunggu 500 foto naik ke R2 bisa memakan menit, jauh melewati batas tutup
line. Batch itu aman diputus di tengah (`test_batch_upload_crash.py`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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


_PROSES_KELUAR = """
import sys, threading, time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from palmgrade.core.config import Settings
from palmgrade.integrations.scheduler.upload_scheduler import UploadScheduler

mulai = threading.Event()
def batch():
    mulai.set()
    time.sleep(30)  # satu batch R2 ratusan foto

penjadwal = UploadScheduler(settings=replace(Settings(), repo_root=Path(sys.argv[1])), run_batch=batch)
penjadwal.start()
penjadwal._scheduler.get_jobs()[0].modify(next_run_time=datetime.now(UTC))
assert mulai.wait(5)
penjadwal.stop(tunggu=False)
print("utama selesai", flush=True)
"""


def test_batch_yang_jalan_tidak_menahan_proses_keluar_sesudah_stop(tmp_path):
    """Final review line M1: `shutdown(wait=False)` cuma berhenti menjadwal. Batch yang
    sedang jalan duduk di thread pool yang BUKAN daemon, dan interpreter menunggunya
    saat keluar: SIGTERM di tengah batch jam-an membuat proses bertahan sampai SIGKILL
    `docker stop` (exit 137, aturan 29 "keluar dalam ~9,2 detik" tidak berlaku).
    Batch itu aman diputus (`test_batch_upload_crash.py`), jadi proses boleh pergi."""
    t0 = time.monotonic()
    hasil = subprocess.run(
        [sys.executable, "-c", _PROSES_KELUAR, str(tmp_path)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    lama = time.monotonic() - t0

    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert "utama selesai" in hasil.stdout
    assert lama < 10, f"proses bertahan {lama:.1f} dtk menunggu batch upload"
