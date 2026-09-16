"""Uploads one JSON per truck visit to R2, through its own queue.

Why a queue: the uplink drops, the PC loses power, and a truck graded during
either must still get its manifest afterwards — same reasoning as the AutoERP
outbox. Why its own DB file: R2 being down must not hold AutoERP messages, and
the other way round.

`detail_url` was already sent to AutoERP with a URL derived from the visit id,
so this worker running late only means the page shows "belum terunggah" until
it catches up.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ..domain.visit_manifest import MANIFEST_KIND, VIEWER_KEY, build_manifest, manifest_key
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

_INTERVAL_S = 30
_BATCH = 20


class Uploader(Protocol):
    def put_bytes(self, body: bytes, r2_key: str, *, content_type: str) -> None: ...


class VisitManifestWorker:
    def __init__(
        self,
        store: ConsoleStore,
        outbox: ErpOutboxStore,
        uploader: Uploader,
        *,
        public_url: str,
        viewer_html: Path,
        clock: Callable[[], str],
        interval_s: int = _INTERVAL_S,
    ) -> None:
        self._store = store
        self.outbox = outbox
        self._uploader = uploader
        self._public_url = public_url
        self._viewer_html = viewer_html
        self._clock = clock
        self._interval_s = interval_s
        self._viewer_uploaded = False

    def enqueue(self, weighing_id: str, assignment_id: str) -> None:
        self.outbox.enqueue(MANIFEST_KIND, weighing_id, {"assignment_id": assignment_id})

    async def run_loop(self) -> None:
        logger.info("VisitManifestWorker started, every %ss", self._interval_s)
        while True:
            try:
                await self.drain_once()
            except Exception:
                logger.exception("Manifest drain failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    async def drain_once(self) -> int:
        uploaded = 0
        for message in self.outbox.due(_BATCH):
            body = self._build(message.key, message.payload)
            if body is None:
                # Nothing graded under that assignment: no page to make, and no
                # amount of retrying changes that.
                self.outbox.mark_sent(message)
                continue
            try:
                await asyncio.to_thread(self._put_viewer_once)
                await asyncio.to_thread(
                    self._uploader.put_bytes, body, manifest_key(message.key), content_type="application/json"
                )
            except Exception as exc:  # noqa: BLE001 — any transport failure: keep the row
                logger.warning("R2 unreachable, holding manifests: %s", exc)
                self.outbox.mark_error(message, str(exc))
                break
            self.outbox.mark_sent(message)
            uploaded += 1
        return uploaded

    def _build(self, weighing_id: str, payload: dict[str, Any]) -> bytes | None:
        visit = self._store.visit(weighing_id)
        grading = self._store.grading_counts(payload["assignment_id"])
        if not visit or not grading:
            return None
        bunches = self._store.bunches_for_assignment(payload["assignment_id"])
        manifest = build_manifest(visit, grading, bunches, public_url=self._public_url, generated_at=self._clock())
        return json.dumps(manifest, ensure_ascii=False).encode("utf-8")

    def _put_viewer_once(self) -> None:
        """The page that reads the manifests — shipped with the console so the
        two can never drift apart. Idempotent overwrite, once per process."""
        if self._viewer_uploaded:
            return
        self._uploader.put_bytes(self._viewer_html.read_bytes(), VIEWER_KEY, content_type="text/html; charset=utf-8")
        self._viewer_uploaded = True
