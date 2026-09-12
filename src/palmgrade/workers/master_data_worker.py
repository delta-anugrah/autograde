"""Tarik master data (truk + supplier + Sumber TBS) dari cloud ke konsol.

Satu arah, cloud selalu menang (§3.4). Kontrak & header-nya persis yang dipakai
`palmgrade-api/src/services/edgeSync/edgeSync.service.impl.ts` — endpoint yang
sama, jendela tumpang tindih yang sama, dan respons JSON telanjang (tanpa
amplop `{status,data}`). Nol perubahan di sisi cloud.

`sumber` dibaca defensif: kolomnya baru ada setelah Fase 1 di PalmOS. Sebelum
itu nilainya None dan konsol menampilkan "—". Edge TIDAK PERNAH menentukan
sumber, cuma menampilkannya (§3.5b).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from ..core.config import Settings
from ..repositories.console_repository import ConsoleStore
from ..services.console_service import MASTER_CURSOR_KEY

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15
# Jam edge dan cloud tidak pernah sinkron sempurna; tanpa tumpang tindih, baris
# yang ditulis persis di detik batas tidak akan pernah ikut tarikan berikutnya.
_PULL_OVERLAP = timedelta(seconds=5)


class MasterDataWorker:
    def __init__(self, settings: Settings, store: ConsoleStore) -> None:
        self.settings = settings
        self.store = store

    async def run_loop(self) -> None:
        if not self.settings.upload_api_url:
            logger.info("MasterDataWorker off — UPLOAD_API_URL kosong")
            return
        logger.info("MasterDataWorker started — target: %s", self.settings.master_data_url)
        while True:
            try:
                await self.pull_once()
            except Exception:
                logger.exception("MasterDataWorker pull gagal — coba lagi tick berikutnya")
            await asyncio.sleep(self.settings.console_sync_interval_s)

    async def pull_once(self) -> int:
        cursor = self.store.get_state(MASTER_CURSOR_KEY)
        params = {}
        if cursor:
            params["updated_since"] = (
                datetime.fromisoformat(cursor.replace("Z", "+00:00")) - _PULL_OVERLAP
            ).isoformat()

        headers = {"x-webhook-secret": self.settings.upload_api_secret}
        if self.settings.lic_token:
            # Identitas pabrik. Tanpa ini cloud menahan sebagian payload.
            headers["x-license-token"] = self.settings.lic_token

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            res = await client.get(self.settings.master_data_url, params=params, headers=headers)
        res.raise_for_status()
        return self.apply(res.json())

    def apply(self, data: dict) -> int:
        """Terapkan satu respons master-data. Return jumlah baris yang mendarat."""
        applied = 0
        failed = False
        for supplier in data.get("suppliers") or []:
            try:
                self.store.upsert_supplier(supplier)
                applied += 1
            except Exception:
                logger.exception("Supplier gagal disimpan: %s", supplier.get("id"))
                failed = True
        for truck in data.get("trucks") or []:
            try:
                self.store.upsert_truck(truck)
                applied += 1
            except Exception:
                logger.exception("Truk gagal disimpan: %s", truck.get("id"))
                failed = True

        # Kursor hanya maju kalau SEMUA baris mendarat. Melewati satu baris yang
        # gagal berarti pabrik terjebak selamanya di matriks setengah basi —
        # termasuk pencabutan truk yang sudah dilakukan cloud.
        server_time = data.get("server_time")
        if not failed and server_time:
            self.store.set_state(MASTER_CURSOR_KEY, server_time)
        logger.info("Master data: %s baris diterapkan (failed=%s)", applied, failed)
        return applied
