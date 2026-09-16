"""Writes one bunch's images to disk, in the layout `domain/capture_layout.py` names.

Both image writers go through here — `FrameProcessingWorker` (auto) and
`CaptureRepository` (manual reject). They used to each build their own path, and
a layout that two files decide separately is a layout that drifts: the same
folder would come to mean different things depending on which line wrote it.

This module owns *writing*; the layout module owns *naming*. Neither knows about
the JSON sidecar, which stays flat in the day folder (see `capture_layout`).
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain.capture_layout import CaptureVariant, image_relative_path, truck_folder_name

logger = logging.getLogger(__name__)

# Deliberately NOT imported from `core.constants`: that module imports cv2 at
# top level, and the unit suite runs without cv2 on purpose (CLAUDE.md § Tests).
# Pulling it in here would drag the whole capture path out of CI.
# `tests/unit/test_capture_layout_constants.py` keeps the two in step.
_SAVE_QUALITY = 65


class ImageStorage(Protocol):
    """The slice of `LocalFileStorage` this needs — a seam for tests."""

    def write_image(self, path: Path, frame: Any, quality: int = ...) -> None: ...


class CaptureWriter:
    def __init__(self, settings: Any, storage: ImageStorage) -> None:
        self._settings = settings
        self._storage = storage

    # ------------------------------------------------------------------ clock

    def _mill_zone(self) -> datetime.tzinfo:
        """`FACTORY_TZ`, falling back to UTC rather than failing a capture.

        A bad zone makes folder names less readable; refusing to write would
        lose the bunch. `console_main` already rejects a bogus zone at boot, so
        this path is the last resort, not the guard.
        """
        try:
            return ZoneInfo(self._settings.factory_tz)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "FACTORY_TZ %r is not a known zone — capture folders fall back to UTC",
                self._settings.factory_tz,
            )
            return datetime.UTC

    def _folder_clock(self, assigned_at: str | None, fallback: datetime.datetime):
        """When the truck was assigned; the capture's own time if unknown.

        The folder is named once per truck, so its clock is the assignment, not
        whichever bunch happened to be graded first. An older console sends no
        `assigned_at` at all — then a slightly-off name beats losing the image.
        """
        if not assigned_at:
            return fallback
        try:
            parsed = datetime.datetime.fromisoformat(assigned_at)
        except ValueError:
            logger.warning("Unparseable assigned_at %r — using the capture time", assigned_at)
            return fallback
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)

    # ------------------------------------------------------------------ write

    def truck_folder(
        self,
        *,
        assignment_id: str | None,
        plate: str | None,
        assigned_at: str | None,
        now: datetime.datetime,
    ) -> str:
        zone = self._mill_zone()
        return truck_folder_name(
            self._folder_clock(assigned_at, now),
            plate=plate,
            assignment_id=assignment_id,
            tz=zone,
        )

    def write_pair(
        self,
        *,
        date_folder: str,
        truck_folder: str,
        ripeness_status: str,
        filename: str,
        annotated_frame: Any,
        clean_frame: Any,
    ) -> str:
        """Write both variants and return the annotated one's `captures/` path.

        Annotated goes first on purpose: it is the copy `image_path` names, so if
        the disk fails the write raises before any record can point at a file
        that was never created (Critical Rule #8). The clean copy is the training
        material — worth keeping, never worth failing a grading run for.
        """
        annotated_relative = image_relative_path(
            date_folder=date_folder,
            truck_folder=truck_folder,
            variant=CaptureVariant.ANNOTATED,
            ripeness_status=ripeness_status,
            filename=filename,
        )
        self._storage.write_image(
            self._settings.results_dir / annotated_relative,
            annotated_frame,
            quality=_SAVE_QUALITY,
        )

        clean_relative = image_relative_path(
            date_folder=date_folder,
            truck_folder=truck_folder,
            variant=CaptureVariant.CLEAN,
            ripeness_status=ripeness_status,
            filename=filename,
        )
        try:
            self._storage.write_image(
                self._settings.results_dir / clean_relative,
                clean_frame,
                quality=_SAVE_QUALITY,
            )
        except OSError as exc:
            # Never fatal: the evidence copy and its sidecar are already safe, and
            # a grading line must not stop because the training copy did not fit.
            logger.error("Clean capture copy failed (%s): %s", clean_relative, exc)

        return f"captures/results/{annotated_relative}"
