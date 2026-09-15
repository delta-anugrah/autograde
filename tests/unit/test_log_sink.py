"""Logging handler that bridges `logging` records into `LogStore`.

Covers: only WARNING/ERROR/CRITICAL are stored, redaction runs before the row
lands, exceptions carry their traceback in `detail`, and a broken store never
raises back into the caller.
"""

from __future__ import annotations

import logging

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.repositories.log_repository import LogStore


def _logger_dengan_handler(store, nama):
    log = logging.getLogger(nama)
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.addHandler(SqliteLogHandler(store))
    log.propagate = False
    return log


def test_error_tersimpan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.error").error("kamera putus")
    hasil = store.baca(level=None, cari=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["level"] == "ERROR"


def test_warning_tersimpan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.warn").warning("antrean menumpuk")
    assert store.baca(level="WARNING", cari=None, limit=10, offset=0)["total"] == 1


def test_info_tidak_tersimpan(tmp_path):
    """INFO terlalu berisik; log yang penuh INFO menenggelamkan sebab."""
    store = LogStore(tmp_path / "log.db")
    log = _logger_dengan_handler(store, "t.info")
    log.info("frame diproses")
    log.debug("detail")
    assert store.baca(level=None, cari=None, limit=10, offset=0)["total"] == 0


def test_sandi_tidak_pernah_mendarat_di_disk(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_dengan_handler(store, "t.rahasia").error("gagal: password=rahasia123")
    items = store.baca(level=None, cari=None, limit=10, offset=0)["items"]
    assert "rahasia123" not in items[0]["pesan"]


def test_traceback_masuk_detail(tmp_path):
    store = LogStore(tmp_path / "log.db")
    log = _logger_dengan_handler(store, "t.exc")
    try:
        raise ValueError("pecah")
    except ValueError:
        log.exception("worker jatuh")
    items = store.baca(level=None, cari=None, limit=10, offset=0)["items"]
    assert "ValueError" in items[0]["detail"]


def test_store_yang_gagal_tidak_menjatuhkan_pemanggil(tmp_path):
    """Log itu alat bantu; ia tidak boleh jadi sebab baru matinya line."""

    class StoreRusak:
        def tulis(self, *a, **k):
            raise RuntimeError("disk penuh")

    log = logging.getLogger("t.rusak")
    log.handlers.clear()
    log.addHandler(SqliteLogHandler(StoreRusak()))
    log.propagate = False
    log.error("tetap harus balik dengan selamat")  # tidak boleh melempar


def test_konsol_sesi_tidak_pernah_mendarat_di_disk(tmp_path):
    """A session cookie can ride a traceback through `uvicorn.error`, which
    propagates to root — this is exactly why `konsol_sesi` is a redaction key."""
    store = LogStore(tmp_path / "log.db")
    log = _logger_dengan_handler(store, "t.sesi")
    log.error("request gagal: konsol_sesi=abc123def")
    items = store.baca(level=None, cari=None, limit=10, offset=0)["items"]
    assert "abc123def" not in items[0]["pesan"]
