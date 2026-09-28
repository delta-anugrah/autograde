"""Integrasi tab Akun yang menulis: komponen sungguhan, tanpa Docker.

- Akun yang dibuat dari layar bertemu tarikan AutoERP SUNGGUHAN
  (`MasterDataWorker` + `ErpClient`, jaringannya saja `httpx.MockTransport`)
  dengan email yang sama. Jawaban untuk pertanyaan user 2026-09-26 ("akun yang
  dibuat di AutoGrade masuk ke AutoERP?"): tidak. Tidak ada satu pun permintaan
  tulis ke AutoERP, dan akun lokal itu tidak ditimpa tarikan.
- Jejak perubahan lewat jalur log yang dipakai pabrik: `logging` →
  `SqliteLogHandler` → `LogStore` → `DevService.log()` (tab Log), tanpa sandi.
"""
from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import unquote

import httpx
import pytest

from palmgrade.core.log_sink import install_log_sink
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.services.operator_admin import OperatorAdmin
from palmgrade.workers.master_data_worker import MasterDataWorker

HASH_ERP = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"
SUPPORT = "support@pks.test"
SANDI = "sandi-lokal-99"


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _erp_mencatat(operator: dict, permintaan: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        permintaan.append(request)
        doctype = unquote(request.url.path.rsplit("/", 1)[-1])
        data = [operator] if doctype == "AutoGrade Operator" else []
        return httpx.Response(200, json={"data": data})

    return httpx.MockTransport(handler)


def test_akun_dari_layar_tidak_dikirim_ke_autoerp_dan_tidak_ditimpa_tarikan(store):
    OperatorAdmin(store).tambah("budi@pks.test", "Budi Lokal", SANDI, SANDI, "operator",
                                oleh=SUPPORT)
    permintaan: list[httpx.Request] = []
    operator_erp = {
        "name": "budi@pks.test", "email": "budi@pks.test", "full_name": "Budi ERP",
        "active": 1, "password_hash": HASH_ERP, "role": "support",
        "modified": "2026-09-26 08:00:00.000000",
    }
    klien = ErpClient("http://erp.local", "k", "s", transport=_erp_mencatat(operator_erp, permintaan))

    asyncio.run(MasterDataWorker(store, klien).pull_once())

    assert permintaan, "tarikan tidak pernah menghubungi ERP palsu"
    assert {r.method for r in permintaan} == {"GET"}
    row = store.operator_by_email("budi@pks.test")
    assert (row["origin"], row["full_name"], row["role"]) == ("lokal", "Budi Lokal", "operator")
    auth = AuthService(store)
    token, _ = auth.login("budi@pks.test", SANDI)
    assert auth.current(token)["email"] == "budi@pks.test"


def test_perubahan_akun_sampai_ke_tab_log_tanpa_sandi(store, tmp_path):
    log = LogStore(tmp_path / "log.db")
    handler = install_log_sink(log)
    try:
        admin = OperatorAdmin(store)
        admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)
        admin.ganti_sandi("budi@pks.test", "sandi-baru-77", "sandi-baru-77", oleh=SUPPORT)
        admin.atur_status("budi@pks.test", False, oleh=SUPPORT)
        admin.atur_role("budi@pks.test", "support", oleh=SUPPORT)
    finally:
        logging.getLogger().removeHandler(handler)

    hasil = DevService(log, console_store=store).log(
        level="WARNING", search="budi@pks.test", limit=50, offset=0
    )
    teks = json.dumps(hasil)
    pesan = [row["message"] for row in hasil["items"]]
    assert len(pesan) == 4, pesan
    assert all(SUPPORT in m for m in pesan)
    assert SANDI not in teks and "sandi-baru-77" not in teks
