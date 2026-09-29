"""End-to-end tanda "line sedang dinyalakan ulang": jawaban rute ASLI sampai kotak kamera.

Router konsol asli dengan login support sungguhan (Sumber Kamera lewat
`ConsoleService`, Danger Zone lewat `BahayaService`), line palsu yang sebagian
menolak. Jawaban JSON-nya diberikan apa adanya ke `lineDirestart` di node, lalu
kotak kamera dirender dengan KAMUS asli dalam dua bahasa: yang ditandai persis
line yang dijawab server sudah restart, dan kalimat yang tampil bebas em dash.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

import pytest
from bahaya_palsu import LINES, LinePalsu, isi_data
from fastapi import FastAPI
from fastapi.testclient import TestClient
from konsol_js import NODE, jalankan, konstanta

from palmgrade.core.config import Settings
from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import (
    get_auth_service,
    get_bahaya_service,
    get_console_service,
    get_dev_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.bahaya_service import BahayaService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.dev_service import DevService

SANDI = "sandi-e2e-restart"
MULAI = 1_790_000_000_000  # ms; 21.13 WIB
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")


class _LineSumber:
    """Line untuk Sumber Kamera: `line-3` tidak menjawab restart."""

    async def restart(self, line):
        if line.line_code == "line-3":
            raise LineUnavailable("LINE_TIDAK_MENJAWAB", "line-3 mati", line=line.name)


@pytest.fixture
def konsol(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))
    (tmp_path / "media").mkdir()
    store = ConsoleStore(tmp_path / "console.db")
    log = LogStore(tmp_path / "log.db")
    sink = install_log_sink(log)
    line = LinePalsu()
    bahaya = BahayaService(
        store, log, line, LINES, ErpOutboxStore(tmp_path / "erp_outbox.db"), None,
        erp_aktif=False, hash_bawaan=hash_password("bawaan"), hash_support=hash_password("bawaan"),
        hari_kerja=lambda: "2026-09-29", tunggu_mati_s=1.0, jeda_cek_s=0.0,
    )
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, _LineSumber())
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log)
    app.dependency_overrides[get_bahaya_service] = lambda: bahaya
    store.upsert_operator_manual({
        "email": "support@pks.test", "full_name": "Support",
        "password_hash": hash_password(SANDI), "role": ROLE_SUPPORT,
    })
    isi_data(store)
    client = TestClient(app)
    res = client.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI})
    assert res.status_code == 200, res.text
    yield client, line
    logging.getLogger().removeHandler(sink)


def _ditandai(jawaban: dict) -> list[str]:
    return jalankan(["lineDirestart"], f"lineDirestart({json.dumps(jawaban)})")


def _kotak(nama: str, lewat_ms: int, bahasa: str) -> str:
    konst = konstanta("RESTART_BATAS_MS", "RESTART_PASTI_MATI_MS", "RESTART_KODE")
    m = json.dumps({"mulai": MULAI, "turunPada": None, "diam": 0})
    return jalankan(
        ["jamSinkron", "isiRestart", "teksDetikRestart"],
        f"[isiRestart({json.dumps(nama)}, {m}, {MULAI + lewat_ms}),"
        f" teksDetikRestart({m}, {MULAI + lewat_ms})].join(' ')",
        bahasa=bahasa, tambahan=konst,
    )


@butuh_node
def test_sumber_kamera_menandai_line_yang_benar_benar_direstart(konsol):
    client, _line = konsol
    res = client.post("/api/console/dev/sumber-kamera", json={
        "line-1": {"sumber": "webcam"},   # berubah, direstart
        "line-2": {"sumber": "hikrobot"},  # tidak berubah
        "line-3": {"sumber": "webcam"},   # berubah, tapi tidak menjawab restart
    })
    assert res.status_code == 200, res.text
    assert _ditandai(res.json()) == ["line-1"]


@butuh_node
def test_restart_semua_line_menandai_yang_menjawab(konsol):
    client, line = konsol
    line.mati = {"line-2"}
    res = client.post("/api/console/dev/bahaya/restart-line", json={})
    assert res.status_code == 200, res.text
    assert _ditandai(res.json()) == ["line-1", "line-3"]


@butuh_node
def test_hapus_data_menandai_line_yang_menerima(konsol):
    client, line = konsol
    line.status_hapus = {"line-1": (403, '{"detail":"lisensi habis"}')}
    res = client.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 200, res.text
    assert _ditandai(res.json()) == ["line-2", "line-3"]


@butuh_node
@pytest.mark.parametrize("bahasa,jalan,lama", [
    ("id", ["Line 1 sedang dinyalakan ulang", "12 detik"],
     ["Line 1 belum kembali", "Kode RESTART_LAMA", "21.13", "Cek tab Log dan terminal line itu", "75 detik"]),
    ("en", ["Line 1 is restarting", "12 s"],
     ["Line 1 has not come back", "Code RESTART_LAMA", "21:13", "Check the Log tab", "75 s"]),
])
def test_kotak_kamera_dengan_kamus_asli_tanpa_em_dash(bahasa, jalan, lama):
    teks_jalan = _kotak("Line 1", 12_000, bahasa)
    teks_lama = _kotak("Line 1", 75_000, bahasa)
    for p in jalan:
        assert p in teks_jalan, (p, teks_jalan)
    for p in lama:
        assert p in teks_lama, (p, teks_lama)
    for teks in (teks_jalan, teks_lama):
        assert "—" not in teks and "–" not in teks and " - " not in teks
