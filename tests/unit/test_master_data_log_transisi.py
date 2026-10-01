"""Master data offline seharian = satu baris, bukan ±288 ERROR bertraceback (batch 3.3).

Tarikan tiap 5 menit lebih lama dari jendela gabung tab Log (60 detik), jadi dulu
tiap tarikan yang gagal jadi baris sendiri, lengkap dengan traceback.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from palmgrade.integrations.erp.client import ErpClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.workers import master_data_worker as modul
from palmgrade.workers.master_data_worker import MasterDataWorker


class _Erp:
    """Keadaan AutoERP palsu: `mode` = "hidup" | "jaringan" | "ditolak"."""

    def __init__(self) -> None:
        self.mode = "hidup"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "jaringan":
            raise httpx.ConnectError("[Errno 113] No route to host")
        if self.mode == "ditolak":
            return httpx.Response(403, json={"exc_type": "PermissionError"})
        return httpx.Response(200, json={"data": []})


class _Jam:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def _worker(tmp_path, erp: _Erp, jam: _Jam) -> MasterDataWorker:
    client = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(erp))
    return MasterDataWorker(ConsoleStore(tmp_path / "console.db"), client, interval_s=300, jam=jam)


def _log(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == modul.logger.name and r.levelno >= logging.WARNING]


def _tarik(worker: MasterDataWorker, jam: _Jam, n: int) -> None:
    for _ in range(n):
        asyncio.run(worker.run_once())
        jam.t += 300


def test_offline_sehari_satu_warning_tanpa_traceback_lalu_satu_saat_pulih(tmp_path, caplog):
    erp, jam = _Erp(), _Jam()
    worker = _worker(tmp_path, erp, jam)
    with caplog.at_level(logging.DEBUG, logger=modul.logger.name):
        erp.mode = "jaringan"
        _tarik(worker, jam, 288)
        erp.mode = "hidup"
        _tarik(worker, jam, 2)
    catatan = _log(caplog)
    assert len(catatan) == 2
    assert "(jaringan)" in catatan[0].getMessage() and catatan[0].exc_info is None
    assert catatan[1].getMessage() == "Master data tertarik lagi dari AutoERP sesudah 24 jam gagal"


def test_galat_bukan_jaringan_satu_error_dengan_traceback(tmp_path, caplog):
    erp, jam = _Erp(), _Jam()
    worker = _worker(tmp_path, erp, jam)
    erp.mode = "ditolak"
    with caplog.at_level(logging.WARNING, logger=modul.logger.name):
        _tarik(worker, jam, 10)
    [catatan] = _log(caplog)
    assert catatan.levelno == logging.ERROR and catatan.exc_info is not None


def test_jenis_galat_berganti_di_tengah_kejadian_ditulis_lagi(tmp_path, caplog):
    """Jaringan putus lalu kunci ditolak: yang kedua butuh tindakan lain."""
    erp, jam = _Erp(), _Jam()
    worker = _worker(tmp_path, erp, jam)
    with caplog.at_level(logging.WARNING, logger=modul.logger.name):
        erp.mode = "jaringan"
        _tarik(worker, jam, 3)
        erp.mode = "ditolak"
        _tarik(worker, jam, 3)
    assert [r.levelname for r in _log(caplog)] == ["WARNING", "ERROR"]


def test_tarikan_tanpa_perubahan_tidak_menulis_info(tmp_path, caplog):
    erp, jam = _Erp(), _Jam()
    with caplog.at_level(logging.INFO, logger=modul.logger.name):
        _tarik(_worker(tmp_path, erp, jam), jam, 3)
    assert not [r for r in caplog.records if "rows applied" in r.getMessage() and r.levelno >= logging.INFO]
