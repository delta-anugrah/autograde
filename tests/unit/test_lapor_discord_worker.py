"""`LaporDiscordWorker` (batch 3.5): store asli + `DiscordClient` asli lewat `httpx.MockTransport`.

Discord tidak pernah dipanggil. Jam disuntik, jadi jeda 15 menit dan sejam diuji tanpa tidur.
"""
from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

import httpx

from palmgrade.domain.digest_galat import MAKS_PESAN
from palmgrade.domain.kirim_discord import JEDA_ANTAR_RINGKASAN_S, JEDA_DITOLAK_S, JEDA_KUMPUL_S
from palmgrade.integrations.notifications.discord_client import DiscordClient
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.workers.lapor_discord_worker import LaporDiscordWorker

URL = "https://discord.com/api/webhooks/1/token-palsu"


class _Jam:
    def __init__(self) -> None:
        self.t = 1_790_000_000.0

    def __call__(self) -> float:
        return self.t


class _Discord:
    """Webhook palsu: jawaban bisa diganti, putus = ConnectError."""

    def __init__(self) -> None:
        self.status = 204
        self.putus = False
        self.badan: dict | None = None
        self.diterima: list[str] = []
        self.permintaan = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.permintaan += 1
        if self.putus:
            raise httpx.ConnectError("internet pabrik putus", request=req)
        if 200 <= self.status < 300:
            self.diterima.append(req.read().decode())
        return httpx.Response(self.status, json=self.badan) if self.badan else httpx.Response(self.status)


def _rakit(tmp_path, jam: _Jam, discord: _Discord) -> tuple[LaporDiscordWorker, LaporDiscordStore]:
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=jam)
    worker = LaporDiscordWorker(
        store,
        DiscordClient(URL, transport=httpx.MockTransport(discord)),
        identitas="PT Uji (host pc-uji)",
        versi="v9.9.9",
        zona=ZoneInfo("Asia/Jakarta"),
        jam=jam,
    )
    return worker, store


def _galat(store: LaporDiscordStore, jam: _Jam, pesan: str = "kamera putus") -> None:
    store.write("ERROR", "palmgrade.x", pesan, None, now=jam.t)


def test_galat_pertama_menunggu_jendela_kumpul_lalu_terkirim(tmp_path):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    _galat(store, jam)

    asyncio.run(worker.run_once())
    assert discord.permintaan == 0

    jam.t += JEDA_KUMPUL_S
    asyncio.run(worker.run_once())
    assert len(discord.diterima) == 1
    assert "PT Uji (host pc-uji)" in discord.diterima[0]
    assert "kamera putus" in discord.diterima[0]
    assert store.ringkasan()["kiriman"] == 0


def test_badai_galat_jadi_satu_ringkasan_dan_berikutnya_15_menit_lagi(tmp_path):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    for _ in range(50):
        _galat(store, jam)
    jam.t += JEDA_KUMPUL_S
    asyncio.run(worker.run_once())
    assert len(discord.diterima) == 1 and "50x" in discord.diterima[0]

    _galat(store, jam, "galat berikutnya")
    jam.t += JEDA_KUMPUL_S
    asyncio.run(worker.run_once())
    assert len(discord.diterima) == 1  # belum 15 menit

    jam.t += JEDA_ANTAR_RINGKASAN_S
    asyncio.run(worker.run_once())
    assert len(discord.diterima) == 2


def test_offline_semalam_satu_ringkasan_lama_lalu_satu_gabungan_tanpa_hilang(tmp_path):
    """Internet mati: ringkasan pertama menunggu, galat baru terus dihitung, tidak ada 96 pesan."""
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.putus = True
    _galat(store, jam, "sebelum putus")
    jam.t += JEDA_KUMPUL_S
    asyncio.run(worker.run_once())  # ringkasan pertama disusun, pengiriman gagal
    for _ in range(48):  # 12 jam, satu putaran tiap 15 menit
        _galat(store, jam, "selama putus")
        asyncio.run(worker.run_once())
        jam.t += 900
    assert store.ringkasan()["kiriman"] == 1
    assert store.ringkasan()["menunggu_kejadian"] == 48

    discord.putus = False
    jam.t += 3600
    asyncio.run(worker.run_once())  # ringkasan lama terkirim
    asyncio.run(worker.run_once())  # ringkasan gabungan disusun dan terkirim

    assert len(discord.diterima) == 2
    assert "sebelum putus" in discord.diterima[0]
    assert "48x" in discord.diterima[1]


def test_offline_berhari_hari_kiriman_tidak_pernah_tumbuh(tmp_path):
    """Carry B-T7 no. 4: `boleh_susun` cuma menyusun saat TIDAK ada pesan menunggu, jadi
    Discord tak terjangkau berhari-hari dengan galat baru yang berbeda tiap putaran tidak
    menumpuk tabel `kiriman`: paling banyak satu ringkasan (<= MAKS_PESAN bagian)."""
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.putus = True
    terbanyak = 0
    for putaran in range(3 * 24 * 4):  # 3 hari, satu putaran tiap 15 menit
        for i in range(40):  # 40 jenis panjang tiap putaran: satu ringkasan pun berbagian-bagian
            store.write("ERROR", f"palmgrade.modul_{i}", f"galat {'z' * 200} {putaran}", None, now=jam.t)
        asyncio.run(worker.run_once())
        terbanyak = max(terbanyak, store.ringkasan()["kiriman"])
        jam.t += 900

    assert 1 < terbanyak <= MAKS_PESAN
    assert store.ringkasan()["kiriman"] == terbanyak


def test_jaringan_putus_jeda_berlipat_bukan_berputar_cepat(tmp_path):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.putus = True
    _galat(store, jam)
    jam.t += JEDA_KUMPUL_S

    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())
    assert discord.permintaan == 1  # jeda 30 dtk belum lewat
    jam.t += 30
    asyncio.run(worker.run_once())
    jam.t += 30
    asyncio.run(worker.run_once())
    assert discord.permintaan == 2  # jeda kedua 60 dtk


def test_webhook_ditolak_404_berhenti_sejam_tampil_dan_satu_warning(tmp_path, caplog):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.status, discord.badan = 404, {"message": "Unknown Webhook"}
    _galat(store, jam)
    jam.t += JEDA_KUMPUL_S

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.lapor_discord_worker"):
        for _ in range(10):
            asyncio.run(worker.run_once())
            jam.t += 60
    assert discord.permintaan == 1
    r = store.ringkasan()
    assert (r["status_http"], r["kiriman"]) == (404, 1)
    peringatan = [x.getMessage() for x in caplog.records]
    assert peringatan == [
        "Lapor Discord tertahan: Discord menjawab HTTP 404. Pesan tidak dibuang, periksa "
        "DISCORD_WEBHOOK_URL di .env PC ini lalu autograde restart."
    ]
    assert not [x for x in caplog.records if x.levelno >= logging.ERROR]

    jam.t += JEDA_DITOLAK_S
    discord.status, discord.badan = 204, None
    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.lapor_discord_worker"):
        asyncio.run(worker.run_once())
    assert len(discord.diterima) == 1
    assert caplog.records[-1].getMessage() == "Lapor Discord terkirim lagi"


def test_429_menunggu_retry_after_tanpa_mencatat_gagal(tmp_path):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.status, discord.badan = 429, {"retry_after": 5}
    _galat(store, jam)
    jam.t += JEDA_KUMPUL_S

    asyncio.run(worker.run_once())
    jam.t += 4
    asyncio.run(worker.run_once())
    assert discord.permintaan == 1
    assert store.ringkasan()["galat"] is None

    discord.status, discord.badan = 204, None
    jam.t += 1
    asyncio.run(worker.run_once())
    assert len(discord.diterima) == 1


def test_ringkasan_panjang_terkirim_semua_bagian_berurutan(tmp_path):
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    for i in range(30):
        store.write("ERROR", f"palmgrade.modul_{i}", f"galat {'z' * 200} {i}", None, now=jam.t)
    jam.t += JEDA_KUMPUL_S

    asyncio.run(worker.run_once())

    assert len(discord.diterima) > 1
    assert '"(1/' in discord.diterima[0]
    assert store.ringkasan()["kiriman"] == 0


def test_worker_tidak_pernah_menulis_error_walau_discord_rusak(tmp_path, caplog):
    """Handler lapor menangkap SEMUA ERROR konsol: worker ini tidak boleh menambah ERROR sendiri."""
    jam, discord = _Jam(), _Discord()
    worker, store = _rakit(tmp_path, jam, discord)
    discord.status = 500
    _galat(store, jam)
    jam.t += JEDA_KUMPUL_S

    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            asyncio.run(worker.run_once())
            jam.t += 1000

    assert not [x for x in caplog.records if x.levelno >= logging.ERROR]
    assert store.ringkasan()["status_http"] == 500
