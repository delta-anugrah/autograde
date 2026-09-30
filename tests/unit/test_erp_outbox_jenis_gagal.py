"""Why a queued message is still waiting, as a code the Status tab words (2026-10-01).

User decision after testing PR #200: outside the Log tab no screen shows system error
text. The ERP queue and the R2 manifest queue showed `last_error` raw ("POST
/api/method/...: HTTP 417: ..."). The worker knows the failure's TYPE when it records it,
so it stores one code next to the text (`error_kind`); the screen words the code, the
text stays for the Log tab and curl. Rows written by an older build have no code and get
the generic sentence.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3

import httpx
import pytest

from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import (
    GAGAL_DITOLAK,
    GAGAL_KONSOL,
    GAGAL_KUNCI_DITOLAK,
    GAGAL_TAK_TERJANGKAU,
    GAGAL_TUJUAN,
    JENIS_GAGAL,
    ErpOutboxStore,
)
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker, OutboxHandler

METHOD = "erpnext.palm_mill.api.upsert_truck"


class _Jam:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _worker(tmp_path, jawab, *, on_sent=None, handlers=None):
    jam = _Jam()
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db", clock=jam)
    client = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(jawab))
    handlers = handlers if handlers is not None else {
        "truck": OutboxHandler(method=METHOD, on_sent=on_sent or (lambda key, message: None)),
    }
    return ErpOutboxWorker(outbox, client, handlers), outbox


def _satu_gagal(outbox: ErpOutboxStore) -> dict:
    [baris] = outbox.failed_rows()
    return baris


# ── store ───────────────────────────────────────────────────────────────


def test_kosakata_jenis_gagal():
    assert set(JENIS_GAGAL) == {GAGAL_TAK_TERJANGKAU, GAGAL_KUNCI_DITOLAK, GAGAL_DITOLAK, GAGAL_TUJUAN, GAGAL_KONSOL}


def test_jenis_ikut_disimpan_dan_dibaca_layar(tmp_path):
    outbox = ErpOutboxStore(tmp_path / "o.db")
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "POST /api/method/x: HTTP 417: unknown field", jenis=GAGAL_DITOLAK)

    baris = _satu_gagal(outbox)
    assert (baris["error_kind"], baris["last_error"]) == (GAGAL_DITOLAK, "POST /api/method/x: HTTP 417: unknown field")


def test_tanpa_jenis_tetap_boleh_dan_terbaca_kosong(tmp_path):
    outbox = ErpOutboxStore(tmp_path / "o.db")
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "timeout")

    assert _satu_gagal(outbox)["error_kind"] is None


def test_diantre_ulang_menghapus_jenis_lama(tmp_path):
    jam = _Jam()
    outbox = ErpOutboxStore(tmp_path / "o.db", clock=jam)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "x", jenis=GAGAL_TAK_TERJANGKAU)
    outbox.enqueue("truck", "K1", {"v": 2})
    outbox.mark_error(outbox.due()[0], "y")

    assert _satu_gagal(outbox)["error_kind"] is None


def test_berkas_versi_lama_mendapat_kolomnya_tanpa_kehilangan_baris(tmp_path):
    """Lampung's erp_outbox.db predates the column: B5/C3, added in place, rows kept."""
    jalur = tmp_path / "erp_outbox.db"
    db = sqlite3.connect(jalur)
    db.executescript(
        """CREATE TABLE erp_outbox (
               kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
               last_error TEXT, next_attempt_at REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL,
               version INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (kind, key));"""
    )
    db.execute(
        "INSERT INTO erp_outbox (kind, key, payload, status, attempts, last_error, created_at)"
        " VALUES ('truck', 'K1', '{}', 'error', 2, 'HTTP 503', 1)"
    )
    db.commit()
    db.close()

    outbox = ErpOutboxStore(jalur)
    ErpOutboxStore(jalur)  # twice: safe to run again

    baris = _satu_gagal(outbox)
    assert (baris["key"], baris["last_error"], baris["error_kind"]) == ("K1", "HTTP 503", None)


def test_payload_rusak_disisihkan_sebagai_galat_konsol(tmp_path):
    jalur = tmp_path / "o.db"
    outbox = ErpOutboxStore(jalur)
    outbox.enqueue("truck", "K1", {"v": 1})
    db = sqlite3.connect(jalur)
    db.execute("UPDATE erp_outbox SET payload='{rusak'")
    db.commit()
    db.close()

    assert outbox.due() == []
    assert _satu_gagal(outbox)["error_kind"] == GAGAL_KONSOL


# ── worker: the failure's type picks the code ───────────────────────────


@pytest.mark.parametrize(
    "jawaban,jenis",
    [
        (httpx.Response(503, text="service unavailable"), GAGAL_TAK_TERJANGKAU),
        (httpx.Response(401, json={"exc_type": "AuthenticationError"}), GAGAL_KUNCI_DITOLAK),
        (httpx.Response(403, json={"exc_type": "PermissionError"}), GAGAL_KUNCI_DITOLAK),
        (httpx.Response(417, json={"exception": "Nomor polisi wajib"}), GAGAL_DITOLAK),
        (httpx.Response(500, json={"exc_type": "KeyError", "exception": "KeyError: 'counts'"}), GAGAL_TUJUAN),
    ],
)
def test_jawaban_autoerp_menentukan_jenisnya(tmp_path, jawaban, jenis):
    worker, outbox = _worker(tmp_path, lambda request: jawaban)
    outbox.enqueue("truck", "K1", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    assert _satu_gagal(outbox)["error_kind"] == jenis


def test_jaringan_putus_tak_terjangkau(tmp_path):
    def putus(request):
        raise httpx.ConnectError("All connection attempts failed", request=request)

    worker, outbox = _worker(tmp_path, putus)
    outbox.enqueue("truck", "K1", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    assert _satu_gagal(outbox)["error_kind"] == GAGAL_TAK_TERJANGKAU


def test_pencatatan_lokal_yang_gagal_galat_konsol(tmp_path):
    def meledak(key, message):
        raise RuntimeError("database is locked")

    worker, outbox = _worker(tmp_path, lambda request: httpx.Response(200, json={"message": {}}), on_sent=meledak)
    outbox.enqueue("truck", "K1", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    assert _satu_gagal(outbox)["error_kind"] == GAGAL_KONSOL


def test_jenis_tanpa_handler_galat_konsol_dan_tercatat_di_tab_log(tmp_path, caplog):
    """The screen points to the Log tab for this row, so the Log tab must have it."""
    worker, outbox = _worker(tmp_path, lambda request: httpx.Response(200, json={}), handlers={})
    outbox.enqueue("visit", "v1", {"stage": "gate"})

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.erp_outbox_worker"):
        asyncio.run(worker.drain_once())

    assert _satu_gagal(outbox)["error_kind"] == GAGAL_KONSOL
    assert any("visit" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records)
