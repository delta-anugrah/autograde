"""Writes one bunch's images to disk, in the layout `domain/capture_layout.py` names.

Both image writers go through here — `FrameProcessingWorker` (auto) and
`CaptureRepository` (manual reject). They used to each build their own path, and
a layout that two files decide separately is a layout that drifts: the same
folder would come to mean different things depending on which line wrote it.

This module owns *writing*; the layout module owns *naming*. Neither knows about
the JSON sidecar, which stays flat in the day folder (see `capture_layout`).
"""
from __future__ import annotations

import contextlib
import datetime
import logging
import threading
from collections.abc import Callable
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
# The backoffice grid loads 500 of these per truck: keep one under ~15 KB.
_THUMB_WIDTH = 400
_THUMB_QUALITY = 60


class ImageStorage(Protocol):
    """The slice of `LocalFileStorage` this needs — a seam for tests."""

    def write_image(self, path: Path, frame: Any, quality: int = ...) -> None: ...
    def write_thumbnail(self, path: Path, frame: Any, *, max_width: int, quality: int) -> None: ...


class _TulisDiSamping:
    """One write on its own thread, started at once (batch 6.2).

    A thread per bunch, not a pool: a line saves a bunch every few seconds at most, so there
    is nothing to keep warm and nothing to shut down. `tunggu()` always joins, so the helper
    never outlives the `write_pair` call that started it.
    """

    def __init__(self, tulis: Callable[[], None]) -> None:
        self._tulis = tulis
        self._galat: BaseException | None = None
        self._thread = threading.Thread(target=self._jalan, name="capture_clean", daemon=True)
        self._thread.start()

    def _jalan(self) -> None:
        try:
            self._tulis()
        except BaseException as exc:  # handed to the caller by `tunggu()`, never lost here
            self._galat = exc

    def tunggu(self) -> BaseException | None:
        """Wait for the write to end; what it raised, or None."""
        self._thread.join()
        return self._galat


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
        except (ZoneInfoNotFoundError, ValueError, OSError):
            # OSError: a zone folder name (`Asia`) through the `tzdata` package
            # raises IsADirectoryError, not ZoneInfoNotFoundError.
            logger.warning(
                "FACTORY_TZ %r is not a known zone, capture folders fall back to UTC",
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
            logger.warning("Unparseable assigned_at %r, using the capture time", assigned_at)
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

    @staticmethod
    def annotated_url(
        *,
        date_folder: str,
        truck_folder: str,
        grade_class: str | None,
        filename: str,
        tp: bool = False,
    ) -> str:
        """Tautan `captures/` ke salinan bbox — tanpa menulis apa pun.

        Ada supaya jalur deteksi bisa menyebut tautan itu ke layar operator
        seketika, sementara berkasnya baru ditulis thread penulis beberapa ratus
        milidetik kemudian. Satu-satunya cara aman melakukan itu adalah memakai
        rumus yang sama persis dengan `write_pair` di bawah — dua perhitungan
        terpisah akan menyimpang diam-diam, dan yang terlihat cuma gambar 404 di
        konsol tanpa satu pun error di line.
        """
        return "captures/results/" + image_relative_path(
            date_folder=date_folder,
            truck_folder=truck_folder,
            variant=CaptureVariant.ANNOTATED,
            grade_class=grade_class,
            filename=filename,
            tp=tp,
        )

    def write_pair(
        self,
        *,
        date_folder: str,
        truck_folder: str,
        grade_class: str | None,
        filename: str,
        annotated_frame: Any,
        clean_frame: Any,
        tp: bool = False,
    ) -> str:
        """Write both variants and return the annotated one's `captures/` path.

        The annotated copy is the one `image_path` names, so if the disk fails this raises
        before any record can point at a file that was never created (Critical Rule #8). The
        clean copy is the training material: worth keeping, never worth failing a grading
        run for.

        Both are full-size WebP encodes, the slow part of saving a bunch. Since batch 6.2
        the clean copy is written on a helper thread WHILE the annotated copy is written
        here (cv2 releases the GIL while it encodes). The annotated copy stays on this
        thread because its failure is the one that raises. If it fails, the clean copy that
        was written beside it is removed again: it has no manifest row of its own, so
        without its annotated twin retention would never delete it (rule 9).
        """
        annotated_relative = image_relative_path(
            date_folder=date_folder,
            truck_folder=truck_folder,
            variant=CaptureVariant.ANNOTATED,
            grade_class=grade_class,
            filename=filename,
            tp=tp,
        )
        clean_relative = image_relative_path(
            date_folder=date_folder,
            truck_folder=truck_folder,
            variant=CaptureVariant.CLEAN,
            grade_class=grade_class,
            filename=filename,
            tp=tp,
        )
        clean_path = self._settings.results_dir / clean_relative
        clean_di_samping = _TulisDiSamping(
            lambda: self._storage.write_image(clean_path, clean_frame, quality=_SAVE_QUALITY)
        )
        try:
            self._storage.write_image(
                self._settings.results_dir / annotated_relative,
                annotated_frame,
                quality=_SAVE_QUALITY,
            )
        except BaseException:
            clean_di_samping.tunggu()
            with contextlib.suppress(OSError):
                clean_path.unlink(missing_ok=True)
            raise

        galat_clean = clean_di_samping.tunggu()
        if isinstance(galat_clean, OSError):
            # Never fatal: the evidence copy and its sidecar are already safe, and
            # a grading line must not stop because the training copy did not fit.
            logger.error("Clean capture copy failed (%s): %s", clean_relative, galat_clean)
        elif galat_clean is not None:
            # Not a disk refusal: raised here as it was when this ran on the calling thread.
            raise galat_clean

        thumb_relative = image_relative_path(
            date_folder=date_folder, truck_folder=truck_folder,
            variant=CaptureVariant.THUMB, grade_class=grade_class, filename=filename, tp=tp,
        )
        try:
            self._storage.write_thumbnail(
                self._settings.results_dir / thumb_relative, annotated_frame,
                max_width=_THUMB_WIDTH, quality=_THUMB_QUALITY,
            )
        except OSError as exc:
            # Same rule as the clean copy: the evidence is already on disk, and a
            # grading line must not stop because a preview did not fit.
            logger.error("Thumbnail failed (%s): %s", thumb_relative, exc)

        return self.annotated_url(
            date_folder=date_folder,
            truck_folder=truck_folder,
            grade_class=grade_class,
            filename=filename,
            tp=tp,
        )
