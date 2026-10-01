"""Satu kejadian line = satu baris di tab Log (batch 3.2 + 3.6 + 3.7, aturan 34 dan 35).

Setelah batch 3.2 konsol menarik WARNING/ERROR tiap line ke tab Log, dan batch 3.6/3.7
membuat line sendiri yang mencatat FRAME_BERHENTI dan DISK_KRITIS. `LineStatusWorker`
konsol memantau keadaan yang SAMA tiap detik; cerminnya harus INFO (ruling R5), kalau
tidak tiap kejadian muncul dua kali di tab Log (satu bertanda line, satu bertanda konsol)
dan dua kali di ringkasan Discord.

Line: worker capture + deteksi ASLI (kamera palsu), `PenjagaAi`, `PemantauDisk` (disk
palsu), `AntreanLogLine` + `LogLineStore` + router `/internal/log` ASLI. Konsol:
`LineClient` + `LineStatusWorker` + `TarikLogLineWorker` + `LogStore` + `DevService`
+ router konsol ASLI dengan login support sungguhan.

Dua proses disimulasikan di satu proses test, jadi handler log dipasang per logger,
bukan di root: handler line (antrean `log_line.db`) di logger modul line, handler tab
Log konsol di logger modul konsol yang ikut kejadian ini. Di produksi keduanya di root
proses masing-masing; di satu proses root yang sama akan mencampur kedua sisi.
"""
from __future__ import annotations

import asyncio
import logging
import types
from collections import namedtuple
from dataclasses import replace
from pathlib import Path

import pytest
from ai_palsu import JAM_DINDING, LinePalsu
from antrean_line_rakit import LinePerPort
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.kesehatan_disk import GB
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.plc.mc_client import McProtocolPlcClient
from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_line_repository import LogLineStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.internal_log import buat_router
from palmgrade.schemas.internal_schema import LineStatusResponse
from palmgrade.services.antrean_log_line import AntreanLogLine
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.services.pemantau_disk import PemantauDisk, ringkas_disk_dari_state
from palmgrade.services.penjaga_ai import ringkas_ai_dari_state
from palmgrade.workers import frame_capture_worker
from palmgrade.workers.line_status_worker import LineStatusWorker
from palmgrade.workers.tarik_log_line_worker import TarikLogLineWorker

SANDI = "sandi-e2e-transisi-sekali"
SECRET = "kunci-internal-palsu"
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")
Usage = namedtuple("Usage", "total used free")

#: Logger yang hidup di proses LINE untuk kejadian ini.
LOGGER_LINE = (
    "palmgrade.services.penjaga_ai",
    "palmgrade.services.pemantau_disk",
    "palmgrade.workers.frame_capture_worker",
    "palmgrade.workers.frame_processing_worker",
    "palmgrade.plc.jejak_sambungan",
    "palmgrade.plc.worker",
)
#: Logger yang hidup di proses KONSOL dan ikut kejadian ini.
LOGGER_KONSOL = (
    "palmgrade.workers.line_status_worker",
    "palmgrade.workers.tarik_log_line_worker",
    "palmgrade.integrations.notifications.line_client",
)


class _DiskPalsu:
    def __init__(self) -> None:
        self.bebas_gb = 232.0

    def __call__(self, _jalur):
        total, bebas = 468 * GB, int(self.bebas_gb * GB)
        return Usage(total, total - bebas, bebas)


class _Type3E:
    """Pengganti pymcprotocol.Type3E; `papan["hidup"] = False` = kabel PLC dicabut."""

    def __init__(self, papan: dict) -> None:
        self._papan = papan

    def _cek(self) -> None:
        if not self._papan["hidup"]:
            raise OSError("[Errno 113] No route to host")

    def setaccessopt(self, **_kw) -> None:
        pass

    def connect(self, _ip, _port) -> None:
        self._cek()

    def batchwrite_bitunits(self, headdevice, values) -> None:
        self._cek()

    def randomwrite_bitunits(self, bit_devices, values) -> None:
        self._cek()

    def _recv(self):
        return b"\x00" * 32

    def batchread_bitunits(self, headdevice, readsize):
        self._cek()
        self._recv()
        return [0] * readsize

    def close(self) -> None:
        pass


class _CfgPlc:
    plc_coil_base = 1000
    plc_coil_alive = (1015,)
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_base = 1100
    plc_di_count = 16
    plc_coil_ok = 1000
    plc_coil_ng = 1001
    plc_coil_error = 1002


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


def _pasang(handler: logging.Handler, nama_logger: tuple[str, ...]) -> list[logging.Logger]:
    dipasang = [logging.getLogger(n) for n in nama_logger]
    for lg in dipasang:
        lg.addHandler(handler)
    return dipasang


@pytest.fixture
def pabrik(tmp_path, monkeypatch):
    monkeypatch.setattr(frame_capture_worker.time, "sleep", lambda _detik: None)

    # ── proses line ──────────────────────────────────────────────────────────
    line = LinePalsu()
    line.kamera.bisa_sambung_ulang = True        # Hikrobot: sambung ulangnya tetap berhasil
    papan_plc = {"hidup": True}
    plc = PlcWorker(
        McProtocolPlcClient("192.168.3.39", 1025, _client_factory=lambda: _Type3E(papan_plc)),
        PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20), _CfgPlc(),
    )
    disk = _DiskPalsu()
    line.state.pemantau_disk = PemantauDisk(
        settings=replace(line.settings, r2_bucket=""), jalur=(Path("/app/artifacts"),), ukur=disk,
        jam_dinding=lambda: JAM_DINDING + (line.jam.sekarang - 1_000.0),
    )
    log_line = LogLineStore(tmp_path / "state-line-2" / "log_line.db")
    antrean = AntreanLogLine(log_line)           # thread penulisnya diganti `antrean.kuras()`
    handler_line = SqliteLogHandler(antrean)
    settings_line = replace(Settings(), internal_secret=SECRET)

    line_app = FastAPI()
    line_app.include_router(buat_router(settings=lambda: settings_line, store=lambda: log_line))

    @line_app.get("/internal/status", response_model=LineStatusResponse)
    async def status() -> LineStatusResponse:
        return LineStatusResponse(machine_id="m-2", truck_id=None, ffb_source=None, piston=None,
                                  ai=ringkas_ai_dari_state(line.state),
                                  disk=ringkas_disk_dari_state(line.state))

    # ── proses konsol ────────────────────────────────────────────────────────
    log_store = LogStore(tmp_path / "log_kejadian.db")
    handler_konsol = SqliteLogHandler(log_store)
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8002: line_app}),
    )
    status_worker = LineStatusWorker([LINE_2], klien)
    tarik = TarikLogLineWorker([LINE_2], klien, log_store)

    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "support@pks.test", "nama": "Support", "password_hash": hash_password(SANDI),
         "role": ROLE_SUPPORT}
    )
    konsol = FastAPI()
    konsol.include_router(console_router)
    konsol.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    konsol.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    konsol.dependency_overrides[get_dev_service] = lambda: DevService(log_store)
    layar = TestClient(konsol)
    assert layar.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI}).status_code == 200

    def putaran() -> None:
        """Satu detik konsol: status line, lalu penulis log line menguras, lalu tarikan."""
        asyncio.run(status_worker.run_once())
        antrean.kuras()
        asyncio.run(tarik.run_once())

    def tab_log() -> list[dict]:
        res = layar.get("/api/console/dev/log?limit=200")
        assert res.status_code == 200, res.text
        return res.json()["items"]

    di_line = _pasang(handler_line, LOGGER_LINE)
    di_konsol = _pasang(handler_konsol, LOGGER_KONSOL)
    try:
        yield types.SimpleNamespace(line=line, disk=disk, putaran=putaran, tab_log=tab_log,
                                    plc=plc, papan_plc=papan_plc)
    finally:
        for lg in di_line:
            lg.removeHandler(handler_line)
        for lg in di_konsol:
            lg.removeHandler(handler_konsol)


def _baris_konsol(baris: list[dict]) -> list[str]:
    return [b["message"] for b in baris if b["line_code"] is None]


def test_frame_berhenti_satu_baris_error_bertanda_line_di_tab_log(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    p.putaran()
    assert p.tab_log() == []

    p.line.kamera.mengirim = False
    p.line.jalan(40, deteksi=False)
    for _ in range(3):                           # konsol memantau tiap detik, keadaan sama
        p.putaran()

    baris = p.tab_log()
    frame = [b for b in baris if "FRAME_BERHENTI" in b["message"]]
    assert [(b["level"], b["line_code"], b["count"]) for b in frame] == [("ERROR", "line-2", 1)], baris
    assert _baris_konsol(baris) == []


def test_disk_kritis_satu_baris_error_bertanda_line_di_tab_log(pabrik):
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    p.putaran()

    p.disk.bebas_gb = 3.0
    for _ in range(3):
        p.putaran()

    baris = p.tab_log()
    disk = [b for b in baris if "DISK_KRITIS" in b["message"]]
    assert [(b["level"], b["line_code"], b["count"]) for b in disk] == [("ERROR", "line-2", 1)], baris
    assert _baris_konsol(baris) == []



def _tick_plc(plc: PlcWorker, mulai: float, n: int) -> float:
    for i in range(n):
        plc.run_once(now=mulai + i * 0.2)
    return mulai + n * 0.2


def test_plc_putus_lalu_pulih_satu_baris_masing_masing_bertanda_line(pabrik):
    """Review akhir 1, M3: kabel PLC dicabut 50 tick (10 detik) lalu dipasang lagi. Tab Log
    konsol: satu ERROR "tidak bisa disambung" / "terputus" dan satu WARNING "tersambung
    lagi", keduanya `line-2`, tidak ada baris konsol."""
    p = pabrik
    t = _tick_plc(p.plc, 0.0, 3)
    p.putaran()
    assert p.tab_log() == []

    p.papan_plc["hidup"] = False
    t = _tick_plc(p.plc, t, 50)
    for _ in range(3):
        p.putaran()
    p.papan_plc["hidup"] = True
    _tick_plc(p.plc, t, 5)
    for _ in range(3):
        p.putaran()

    baris = p.tab_log()
    plc = sorted(((b["level"], b["line_code"], b["count"], b["message"]) for b in baris
                  if b["source"].startswith("palmgrade.plc")), key=lambda x: x[0])
    assert [(lv, lc, n) for lv, lc, n, _ in plc] == [("ERROR", "line-2", 1), ("WARNING", "line-2", 1)], baris
    assert "192.168.3.39:1025" in plc[0][3]
    assert "tersambung lagi sesudah" in plc[1][3]
    assert _baris_konsol(baris) == []


def test_kamera_berhenti_lalu_kembali_satu_baris_masing_masing_bertanda_line(pabrik):
    """Review akhir 1, M3: kamera berhenti 10 detik (di bawah ambang FRAME_BERHENTI) lalu
    kembali. Tab Log: satu WARNING "tidak mengirim gambar" dan satu WARNING "mengirim
    gambar lagi", keduanya `line-2`, walau konsol memantau tiap detik."""
    p = pabrik
    p.line.mulai()
    p.line.jalan(5)
    p.putaran()
    assert p.tab_log() == []

    p.line.kamera.mengirim = False
    p.line.jalan(10, deteksi=False)
    for _ in range(3):
        p.putaran()
    p.line.kamera.mengirim = True
    p.line.jalan(3)
    for _ in range(3):
        p.putaran()

    baris = p.tab_log()
    kamera = [(b["level"], b["line_code"], b["count"], b["message"]) for b in baris
              if b["source"] == "palmgrade.workers.frame_capture_worker"]
    pesan = sorted(m for *_, m in kamera)
    assert [(lv, lc, n) for lv, lc, n, _ in kamera] == [("WARNING", "line-2", 1)] * 2, baris
    assert pesan[0].startswith("Kamera mengirim gambar lagi sesudah")
    assert pesan[1].startswith("Kamera tidak mengirim gambar")
    assert not [b for b in baris if "FRAME_BERHENTI" in b["message"]]
    assert _baris_konsol(baris) == []
