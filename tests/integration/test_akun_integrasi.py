"""Integrasi layar Akun: akun datang dari jalurnya yang SUNGGUHAN, sampai ke layar.

Unit test mengisi tabel `operators` langsung. Di sini akun tiba lewat jalur
yang dipakai pabrik:

- akun AutoERP lewat `MasterDataWorker` + `ErpClient` asli (jaringannya saja
  yang ditukar `httpx.MockTransport`, dan ERP palsunya menolak field asing
  seperti Frappe);
- status terkunci lewat `AuthService.login` asli yang salah sandi berulang;
- "sedang masuk" lewat sesi yang dibuat login sungguhan;

lalu dibaca `DevService.akun()` dan digambar `barisAkun` yang ada di
`console.html` (lewat node, dilewati kalau node tidak ada).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import OperatorError
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.workers.master_data_worker import MasterDataWorker

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")

# Hash yang ditulis passlib AutoERP untuk sandi "sawit2026" (sama dengan
# tests/unit/test_erp_master_data.py) — konsol memverifikasinya tanpa passlib.
HASH_ERP = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"
FIELD_OPERATOR = {"name", "modified", "email", "full_name", "active", "password_hash", "role"}


def _erp(operator: dict) -> httpx.MockTransport:
    """`/api/resource` AutoERP dalam bentuk kecil — ketat soal nama field."""

    def handler(request: httpx.Request) -> httpx.Response:
        doctype = unquote(request.url.path.rsplit("/", 1)[-1])
        if doctype == "AutoGrade Operator":
            asing = set(json.loads(request.url.params["fields"])) - FIELD_OPERATOR
            if asing:
                return httpx.Response(417, json={"exception": f"Field not permitted: {asing}"})
            return httpx.Response(200, json={"data": [operator]})
        return httpx.Response(200, json={"data": []})

    return httpx.MockTransport(handler)


def _operator(**ubah) -> dict:
    return {
        "name": "budi@pks.test", "email": "budi@pks.test", "full_name": "Pak Budi",
        "active": 1, "password_hash": HASH_ERP, "role": "operator",
        "modified": "2026-09-25 08:00:00.000000",
    } | ubah


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    dev = DevService(LogStore(tmp_path / "log.db"), console_store=store)
    return store, dev


def _akun(dev: DevService) -> dict[str, dict]:
    return {a["email"]: a for a in dev.akun()["akun"]}


def _tarik(store: ConsoleStore, operator: dict) -> None:
    klien = ErpClient("http://erp.local", "k", "s", transport=_erp(operator))
    asyncio.run(MasterDataWorker(store, klien).pull_once())


def test_akun_dari_autoerp_tampil_dengan_asal_erp(konsol):
    store, dev = konsol
    _tarik(store, _operator())

    budi = _akun(dev)["budi@pks.test"]
    assert (budi["nama"], budi["asal"], budi["keadaan"]) == ("Pak Budi", "erp", "aktif")
    assert "password_hash" not in json.dumps(dev.akun())


def test_akun_dimatikan_di_autoerp_terbaca_mati(konsol):
    store, dev = konsol
    _tarik(store, _operator())
    _tarik(store, _operator(active=0, modified="2026-09-25 09:00:00.000000"))

    assert _akun(dev)["budi@pks.test"]["keadaan"] == "mati"


def test_akun_autoerp_bisa_masuk_dan_terbaca_sedang_masuk(konsol):
    store, dev = konsol
    _tarik(store, _operator())

    AuthService(store).login("budi@pks.test", "sawit2026")

    assert _akun(dev)["budi@pks.test"]["sedang_masuk"] is True


def test_salah_sandi_berulang_terbaca_terkunci(konsol):
    store, dev = konsol
    store.upsert_operator_manual(
        {"email": "ani@pks.test", "full_name": "Ani", "password_hash": hash_password("sandi-benar-1")}
    )
    auth = AuthService(store)
    for _ in range(5):
        with pytest.raises(OperatorError):  # sandi salah, lalu terkunci
            auth.login("ani@pks.test", "sandi-salah-99")

    ani = _akun(dev)["ani@pks.test"]
    assert ani["keadaan"] == "terkunci"
    assert ani["terkunci_detik"] > 0
    assert ani["asal"] == "lokal"


@pytest.mark.skipif(NODE is None, reason="node tidak ada")
def test_baris_layar_dari_jawaban_sungguhan(konsol):
    store, dev = konsol
    _tarik(store, _operator())
    store.upsert_operator_manual(
        {"email": "ani@pks.test", "full_name": "Ani", "password_hash": hash_password("sandi-benar-1")}
    )
    auth = AuthService(store)
    for _ in range(5):
        with pytest.raises(OperatorError):
            auth.login("ani@pks.test", "sandi-salah-99")

    def fungsi(nama: str) -> str:
        awal = HTML.index(f"function {nama}(")
        return HTML[awal : HTML.index("\n}", awal) + 2]

    skrip = (
        'const esc = (s) => String(s ?? "").replace(/[&<>"\'`]/g, (c) =>'
        ' ({ "&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;","`":"&#96;" }[c]));\n'
        'const KOSONG = "-"; const t = (k) => k; const lokal = () => "id-ID";\n'
        + fungsi("tanggalAkun") + "\n" + fungsi("barisAkun")
        + f"\nconsole.log(JSON.stringify({json.dumps(dev.akun()['akun'])}.map(barisAkun)));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    baris = {b.split("<td>")[2].split("</td>")[0]: b for b in json.loads(hasil.stdout)}

    assert "asalErp" in baris["budi@pks.test"] and 'class="tag ok"' in baris["budi@pks.test"]
    assert "akunTerkunci" in baris["ani@pks.test"] and 'class="tag no"' in baris["ani@pks.test"]
