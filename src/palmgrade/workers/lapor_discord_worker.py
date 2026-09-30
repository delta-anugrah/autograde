"""Susun ringkasan galat dan kirim ke Discord saat internet ada (batch 3.5).

Jalan di loop asyncio konsol tiap 30 detik: susun ringkasan kalau waktunya
(`domain/kirim_discord.boleh_susun`), lalu kirim pesan yang menunggu, paling tua dulu.
Aturan jeda dan arti jawaban Discord hidup di `domain/kirim_discord.py`.

Worker ini TIDAK PERNAH menulis ERROR: handler lapor menangkap semua ERROR konsol, dan
Discord yang mati akan melaporkan kematiannya sendiri ke antrean yang tidak bisa
terkirim, selamanya. Putus dan pulih masing-masing SATU WARNING (tab Log), seperti
Last Sync.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from functools import partial
from typing import Protocol
from zoneinfo import ZoneInfo

from ..core.config import Settings
from ..domain.digest_galat import identitas_pabrik, susun_pesan
from ..domain.kirim_antrean_line import jeda_mundur
from ..domain.kirim_discord import (
    JEDA_GAGAL_DASAR_S,
    JEDA_GAGAL_MAKS_S,
    MAKS_KIRIM_PER_PUTARAN,
    NasibDiscord,
    boleh_susun,
    nilai_jawaban_discord,
)
from ..integrations.notifications.discord_client import (
    DiscordClient,
    DiscordTakTerjangkau,
    JawabanDiscord,
)
from ..repositories.lapor_discord_repository import LaporDiscordStore

logger = logging.getLogger(__name__)

INTERVAL_S = 30.0


class _Pengirim(Protocol):
    async def kirim(self, isi: str) -> JawabanDiscord: ...


class LaporDiscordWorker:
    def __init__(
        self,
        store: LaporDiscordStore,
        pengirim: _Pengirim,
        *,
        identitas: str,
        versi: str,
        zona: ZoneInfo,
        interval_s: float = INTERVAL_S,
        jam: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._pengirim = pengirim
        self._susun = partial(susun_pesan, identitas=identitas, versi=versi, zona=zona)
        self._interval_s = interval_s
        self._jam = jam
        self._coba_lagi_at = 0.0
        self._gagal_beruntun = 0
        self._putus = False

    @classmethod
    def dari_settings(cls, store: LaporDiscordStore, settings: Settings) -> LaporDiscordWorker:
        return cls(
            store,
            DiscordClient(settings.discord_webhook_url),
            identitas=identitas_pabrik(settings.erp_company, socket.gethostname()),
            versi=settings.app_version,
            zona=ZoneInfo(settings.factory_tz),
        )

    async def run_once(self) -> None:
        await asyncio.to_thread(self._susun_kalau_waktunya)
        for _ in range(MAKS_KIRIM_PER_PUTARAN):
            if self._jam() < self._coba_lagi_at or not await self._kirim_satu():
                return

    def _susun_kalau_waktunya(self) -> None:
        now = self._jam()
        if boleh_susun(
            sekarang=now,
            ada_kiriman=self._store.ada_kiriman(),
            tertua_masuk_at=self._store.tertua_masuk_at(),
            ringkasan_terakhir_at=self._store.ringkasan_terakhir_at(),
        ):
            self._store.susun(self._susun, now=now)

    async def _kirim_satu(self) -> bool:
        """Kirim pesan tertua. True kalau terkirim dan boleh lanjut ke berikutnya."""
        kiriman = await asyncio.to_thread(self._store.kiriman_berikut)
        if kiriman is None:
            return False
        try:
            jawab = await self._pengirim.kirim(kiriman.isi)
        except DiscordTakTerjangkau as exc:
            await self._gagal(kiriman.id, f"Discord tidak terjangkau ({exc})", None)
            return False
        putusan = nilai_jawaban_discord(jawab.status, jawab.retry_after)
        if putusan.nasib is NasibDiscord.TERKIRIM:
            await asyncio.to_thread(self._store.tandai_terkirim, kiriman.id, now=self._jam())
            self._pulih()
            return True
        if putusan.nasib is NasibDiscord.TUNGGU:
            self._coba_lagi_at = self._jam() + putusan.tunggu_s
            return False
        await self._gagal(kiriman.id, f"Discord menjawab HTTP {jawab.status}", jawab.status)
        if putusan.nasib is NasibDiscord.DITOLAK:
            self._coba_lagi_at = self._jam() + putusan.tunggu_s
        return False

    async def _gagal(self, kiriman_id: int, galat: str, status_http: int | None) -> None:
        now = self._jam()
        await asyncio.to_thread(
            self._store.tandai_gagal, kiriman_id, galat=galat, status_http=status_http, now=now
        )
        self._gagal_beruntun += 1
        self._coba_lagi_at = now + jeda_mundur(
            self._gagal_beruntun, dasar=JEDA_GAGAL_DASAR_S, maks=JEDA_GAGAL_MAKS_S
        )
        if not self._putus:
            self._putus = True
            saran = (
                "periksa DISCORD_WEBHOOK_URL di .env PC ini lalu autograde restart"
                if status_http is not None and 400 <= status_http < 500
                else "dikirim otomatis begitu internet ada"
            )
            logger.warning("Lapor Discord tertahan: %s. Pesan tidak dibuang, %s.", galat, saran)

    def _pulih(self) -> None:
        self._gagal_beruntun = 0
        self._coba_lagi_at = 0.0
        if self._putus:
            self._putus = False
            logger.warning("Lapor Discord terkirim lagi")

    async def run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001, WARNING, bukan ERROR (lihat docstring modul)
                logger.warning("Putaran lapor Discord gagal", exc_info=True)
            await asyncio.sleep(self._interval_s)
