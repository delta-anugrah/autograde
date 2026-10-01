"""Lapor galat ke Discord (batch 3.5): dirakit dari `Settings`, dibaca layar support.

Mati total kalau `DISCORD_WEBHOOK_URL` kosong (bawaan): tidak ada berkas, handler, atau
worker, jadi PC pabrik yang `.env`-nya belum punya baris itu berperilaku persis seperti
sebelumnya. Alamat yang bukan `https://` dengan host dan port yang bisa dipakai (diperiksa
juga oleh httpx, yang nanti mengirimnya) juga mati, dan layar menyebutnya `url_salah`.
Antrean di disk yang tidak bisa dibuka (berkas rusak, disk tidak bisa ditulis) juga
mati, dengan keadaan `rusak`: konsol tetap menyala, cuma laporannya yang berhenti.
Alasan mati yang perlu tindakan dicatat SATU WARNING di sini, saat dirakit
(`console_deps.get_lapor_discord`, dihangatkan sesudah sink tab Log terpasang).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.config import Settings
from ..core.log_sink import SqliteLogHandler
from ..domain.kirim_discord import KEADAAN_RUSAK, KEADAAN_URL_SALAH, keadaan_lapor, url_webhook_sah
from ..repositories.lapor_discord_repository import LaporDiscordStore

logger = logging.getLogger(__name__)


@dataclass
class LaporDiscord:
    url: str
    store: LaporDiscordStore | None
    #: Kenapa antrean di disk tidak bisa dibuka walau alamatnya sah (fitur mati).
    rusak: str | None = None
    #: Alamat tidak bisa dipakai mengirim (awalan, host, port, atau ditolak httpx).
    url_salah: bool = False

    def ringkasan(self) -> dict[str, Any]:
        """`GET /api/console/dev/lapor-discord`. Alamat webhook tidak pernah ikut."""
        if self.url_salah:
            return {"keadaan": KEADAAN_URL_SALAH}
        if self.rusak is not None:
            return {"keadaan": KEADAAN_RUSAK, "galat": self.rusak}
        isi = self.store.ringkasan() if self.store is not None else {}
        return {
            "keadaan": keadaan_lapor(self.url, isi.get("galat"), isi.get("status_http")),
            **isi,
        }


def rakit_lapor_discord(settings: Settings) -> LaporDiscord:
    url = settings.discord_webhook_url
    if not url:
        return LaporDiscord(url, None)
    if not url_webhook_sah(url) or not _diterima_httpx(url):
        logger.warning(
            "DISCORD_WEBHOOK_URL bukan alamat https:// yang bisa dipakai, lapor ke Discord MATI. "
            "Salin ulang alamat webhook dari Discord ke .env PC ini lalu autograde restart."
        )
        return LaporDiscord(url, None, url_salah=True)
    jalur = settings.lapor_discord_db_path
    try:
        return LaporDiscord(url, LaporDiscordStore(jalur))
    except (sqlite3.Error, OSError) as exc:
        logger.warning(
            "Antrean lapor Discord %s tidak bisa dibuka (%s: %s), lapor ke Discord MATI. "
            "Galat tetap tercatat di tab Log. Pindahkan berkas state/console/lapor_discord.db "
            "di folder autograde PC ini, lalu autograde restart.",
            jalur, type(exc).__name__, exc,
        )
        return LaporDiscord(url, None, rusak=f"{jalur.name} tidak bisa dibuka ({type(exc).__name__})")


def _diterima_httpx(url: str) -> bool:
    """httpx yang nanti mengirimnya menerima alamat ini (tanpa jaringan).

    `ValueError` ikut ditangkap: host IDNA yang tidak bisa didekode (`https://xn--a.com`)
    melempar `idna.InvalidCodepoint`, turunan `ValueError`, bukan `httpx.InvalidURL`, dan
    ini dipanggil saat lifespan konsol: yang lolos di sini membuat konsol gagal menyala."""
    try:
        return bool(httpx.URL(url).host)
    except (httpx.InvalidURL, ValueError):
        return False


class _HandlerLapor(SqliteLogHandler):
    """`SqliteLogHandler` TANPA kunci handler, dengan keluhan stderr sendiri.

    `logging.Handler.handle()` memegang kunci handler sepanjang `emit`, dan `emit` di sini
    menunggu kunci store. Thread yang sedang di dalam `LaporDiscordStore.susun` (memegang
    kunci store) lalu mencatat ERROR akan menunggu kunci handler milik thread pertama:
    dua thread saling menunggu selamanya. Store sudah menyerialkan dirinya sendiri, jadi
    kunci handler tidak melindungi apa pun di sini.
    """

    KELUHAN = (
        "Discord report queue could not be written; faults still reach the Log tab"
        " but not the Discord digest"
    )

    def createLock(self) -> None:
        self.lock = None


def pasang_handler_lapor(store: LaporDiscordStore) -> SqliteLogHandler:
    """Semua ERROR/CRITICAL konsol ikut antre ke ringkasan. WARNING tidak.

    Dikembalikan supaya lifespan melepasnya saat konsol berhenti.
    """
    handler = _HandlerLapor(store)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)
    return handler
