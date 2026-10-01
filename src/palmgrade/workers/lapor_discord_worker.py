"""Susun ringkasan galat dan kirim ke Discord saat internet ada (batch 3.5).

Jalan di loop asyncio konsol tiap 30 detik: susun ringkasan kalau waktunya
(`domain/kirim_discord.boleh_susun`), lalu kirim pesan yang menunggu, paling tua dulu.
Aturan jeda dan arti jawaban Discord hidup di `domain/kirim_discord.py`.

Worker ini TIDAK PERNAH menulis ERROR: handler lapor menangkap semua ERROR konsol, dan
Discord yang mati akan melaporkan kematiannya sendiri ke antrean yang tidak bisa
terkirim, selamanya. Tiap perubahan JENIS kegagalan (jaringan/5xx, webhook ditolak, isi
ditolak) satu WARNING dengan sarannya sendiri, dan pulihnya satu WARNING, seperti Last
Sync: internet yang putus lalu webhook yang ternyata dihapus tetap memberi saran
memeriksa webhook. Pesan yang isinya ditolak Discord `MAKS_ISI_DITOLAK` kali disisihkan
(tetap di disk) dengan satu WARNING, supaya ringkasan berikutnya tidak ikut tertahan.
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
    MAKS_ISI_DITOLAK,
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

_SARAN = {
    NasibDiscord.ULANG: "Pesan tidak dibuang, dikirim otomatis begitu internet ada.",
    NasibDiscord.DITOLAK: (
        "Pesan tidak dibuang, periksa DISCORD_WEBHOOK_URL di .env PC ini lalu autograde restart."
    ),
    NasibDiscord.ISI_DITOLAK: (
        f"Discord menolak isi pesannya, bukan alamatnya; pesan yang {MAKS_ISI_DITOLAK} kali "
        "ditolak disisihkan (tetap di disk) supaya laporan berikutnya jalan."
    ),
}


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
        #: Jenis kegagalan yang sudah diperingatkan dan belum pulih; None = sehat.
        self._jenis_gagal: NasibDiscord | None = None

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
            await self._gagal(kiriman.id, f"Discord tidak terjangkau ({exc})", None, NasibDiscord.ULANG)
            return False
        putusan = nilai_jawaban_discord(jawab.status, jawab.retry_after)
        if putusan.nasib is NasibDiscord.TERKIRIM:
            await asyncio.to_thread(self._store.tandai_terkirim, kiriman.id, now=self._jam())
            self._pulih()
            return True
        if putusan.nasib is NasibDiscord.TUNGGU:
            self._coba_lagi_at = self._jam() + putusan.tunggu_s
            return False
        await self._gagal(kiriman.id, f"Discord menjawab HTTP {jawab.status}", jawab.status, putusan.nasib)
        if putusan.nasib is NasibDiscord.DITOLAK:
            self._coba_lagi_at = self._jam() + putusan.tunggu_s
        elif putusan.nasib is NasibDiscord.ISI_DITOLAK and kiriman.isi_ditolak + 1 >= MAKS_ISI_DITOLAK:
            # Cuma penolakan ISI yang dihitung, bukan `percobaan` (yang ikut menghitung
            # kegagalan jaringan): layar dan aturan 34 menjanjikan "3 kali ditolak".
            await asyncio.to_thread(self._store.sisihkan, kiriman.id, now=self._jam())
            self._coba_lagi_at = 0.0
            logger.warning(
                "Satu pesan lapor Discord disisihkan sesudah %d kali ditolak isinya (HTTP %s). "
                "Pesannya tetap di state/console/lapor_discord.db dan tidak dikirim lagi; "
                "laporan berikutnya jalan terus.",
                MAKS_ISI_DITOLAK, jawab.status,
            )
        return False

    async def _gagal(
        self, kiriman_id: int, galat: str, status_http: int | None, jenis: NasibDiscord
    ) -> None:
        now = self._jam()
        await asyncio.to_thread(
            self._store.tandai_gagal, kiriman_id, galat=galat, status_http=status_http, now=now,
            isi_ditolak=jenis is NasibDiscord.ISI_DITOLAK,
        )
        self._gagal_beruntun += 1
        self._coba_lagi_at = now + jeda_mundur(
            self._gagal_beruntun, dasar=JEDA_GAGAL_DASAR_S, maks=JEDA_GAGAL_MAKS_S
        )
        if jenis is not self._jenis_gagal:
            self._jenis_gagal = jenis
            logger.warning("Lapor Discord tertahan: %s. %s", galat, _SARAN[jenis])

    def _pulih(self) -> None:
        self._gagal_beruntun = 0
        self._coba_lagi_at = 0.0
        if self._jenis_gagal is not None:
            self._jenis_gagal = None
            logger.warning("Lapor Discord terkirim lagi")

    async def run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001, WARNING, bukan ERROR (lihat docstring modul)
                logger.warning("Putaran lapor Discord gagal", exc_info=True)
            await asyncio.sleep(self._interval_s)
