"""Log line sampai ke `event_log` konsol lewat komponen SUNGGUHAN (batch 3.2).

Line: `SqliteLogHandler` → `AntreanLogLine` → `LogLineStore` → router `/internal/log`
di balik penjaga `INTERNAL_SECRET` (dan gerbang lisensi). Konsol: `LineClient` →
`TarikLogLineWorker` → `LogStore`. Disambung transport ASGI in-process, berkas SQLite
di folder sementara. Restart line dan konsol = objek dibuat ulang di atas berkas yang sama.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import replace
from pathlib import Path

from antrean_line_rakit import LinePerPort
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.license.guard import LicenseGuardMiddleware
from palmgrade.license.types import EffectiveLicense
from palmgrade.repositories.log_line_repository import LogLineStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.internal_log import buat_router
from palmgrade.services.antrean_log_line import AntreanLogLine, pasang_penulis_log_line
from palmgrade.services.penutup_line import PenutupLine
from palmgrade.workers.tarik_log_line_worker import TarikLogLineWorker

SECRET = "kunci-internal-palsu"
LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _Lisensi:
    def __init__(self, habis: bool) -> None:
        self.habis = habis

    async def get_effective_license(self) -> EffectiveLicense:
        return EffectiveLicense(
            status="EXPIRED" if self.habis else "ACTIVE", reason="uji", payload=None, warning=None
        )


class LineLog:
    """Satu proses line: berkas log di `folder`, handler asli, router asli."""

    def __init__(self, folder: Path, *, secret: str = SECRET, lisensi_habis: bool | None = None) -> None:
        self.store = LogLineStore(folder / "log_line.db")
        self.antrean = AntreanLogLine(self.store)
        self.logger = logging.getLogger(f"uji.line.{id(self)}")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.addHandler(SqliteLogHandler(self.antrean))
        settings = replace(Settings(), internal_secret=secret)
        self.app = FastAPI()
        self.app.include_router(buat_router(settings=lambda: settings, store=lambda: self.store))
        if lisensi_habis is not None:
            self.app.add_middleware(LicenseGuardMiddleware, manager=_Lisensi(lisensi_habis))

            @self.app.get("/internal/status")
            def status() -> dict:
                return {"ok": True}

    def error(self, pesan: str) -> None:
        try:
            raise RuntimeError(pesan)
        except RuntimeError:
            self.logger.exception(pesan)
        self.antrean.kuras()


def _worker(line_app: FastAPI | None, log_store: LogStore) -> TarikLogLineWorker:
    apps = {8001: line_app} if line_app is not None else {}
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort(apps),
    )
    return TarikLogLineWorker([LINE_1], klien, log_store)


def _baris(log_store: LogStore) -> list[dict]:
    return log_store.read(level=None, search=None, limit=100, offset=0)["items"]


def test_galat_line_sampai_ke_tab_log_dengan_traceback_dan_tag_line(tmp_path):
    line = LineLog(tmp_path / "line-1")
    log_store = LogStore(tmp_path / "log.db")
    line.error("grab kamera gagal")

    asyncio.run(_worker(line.app, log_store).run_once())

    (b,) = _baris(log_store)
    assert (b["line_code"], b["level"], b["message"]) == ("line-1", "ERROR", "grab kamera gagal")
    assert "RuntimeError: grab kamera gagal" in b["detail"]


def test_galat_sebelum_restart_line_tetap_sampai_sesudahnya(tmp_path):
    """Inti 3.2: container line dibuat ulang (docker logs kosong), berkasnya tetap."""
    LineLog(tmp_path / "line-1").error("sebelum restart")
    log_store = LogStore(tmp_path / "log.db")

    line_baru = LineLog(tmp_path / "line-1")  # proses line baru, berkas yang sama
    line_baru.error("sesudah restart")
    asyncio.run(_worker(line_baru.app, log_store).run_once())

    assert sorted(b["message"] for b in _baris(log_store)) == ["sebelum restart", "sesudah restart"]


def test_konsol_mati_lalu_restart_tidak_ganda_dan_tidak_hilang(tmp_path):
    line = LineLog(tmp_path / "line-1")
    line.error("satu")
    asyncio.run(_worker(line.app, LogStore(tmp_path / "log.db")).run_once())

    line.error("dua")  # konsol mati saat ini terjadi
    line.error("satu")  # berulang: hitungan baris lama naik di line
    konsol_baru = LogStore(tmp_path / "log.db")
    asyncio.run(_worker(line.app, konsol_baru).run_once())
    asyncio.run(_worker(line.app, konsol_baru).run_once())

    hasil = {b["message"]: b["count"] for b in _baris(konsol_baru)}
    assert hasil == {"satu": 2, "dua": 1}


def test_log_line_direset_tidak_melewatkan_baris_baru(tmp_path):
    folder = tmp_path / "line-1"
    line = LineLog(folder)
    for i in range(3):
        line.error(f"lama {i}")
    log_store = LogStore(tmp_path / "log.db")
    asyncio.run(_worker(line.app, log_store).run_once())

    for berkas in folder.iterdir():
        berkas.unlink()
    line_reset = LineLog(folder)
    line_reset.error("baru sesudah reset")
    asyncio.run(_worker(line_reset.app, log_store).run_once())

    assert "baru sesudah reset" in {b["message"] for b in _baris(log_store)}


def test_line_versi_lama_tanpa_rute_tidak_mengisi_apa_pun_dan_tidak_melempar(tmp_path):
    log_store = LogStore(tmp_path / "log.db")

    asyncio.run(_worker(FastAPI(), log_store).run_once())

    assert _baris(log_store) == []


def test_line_mati_tidak_melempar(tmp_path):
    log_store = LogStore(tmp_path / "log.db")
    asyncio.run(_worker(None, log_store).run_once())
    assert _baris(log_store) == []


def test_kunci_konsol_salah_ditolak_line(tmp_path):
    line = LineLog(tmp_path / "line-1", secret="kunci-lain")
    line.error("rahasia line")
    log_store = LogStore(tmp_path / "log.db")

    asyncio.run(_worker(line.app, log_store).run_once())

    assert _baris(log_store) == []


def test_log_tetap_bisa_ditarik_saat_lisensi_habis(tmp_path):
    """Saat lisensi menghentikan line, lane lain 403 tapi log line tetap terbaca."""
    line = LineLog(tmp_path / "line-1", lisensi_habis=True)
    line.error("lisensi habis, deteksi berhenti")
    log_store = LogStore(tmp_path / "log.db")

    asyncio.run(_worker(line.app, log_store).run_once())

    assert [b["message"] for b in _baris(log_store)] == ["lisensi habis, deteksi berhenti"]
    assert TestClient(line.app).get("/internal/status").status_code == 403  # gerbangnya memang aktif


def test_pesan_terakhir_sebelum_restart_dari_konsol_sudah_di_disk_saat_keluar(tmp_path):
    """Restart dan hapus data dari konsol keluar lewat `os._exit` (tanpa `atexit`):
    antrean log dikuras sebelum itu, jadi pesan keluar terakhir line sudah di
    `log_line.db` tepat saat proses berhenti, dan konsol menariknya sesudah restart."""
    folder = tmp_path / "line-1"
    folder.mkdir()
    di_disk_saat_keluar: list[str] = []
    keluar = threading.Event()
    penulis = pasang_penulis_log_line(folder)
    assert penulis is not None

    def os_exit_palsu(_kode: int) -> None:
        halaman = penulis.store.ambil(setelah=0, generasi="", batas=100)
        di_disk_saat_keluar.extend(e["message"] for e in halaman["entri"])
        keluar.set()

    try:
        penutup = PenutupLine(batas_s=1, keluar=os_exit_palsu, tidur=lambda _s: None)
        penutup.sebelum_keluar(penulis.hentikan)
        penutup.keluar_nanti(0)
        assert keluar.wait(5)
    finally:
        penulis.hentikan()

    pesan_keluar = "Keluar atas permintaan konsol, menunggu dinyalakan ulang"
    assert pesan_keluar in di_disk_saat_keluar
    log_store = LogStore(tmp_path / "log.db")
    asyncio.run(_worker(LineLog(folder).app, log_store).run_once())
    assert pesan_keluar in {b["message"] for b in _baris(log_store)}
