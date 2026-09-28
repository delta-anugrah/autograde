"""End-to-end Danger Zone di konsol: alur yang dijalani support, dari login.

Login sungguhan, peran dari store yang sama dengan sisa konsol, log sink yang
dipasang seperti lifespan konsol, dan tab Log dibaca lewat rutenya sendiri.
Line-nya palsu (`tests/bahaya_palsu.py`); rantai konsol ↔ line sungguhan ada di
`tests/integration/test_danger_zone_integrasi.py`.
"""
from __future__ import annotations

import logging

import pytest
from bahaya_palsu import LINES, LinePalsu, buka_tiket, hitung, isi_data
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import (
    get_auth_service,
    get_bahaya_service,
    get_console_service,
    get_dev_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.akun_bawaan import EMAIL_SUPPORT
from palmgrade.services.auth_service import AuthService
from palmgrade.services.bahaya_service import BahayaService
from palmgrade.services.dev_service import DevService

SANDI = "sandi-e2e-bahaya"
SANDI_BAWAAN = "sandi-bawaan-pabrik"
HARI = "2026-09-25"


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log = LogStore(tmp_path / "log.db")
    sink = install_log_sink(log)
    line = LinePalsu()
    hash_bawaan = hash_password(SANDI_BAWAAN)
    bahaya = BahayaService(
        store, log, line, LINES, ErpOutboxStore(tmp_path / "erp_outbox.db"), None,
        erp_aktif=True, hash_bawaan=hash_bawaan, hash_support=hash_bawaan,
        hari_kerja=lambda: HARI, tunggu_mati_s=1.0, jeda_cek_s=0.0,
    )
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log)
    app.dependency_overrides[get_bahaya_service] = lambda: bahaya
    store.upsert_operator_manual(
        {"email": "support@pks.test", "full_name": "Support", "password_hash": hash_password(SANDI)}
    )
    store.set_role(store.operator_by_email("support@pks.test")["id"], "support")
    isi_data(store)
    yield app, store, line
    logging.getLogger().removeHandler(sink)


def _masuk(app, email: str, sandi: str) -> TestClient:
    client = TestClient(app)
    res = client.post("/api/console/login", json={"email": email, "sandi": sandi})
    assert res.status_code == 200, res.text
    return client


def test_alur_hapus_data_transaksi(konsol):
    app, store, line = konsol
    support = _masuk(app, "support@pks.test", SANDI)

    # 1. Buka panel: aman, tidak ada hambatan.
    panel = support.get("/api/console/dev/bahaya").json()
    assert panel["aksi"]["transaksi"]["hambatan"] == []
    assert panel["data"]["janjang"] == 1

    # 2. Ketik HAPUS, tekan.
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 200, res.text

    # 3. Efeknya: ketiga line disuruh, data konsol kosong, master tetap.
    assert sorted(line.perintah) == [
        ("hapus_data", "line-1"), ("hapus_data", "line-2"), ("hapus_data", "line-3"),
    ]
    assert hitung(store, "inspections") == 0
    assert hitung(store, "trucks") == 1

    # 4. Tab Log: log lama hilang, jejak siapa yang menghapus di baris pertama.
    log = support.get("/api/console/dev/log").json()
    assert log["total"] == 1
    assert "[Danger Zone]" in log["items"][0]["message"]
    assert "support@pks.test" in log["items"][0]["message"]

    # 5. Yang menekan tetap masuk.
    assert support.get("/api/console/dev/bahaya").status_code == 200


def test_alur_ditolak_lalu_boleh_sesudah_truk_dilepas(konsol):
    app, store, line = konsol
    support = _masuk(app, "support@pks.test", SANDI)
    line.detail["line-2"]["current_assignment_id"] = "assign-7"

    panel = support.get("/api/console/dev/bahaya").json()
    assert panel["aksi"]["transaksi"]["hambatan"] == [{"kode": "truk_terpasang", "line": "line-2"}]
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 409
    assert hitung(store, "inspections") == 1

    line.detail["line-2"]["current_assignment_id"] = None  # truk dilepas operator
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 200
    assert hitung(store, "inspections") == 0


def test_alur_tiket_terbuka_menahan_sampai_truk_timbang_keluar(konsol):
    """Truk yang sudah timbang masuk hari ini dan belum keluar: bruto-nya yang
    dibayar. Tombolnya tertahan sampai tiket itu lengkap."""
    app, store, line = konsol
    support = _masuk(app, "support@pks.test", SANDI)
    buka_tiket(store, hari=HARI)

    panel = support.get("/api/console/dev/bahaya").json()
    assert panel["aksi"]["transaksi"]["hambatan"] == [{"kode": "tiket_terbuka", "jumlah": 1}]
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["params"]["hambatan"] == "tiket_terbuka"
    assert line.perintah == []

    # Truk timbang keluar: tiketnya lengkap, bukan lagi kunjungan yang berjalan.
    with store._lock, store._db:
        store._db.execute("UPDATE weighings SET tare_kg = 5200, net_kg = 9620")
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 200, res.text
    assert hitung(store, "weighings") == 0


def test_alur_semua_line_menolak_tidak_menghapus_apa_pun(konsol):
    """Lisensi ketiga line habis: middleware lisensi menolak semua `/internal/*`.
    Tidak satu foto pun terhapus, jadi index konsol juga tidak boleh."""
    app, store, line = konsol
    support = _masuk(app, "support@pks.test", SANDI)
    line.status_hapus = {ln.line_code: (403, '{"error":"LICENSE_INVALID"}') for ln in LINES}

    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "semua_line_menolak"
    assert detail["params"]["lines"] == "line-1:lisensi,line-2:lisensi,line-3:lisensi"
    assert hitung(store, "inspections") == 1
    # Tab Log: percobaannya tercatat, log lama tidak ikut dikosongkan.
    log = support.get("/api/console/dev/log", params={"cari": "GAGAL"}).json()
    assert log["total"] == 1
    assert "support@pks.test" in log["items"][0]["message"]


def test_alur_hapus_semua_lalu_masuk_dengan_akun_bawaan(konsol):
    app, store, _line = konsol
    support = _masuk(app, "support@pks.test", SANDI)

    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "semua", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 200, res.text

    # Sesi yang menekan ikut hilang: layar kembali ke gerbang login.
    assert support.get("/api/console/dev/bahaya").status_code == 401
    # Akun buatan sendiri hilang...
    gagal = TestClient(app).post(
        "/api/console/login", json={"email": "support@pks.test", "sandi": SANDI}
    )
    assert gagal.status_code == 401
    # ...akun bawaan dibuat ulang dari hash .env, dan masih support.
    bawaan = _masuk(app, EMAIL_SUPPORT, SANDI_BAWAAN)
    assert bawaan.get("/api/console/dev/bahaya").status_code == 200
    assert hitung(store, "trucks") == 0


def test_alur_logout_paksa(konsol):
    app, _store, _line = konsol
    support = _masuk(app, "support@pks.test", SANDI)
    lain = _masuk(app, "support@pks.test", SANDI)  # layar kedua, mis. kiosk pabrik

    # Dua sesi support di atas + sesi akun "ani" dari `isi_data`.
    assert support.post("/api/console/dev/bahaya/logout-semua").json()["sesi_dihapus"] == 3
    assert support.get("/api/console/dev/bahaya").status_code == 401
    assert lain.get("/api/console/dev/bahaya").status_code == 401
