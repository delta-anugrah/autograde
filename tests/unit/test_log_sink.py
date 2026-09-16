"""Logging handler that bridges `logging` records into `LogStore`.

Covers: only WARNING/ERROR/CRITICAL are stored, redaction runs before the row
lands, exceptions carry their traceback in `detail`, and a broken store never
raises back into the caller.
"""

from __future__ import annotations

import logging

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.repositories.log_repository import LogStore


def _logger_with_handler(store, name):
    log = logging.getLogger(name)
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.addHandler(SqliteLogHandler(store))
    log.propagate = False
    return log


def test_error_is_stored(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_with_handler(store, "t.error").error("kamera putus")
    result = store.read(level=None, search=None, limit=10, offset=0)
    assert result["total"] == 1
    assert result["items"][0]["level"] == "ERROR"


def test_warning_is_stored(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_with_handler(store, "t.warn").warning("antrean menumpuk")
    assert store.read(level="WARNING", search=None, limit=10, offset=0)["total"] == 1


def test_info_is_not_stored(tmp_path):
    """INFO is too noisy; a log full of INFO drowns out the cause."""
    store = LogStore(tmp_path / "log.db")
    log = _logger_with_handler(store, "t.info")
    log.info("frame diproses")
    log.debug("detail")
    assert store.read(level=None, search=None, limit=10, offset=0)["total"] == 0


def test_password_never_lands_on_disk(tmp_path):
    store = LogStore(tmp_path / "log.db")
    _logger_with_handler(store, "t.rahasia").error("gagal: password=rahasia123")
    items = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert "rahasia123" not in items[0]["pesan"]


def test_traceback_lands_in_detail(tmp_path):
    store = LogStore(tmp_path / "log.db")
    log = _logger_with_handler(store, "t.exc")
    try:
        raise ValueError("pecah")
    except ValueError:
        log.exception("worker jatuh")
    items = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert "ValueError" in items[0]["detail"]


def test_a_failing_store_does_not_bring_down_the_caller(tmp_path):
    """A log is a helper; it must never become a new reason a line goes down."""

    class BrokenStore:
        def write(self, *a, **k):
            raise RuntimeError("disk penuh")

    log = logging.getLogger("t.rusak")
    log.handlers.clear()
    log.addHandler(SqliteLogHandler(BrokenStore()))
    log.propagate = False
    log.error("tetap harus balik dengan selamat")  # must not raise


def test_konsol_sesi_never_lands_on_disk(tmp_path):
    """A session cookie can ride a traceback through `uvicorn.error`, which
    propagates to root — this is exactly why `konsol_sesi` is a redaction key."""
    store = LogStore(tmp_path / "log.db")
    log = _logger_with_handler(store, "t.sesi")
    log.error("request gagal: konsol_sesi=abc123def")
    items = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert "abc123def" not in items[0]["pesan"]
