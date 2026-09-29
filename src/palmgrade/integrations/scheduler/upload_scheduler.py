"""Scheduler batch upload cloud — tiap jam pada menit UPLOAD_MINUTE.

Pengganti archiver lokal lama (copytree+rmtree ke DESTINATION_UPLOAD) yang
sudah tidak dipakai. Sekarang satu-satunya job: BatchUploadWorker.run_batch_once
(spec 2026-07-10 §3.4). max_instances=1 + coalesce=True → tick yang telat/numpuk
di-skip, tidak pernah jalan paralel.
"""
from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from ...core.config import Settings

logger = logging.getLogger(__name__)


class UploadScheduler:
    def __init__(self, settings: Settings, run_batch: Callable[[], None]) -> None:
        self.settings = settings
        self._run_batch = run_batch
        self._scheduler: BackgroundScheduler | None = None
        #: Dipasang `stop(tunggu=False)`: job yang sedang menunggu batch-nya berhenti menunggu.
        self._lepas = threading.Event()

    def start(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._jalankan_batch,
            CronTrigger(minute=self.settings.upload_minute),
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        atexit.register(self.stop)
        logger.info(
            "Batch upload terjadwal tiap jam pada menit %02d (R2_BUCKET=%s)",
            self.settings.upload_minute,
            self.settings.r2_bucket or "<kosong — no-op>",
        )

    def _jalankan_batch(self) -> None:
        """Job APScheduler: batch di thread DAEMON, ditunggu sampai selesai atau dilepas.

        Thread pool APScheduler bukan daemon, dan interpreter menunggunya saat keluar:
        `shutdown(wait=False)` saja membuat SIGTERM di tengah batch jam-an menahan
        proses sampai SIGKILL `docker stop` (final review batch 2, line M1). Menunggu
        di sini tetap menjaga `max_instances=1` selama penjadwal hidup; begitu
        `stop(tunggu=False)` melepasnya, thread pool pulang dan batch yang tersisa
        mati bersama proses (aman: manifest SQLite, `test_batch_upload_crash.py`).
        """
        batch = threading.Thread(target=self._batch_tercatat, daemon=True, name="batch-unggah")
        batch.start()
        while batch.is_alive() and not self._lepas.wait(0.2):
            pass

    def _batch_tercatat(self) -> None:
        # Di thread sendiri APScheduler tidak lagi melihat exception-nya.
        try:
            self._run_batch()
        except Exception:
            logger.exception("Batch upload gagal")

    def stop(self, *, tunggu: bool = True) -> None:
        """Hentikan penjadwal. `tunggu=False` = jangan menunggu batch yang sedang jalan.

        Dipakai tutup line (batch 2.2): batch upload aman diputus di tengah
        (state per item di manifest SQLite, `test_batch_upload_crash.py`), dan
        menunggu 500 foto naik ke R2 bisa memakan menit, jauh melewati batas
        tutup line. `atexit` tetap memanggil bentuk bawaan yang menunggu.
        """
        if not tunggu:
            self._lepas.set()
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=tunggu)
            logger.info("Batch upload scheduler stopped")
