"""Queues one training package per bunch for the nexio inbox (nexio spec §6.1).

Called from `ConsoleService._ingest` on a bunch's FIRST arrival only. It never raises:
an exception in `_ingest` would make the line retry the event every 10 minutes forever,
and the bunch is already counted. A package that fails to queue is logged and lost for
training, which costs one photo and nothing the mill is paid on.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..domain.training_sample import SEND_PRIORITY, build_manifest, photo_path
from ..integrations.upload.training_outbox_store import TrainingOutboxStore

logger = logging.getLogger(__name__)


class TrainingInbox:
    def __init__(
        self,
        outbox: TrainingOutboxStore,
        *,
        artifacts_dir: Path,
        company: str,
        autograde_version: str,
        send_mode: str,
        low_confidence: float,
    ) -> None:
        self.outbox = outbox
        self._artifacts_dir = artifacts_dir
        self._company = company
        self._autograde_version = autograde_version
        self._send_mode = send_mode
        self._low_confidence = low_confidence

    def offer(self, payload: dict[str, Any], *, line_code: str, plate: str | None) -> bool:
        """True when a package was queued. Never raises."""
        try:
            manifest = build_manifest(
                payload,
                line_code=line_code,
                plate=plate,
                company=self._company,
                autograde_version=self._autograde_version,
                low_confidence=self._low_confidence,
            )
            if self._send_mode == SEND_PRIORITY and not manifest["priority"]["reasons"]:
                return False
            photo = photo_path(self._artifacts_dir, line_code, payload.get("image_path"))
            if photo is None:
                logger.debug("Janjang %s tanpa foto clean, tidak dikirim ke nexio", payload.get("event_id"))
                return False
            return self.outbox.enqueue(manifest["event_id"], line_code, str(photo), manifest)
        except Exception:
            logger.exception("Foto training janjang %s gagal masuk antrean nexio", payload.get("event_id"))
            return False
