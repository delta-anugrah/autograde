"""Scheduler batch upload cloud — tiap jam pada menit UPLOAD_MINUTE.

Pengganti archiver lokal lama (copytree+rmtree ke DESTINATION_UPLOAD) yang
sudah tidak dipakai. Sekarang satu-satunya job: BatchUploadWorker.run_batch_once
(spec 2026-07-10 §3.4). max_instances=1 + coalesce=True → tick yang telat/numpuk
di-skip, tidak pernah jalan paralel.
"""
from __future__ import annotations

import atexit
import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from ...core.config import Settings

logger = logging.getLogger(__name__)


class UploadScheduler:
    def __init__(self, settings: Settings, run_batch: Callable[[], None]) -> None:
        self.settings = settings
        self._run_batch = run_batch
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._run_batch,
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

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
            logger.info("Batch upload scheduler stopped")
