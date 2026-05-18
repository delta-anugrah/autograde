from __future__ import annotations

import httpx


class SyncClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def fetch_latest(self, device_id: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{self._base_url}/license/sync",
                json={"device_id": device_id},
                headers={
                    "content-type": "application/json",
                    "x-api-key": self._api_key,
                },
            )
            res.raise_for_status()
            return res.json()["token_jws"]
