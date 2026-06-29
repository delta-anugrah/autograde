from __future__ import annotations

import atexit
import datetime
import logging
import shutil
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

from ...core.config import Settings

logger = logging.getLogger(__name__)


def _get_unique_path(path: Path) -> Path:
    counter = 1
    new_path = path
    while new_path.exists():
        new_path = path.parent / f"{path.name}_{counter}"
        counter += 1
    return new_path


def _upload_today_errors(settings: Settings) -> None:
    if not settings.destination_upload:
        logger.warning("DESTINATION_UPLOAD tidak diset, skip.")
        return

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    destination = Path(settings.destination_upload)

    # results/ adalah satu-satunya sumber kebenaran (errors/ sudah tidak ditulis lagi).
    for folder_type, source_dir in [
        ("results", settings.results_dir / today),
    ]:
        if not source_dir.exists():
            logger.info("No source folder for today: %s", source_dir)
            continue

        dest_path = _get_unique_path(destination / f"{folder_type}_{today}")
        try:
            shutil.copytree(str(source_dir), str(dest_path))
            logger.info("Copied %s -> %s", source_dir, dest_path)
            shutil.rmtree(str(source_dir))
            logger.info("Deleted %s", source_dir)
        except Exception as e:
            logger.error("Failed to upload %s: %s", source_dir, e)


class UploadScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            _upload_today_errors,
            "cron",
            hour=self.settings.upload_hour,
            minute=self.settings.upload_minute,
            args=[self.settings],
        )
        self._scheduler.start()
        atexit.register(self.stop)
        logger.info(
            "Upload scheduled at %02d:%02d",
            self.settings.upload_hour,
            self.settings.upload_minute,
        )

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
            logger.info("Scheduler stopped")
