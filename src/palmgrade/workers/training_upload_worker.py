"""Sends queued training photos to the nexio inbox (nexio spec §6.3).

Photo first, manifest second: nexio imports a photo only once its manifest exists, so a
pass cut off in between leaves nothing half-visible, and the retry overwrites both keys.

What stops a pass and what does not (ruling D5):
- any upload failure stops the pass: the uplink, the key or the bucket fails every row the
  same way, so one row pays the backoff and the log gets one WARNING per tick (D6);
- a photo no longer on disk, empty, or a leftover temp file ends its row as `gone`;
- a photo that cannot be read, or a manifest that cannot be completed, holds that row
  only (status error, backoff) and the pass goes on, so one bad row never stalls the queue.

Timeouts on the upload itself come from the uploader (`r2_uploader.KIRIM_CONFIG`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..domain.berkas_utuh import alasan_tidak_utuh
from ..domain.training_sample import MANIFEST_CONTENT_TYPE, PHOTO_CONTENT_TYPE, object_keys, with_image
from ..integrations.erp.outbox_store import GAGAL_KONSOL
from ..integrations.upload.training_outbox_store import TrainingOutboxStore, TrainingPackage
from .visit_manifest_worker import jenis_gagal_r2

logger = logging.getLogger(__name__)

_INTERVAL_S = 60
_BATCH = 20
_PRUNE_EVERY_S = 3600


class Uploader(Protocol):
    def put_bytes(self, body: bytes, r2_key: str, *, content_type: str) -> None: ...


class PhotoGone(Exception):
    """The clean copy is not on disk, or is a leftover of an interrupted write."""


def _read_photo(path: Path) -> bytes:
    """The photo's bytes. PhotoGone when it will never be there; other OSErrors may pass."""
    try:
        body = path.read_bytes()
    except FileNotFoundError as exc:
        raise PhotoGone("foto clean tidak ada di disk") from exc
    alasan = alasan_tidak_utuh(path.name, len(body))
    if alasan:
        raise PhotoGone(alasan)
    return body


def _objects(row: TrainingPackage, body: bytes) -> tuple[str, str, bytes]:
    """(photo key, manifest key, manifest bytes) for one row, its `image` block filled in."""
    manifest = with_image(row.manifest, sha256=hashlib.sha256(body).hexdigest(), size=len(body))
    photo_key, manifest_key = object_keys(
        manifest["source"]["machine_id"], manifest["captured_at"], manifest["event_id"]
    )
    return photo_key, manifest_key, json.dumps(manifest, ensure_ascii=False).encode("utf-8")


class TrainingUploadWorker:
    def __init__(
        self,
        outbox: TrainingOutboxStore,
        uploader: Uploader,
        *,
        interval_s: int = _INTERVAL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.outbox = outbox
        self._uploader = uploader
        self._interval_s = interval_s
        self._clock = clock
        self._last_prune = 0.0

    async def run_loop(self) -> None:
        logger.info("TrainingUploadWorker started, every %ss", self._interval_s)
        while True:
            try:
                await self.drain()
            except Exception:
                logger.exception("Training photo drain failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    async def drain(self) -> int:
        """Send batch after batch until nothing is due or an upload fails.

        A day's backlog (10,000 rows) leaves in one tick, not 20 rows a minute. Every row
        a pass sees ends sent, gone or backed off, so the next `due()` never returns it again.
        """
        sent = 0
        while True:
            rows = self.outbox.due(_BATCH)
            if not rows:
                break
            n, stopped = await self._pass(rows)
            sent += n
            if stopped:
                break
        self._maybe_prune()
        return sent

    async def _pass(self, rows: list[TrainingPackage]) -> tuple[int, bool]:
        """(rows sent, whether an upload failed and the drain must stop)."""
        sent = 0
        for row in rows:
            try:
                body = await asyncio.to_thread(_read_photo, Path(row.photo_path))
            except PhotoGone as exc:
                self.outbox.mark_gone(row.event_id, str(exc))
                logger.warning("Training photo %s (%s) skipped: %s", row.event_id, row.line_code, exc)
                continue
            except (OSError, ValueError) as exc:
                # Unreadable, not missing (permission, a directory in its place, a null byte in the path):
                # it may read next time, and it holds this row only.
                self.outbox.mark_error(row.event_id, str(exc), jenis=GAGAL_KONSOL)
                logger.warning("Training photo %s (%s) unreadable: %s", row.event_id, row.line_code, exc)
                continue
            try:
                photo_key, manifest_key, manifest_body = _objects(row, body)
            except Exception as exc:  # noqa: BLE001 : a damaged manifest holds its own row only
                self.outbox.mark_error(row.event_id, f"manifest: {exc!r}", jenis=GAGAL_KONSOL)
                logger.warning("Training photo %s (%s) manifest incomplete: %r", row.event_id, row.line_code, exc)
                continue
            try:
                await asyncio.to_thread(self._uploader.put_bytes, body, photo_key, content_type=PHOTO_CONTENT_TYPE)
                await asyncio.to_thread(
                    self._uploader.put_bytes, manifest_body, manifest_key, content_type=MANIFEST_CONTENT_TYPE
                )
            except Exception as exc:  # noqa: BLE001 : any upload failure: keep the row, stop the pass (D5)
                jenis = jenis_gagal_r2(exc)
                self.outbox.mark_error(row.event_id, str(exc), jenis=jenis)
                logger.warning(
                    "R2 nexio inbox upload failed (%s), holding training photos (at %s, %s): %s",
                    jenis, row.event_id, row.line_code, exc,
                )
                return sent, True
            self.outbox.mark_sent(row.event_id)
            sent += 1
        return sent, False

    def _maybe_prune(self) -> None:
        now = self._clock()
        if now - self._last_prune >= _PRUNE_EVERY_S:
            self._last_prune = now
            self.outbox.prune(now)
