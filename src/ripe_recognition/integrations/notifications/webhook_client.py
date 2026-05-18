from __future__ import annotations

import logging
from typing import Any

import httpx

from ...core.config import Settings

logger = logging.getLogger(__name__)


class WebhookClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_quality_event(self, payload: dict[str, Any]) -> bool:
        if not self.settings.enable_webhook:
            return False

        url = self.settings.webhook_url
        headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": self.settings.webhook_secret,
        }
        print(f"Sending webhook to {url} with data: {payload}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                res.raise_for_status()
                print(f"Webhook sent ({res.status_code})")
                return True
        except Exception as e:
            logger.debug("Webhook server unavailable, skipped sending.")
            print(f"Error sending webhook: {e}")
            return False
