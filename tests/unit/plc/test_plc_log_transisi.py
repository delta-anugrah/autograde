"""PLC dicabut = satu baris, bukan ±10 per detik (batch 3.3).

Dua klien PLC (MC Protocol dan Modbus) dan `PlcWorker` diuji bersama di sini karena
yang dijaga adalah jumlah baris log SELURUH jalurnya: satu WARNING saat putus, satu
saat pulih, dan diam di antaranya, berapa pun tick yang lewat.
"""
from __future__ import annotations

import logging

import pytest

from palmgrade.plc.jejak_sambungan import JejakSambunganPlc
from palmgrade.plc.mc_client import McProtocolPlcClient
from palmgrade.plc.modbus_client import ModbusPlcClient
from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker


class _Jam:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Type3E:
    """Pengganti pymcprotocol.Type3E; `hidup=False` = kabel dicabut."""

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


class _Cfg:
    plc_coil_base = 1000
    plc_coil_alive = (1015,)
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_base = 1100
    plc_di_count = 16

    plc_coil_ok = 1000
    plc_coil_ng = 1001
    plc_coil_error = 1002


def _log_plc(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("palmgrade.plc") and r.levelno >= logging.WARNING]


@pytest.fixture
def jalur():
    papan = {"hidup": True}
    klien = McProtocolPlcClient("192.168.3.39", 1025, _client_factory=lambda: _Type3E(papan))
    worker = PlcWorker(klien, PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20), _Cfg())
    return papan, klien, worker


def _tick(worker: PlcWorker, mulai: float, n: int) -> float:
    for i in range(n):
        worker.run_once(now=mulai + i * 0.2)
    return mulai + n * 0.2


def test_plc_dicabut_lima_puluh_tick_satu_warning_lalu_satu_saat_pulih(jalur, caplog):
    papan, _klien, worker = jalur
    caplog.set_level(logging.DEBUG, logger="palmgrade.plc")
    t = _tick(worker, 0.0, 3)
    caplog.clear()

    papan["hidup"] = False
    t = _tick(worker, t, 50)
    putus = _log_plc(caplog)
    papan["hidup"] = True
    _tick(worker, t, 5)
    semua = _log_plc(caplog)

    assert len(putus) == 1 and "192.168.3.39:1025" in putus[0].getMessage()
    assert len(semua) == 2 and "tersambung lagi sesudah" in semua[1].getMessage()


def test_kegagalan_berikutnya_tetap_ada_di_debug(jalur, caplog):
    papan, _klien, worker = jalur
    caplog.set_level(logging.DEBUG, logger="palmgrade.plc")
    papan["hidup"] = False
    _tick(worker, 0.0, 10)
    assert len([r for r in caplog.records if r.levelno == logging.DEBUG]) > 10


def test_connect_berhasil_tapi_io_gagal_tetap_satu_kejadian():
    """PLC yang menerima koneksi lalu menolak tiap paket: connect-putus-connect-putus
    tetap satu kejadian, karena pulih baru dinyatakan sesudah I/O berhasil."""
    jam = _Jam()
    jejak = JejakSambunganPlc("10.0.0.1", 1025, jam=jam)
    jejak.terputus(OSError("reset"))
    for _ in range(20):
        jejak.terputus(OSError("reset"))
    assert jejak.putus is True
    jam.t = 42.0
    jejak.berhasil()
    assert jejak.putus is False


def test_modbus_host_yang_tidak_menjawab_satu_warning(caplog):
    class _Inner:
        def connect(self):
            return False

        def close(self):
            pass

    klien = ModbusPlcClient("1.2.3.4", 502, _client_factory=_Inner)
    with caplog.at_level(logging.WARNING, logger="palmgrade.plc"):
        for _ in range(30):
            assert klien.write_coil(4, True) is False
    assert len(_log_plc(caplog)) == 1


def test_penolakan_modbus_saat_tersambung_dicatat_worker_sekali(caplog):
    class _Balas:
        def __init__(self, galat):
            self._galat = galat
            self.bits = [False] * 16

        def isError(self):  # noqa: N802 (nama milik pymodbus)
            return self._galat

    class _Inner:
        menolak = True

        def connect(self):
            return True

        def write_coil(self, address, value, slave=1):
            return _Balas(self.menolak)

        def read_discrete_inputs(self, address, count, slave=1):
            return _Balas(False)

        def close(self):
            pass

    inner = _Inner()
    klien = ModbusPlcClient("1.2.3.4", 502, _client_factory=lambda: inner)
    worker = PlcWorker(klien, PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20), _Cfg())
    with caplog.at_level(logging.WARNING, logger="palmgrade.plc"):
        t = _tick(worker, 0.0, 30)
        inner.menolak = False
        _tick(worker, t, 10)
    pesan = [r.getMessage() for r in _log_plc(caplog)]
    assert len(pesan) == 2
    assert pesan[0].startswith("Coil PLC gagal ditulis") and pesan[1].startswith("Coil PLC bisa ditulis lagi")
