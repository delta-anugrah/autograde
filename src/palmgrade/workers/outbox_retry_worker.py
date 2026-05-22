from __future__ import annotations

import datetime
import json
import logging
import time

import httpx

from ..core.config import Settings
from ..integrations.outbox.outbox_store import OutboxStore
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 1
_REQUEST_TIMEOUT = 5


class OutboxRetryWorker:
    def __init__(self, outbox: OutboxStore, settings: Settings, state: RuntimeState) -> None:
        self.outbox = outbox
        self.settings = settings
        self.state = state
        self._client = httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": settings.webhook_secret,
        }

    def run_loop(self) -> None:
        logger.info("OutboxRetryWorker started — target: %s", self.settings.canonical_events_url)
        while True:
            try:
                self._flush_pending()
            except Exception:
                logger.exception("OutboxRetryWorker unhandled error")
            time.sleep(_POLL_INTERVAL)

    def _flush_pending(self) -> None:
        if not self.settings.enable_webhook:
            return
        pending = self.outbox.get_pending(limit=20)
        if not pending:
            return

        url = self.settings.canonical_events_url
        for row in pending:
            try:
                payload = json.loads(row["payload"])
                res = self._client.post(url, json=payload, headers=self._headers)
                if res.status_code in (200, 201) or "already_processed" in res.text:
                    self.outbox.mark_delivered(row["id"])
                    self.state.last_successful_api_push = datetime.datetime.now().isoformat()
                    logger.debug("Outbox delivered event %s (status=%s)", row["event_id"], res.status_code)
                else:
                    self.outbox.mark_failed_attempt(row["id"], f"HTTP {res.status_code}: {res.text[:200]}")
                    logger.warning("Outbox delivery failed %s: HTTP %s", row["event_id"], res.status_code)
            except Exception as exc:
                self.outbox.mark_failed_attempt(row["id"], str(exc)[:500])
                logger.warning("Outbox delivery error %s: %s", row["event_id"], exc)
