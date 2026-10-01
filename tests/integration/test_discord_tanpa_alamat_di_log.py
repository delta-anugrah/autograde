"""Alamat webhook Discord tidak pernah tertulis di mana pun (batch 3.1 + 3.5, aturan 33 dan 34).

Alamat webhook itu rahasia: siapa pun yang memegangnya bisa menulis ke kanal support.
Batch 3.1 memberi konsol keluaran proses (`docker logs`) di INFO, dan httpx menulis tiap
permintaan di INFO LENGKAP dengan alamatnya (`HTTP Request: POST https://discord.com/
api/webhooks/<id>/<token> ...`). `configure_logging` membatasi `httpx`/`httpcore` di
WARNING (ruling R4); test ini menjaga batas itu bersama pengirim Discord yang ASLI.

Komponen sungguhan: `configure_logging` konsol + `SqliteLogHandler` tab Log, handler
ERROR lapor Discord (`pasang_handler_lapor`) + `LaporDiscordStore`, `LaporDiscordWorker`
+ `DiscordClient` lewat `httpx.MockTransport` (Discord tidak pernah dipanggil). Tiga
jawaban Discord: jaringan putus, 404 (webhook dihapus), lalu 204 (terkirim).
"""
from __future__ import annotations

import asyncio
import logging
import time
from zoneinfo import ZoneInfo

import httpx

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.core.logging import KONTEKS_KONSOL, configure_logging
from palmgrade.domain.kirim_discord import JEDA_DITOLAK_S
from palmgrade.integrations.notifications.discord_client import DiscordClient
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.lapor_discord import pasang_handler_lapor
from palmgrade.workers.lapor_discord_worker import LaporDiscordWorker

URL = "https://discord.com/api/webhooks/1/token-palsu"
RAHASIA = ("webhooks/", "token-palsu")


class _Jam:
    """Mulai di jam dinding: handler log mencap kejadian dengan `time.time()` asli."""

    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


def _isi_berkas(folder, awalan: str) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(folder.glob(f"{awalan}*")))


def test_alamat_webhook_tidak_tertulis_di_stderr_tab_log_atau_antrean_discord(tmp_path, capsys):
    jam = _Jam()
    log_store = LogStore(tmp_path / "log_kejadian.db")
    lapor = LaporDiscordStore(tmp_path / "lapor_discord.db", jam=jam)
    jawaban: list[int | None] = [None, 404, 204]      # None = jaringan putus
    diminta: list[str] = []

    def discord(req: httpx.Request) -> httpx.Response:
        diminta.append(str(req.url))
        kode = jawaban.pop(0)
        if kode is None:
            # Teks exception httpx bisa memuat alamatnya; `DiscordClient` harus membuangnya.
            raise httpx.ConnectError(f"tidak bisa menyambung ke {req.url}", request=req)
        return httpx.Response(kode)

    kirim = LaporDiscordWorker(
        lapor, DiscordClient(URL, transport=httpx.MockTransport(discord)),
        identitas="PT Uji (host pc-uji)", versi="v9.9.9", zona=ZoneInfo("Asia/Jakarta"), jam=jam,
    )
    # DEBUG: semua yang bisa ditulis paket ini ikut keluar, jadi batas httpx diuji paling keras.
    pemasangan = configure_logging(
        konteks=KONTEKS_KONSOL, zona="Asia/Jakarta", level="DEBUG",
        handler_tambahan=(SqliteLogHandler(log_store),),
    )
    handler_lapor = pasang_handler_lapor(lapor)
    layar_support: list[str] = []                       # yang dibaca GET /api/console/dev/lapor-discord
    try:
        logging.getLogger("palmgrade.uji.konsol").error("AutoERP menolak kunjungan")
        for _ in range(3):
            jam.t += JEDA_DITOLAK_S + 1                 # lewat jeda kumpul, mundur, dan ditolak
            asyncio.run(kirim.run_once())
            layar_support.append(str(lapor.ringkasan()))
    finally:
        logging.getLogger().removeHandler(handler_lapor)
        pemasangan.lepas()

    err = capsys.readouterr().err
    # Menjaga penjaganya: alamatnya benar-benar dipakai tiga kali, dan stderr memang tertangkap.
    assert diminta == [URL, URL, URL] and jawaban == []
    assert "AutoERP menolak kunjungan" in err
    assert "Lapor Discord tertahan" in err and "Lapor Discord terkirim lagi" in err
    for rahasia in RAHASIA:
        assert rahasia not in err, err

    baris = log_store.read(level=None, search=None, limit=100, offset=0)["items"]
    assert {"AutoERP menolak kunjungan", "Lapor Discord terkirim lagi"} <= {b["message"] for b in baris}
    assert "ConnectError" in layar_support[0] and "HTTP 404" in layar_support[1]
    for rahasia in RAHASIA:
        assert all(rahasia not in f"{b['message']} {b['detail']}" for b in baris), baris
        assert all(rahasia not in teks for teks in layar_support), layar_support
        assert rahasia.encode() not in _isi_berkas(tmp_path, "log_kejadian.db")
        assert rahasia.encode() not in _isi_berkas(tmp_path, "lapor_discord.db")
