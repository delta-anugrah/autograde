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
    # Awal putus ERROR (sampai ke Discord: buah lewat tanpa disortir), pulihnya WARNING.
    assert [r.levelno for r in semua] == [logging.ERROR, logging.WARNING]


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


def test_penolakan_modbus_saat_tersambung_dicatat_worker_per_coil(caplog):
    """`run_once` tanpa status apa pun di antrean tetap menulis DUA coil sendiri
    tiap detik (alive 1015, ERROR 1002). Fix round 1 (C1) membuat tracker per
    coil, jadi keduanya dicatat sebagai DUA kejadian terpisah, masing-masing satu
    WARNING gagal + satu WARNING pulih: bukan satu pasang gabungan seperti
    sebelum fix (dulu kebetulan tampak "satu" karena tracker dibagi semua coil)."""

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
    gagal = [p for p in pesan if p.startswith("Coil PLC gagal ditulis")]
    pulih = [p for p in pesan if p.startswith("Coil PLC bisa ditulis lagi")]
    assert len(gagal) == 2
    assert any("coil=1015" in p for p in gagal) and any("coil=1002" in p for p in gagal)
    assert len(pulih) == 2
    catatan = _log_plc(caplog)
    assert {r.levelno for r in catatan if r.getMessage().startswith("Coil PLC gagal")} == {logging.ERROR}
    assert {r.levelno for r in catatan if r.getMessage().startswith("Coil PLC bisa")} == {logging.WARNING}


def test_satu_coil_rusak_tidak_membuat_coil_sehat_lain_flapping(caplog):
    """Fix round 1, C1: coil 1000 SELALU gagal ditulis, coil 1015 (alive) dan 1002
    (ERROR) SELALU berhasil di tick yang sama. Sebelum fix, satu `PelacakTransisi`
    dipakai bersama semua coil: coil sehat yang berhasil sesudah coil 1000 gagal
    memanggil `.pulih()` pada tracker yang sama dan membuat 1000 terbaca pulih,
    lalu gagal lagi tick berikutnya -> WARNING-recovery-WARNING berulang, bukan
    satu WARNING yang diam sampai coil 1000 benar-benar pulih.
    """

    class _KlienCoilTunggalRusak:
        connected = True

        def __init__(self, coil_rusak: int) -> None:
            self._rusak = coil_rusak

        def write_coil(self, address: int, value: bool) -> bool:
            return address != self._rusak

        def read_discrete_inputs(self, start: int, count: int) -> list[bool] | None:
            return [False] * count

        def close(self) -> None:
            pass

    klien = _KlienCoilTunggalRusak(coil_rusak=1000)
    worker = PlcWorker(klien, PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20), _Cfg())

    def tick(mulai: float, n: int) -> float:
        # `submit("acc")` tiap tick memaksa coil 1000 (plc_coil_ok) ditulis tiap
        # tick lewat retry (`_failed_writes`), SEDANGKAN coil alive (1015) dan
        # ERROR (1002) ditulis tiap ~1 detik dan SELALU berhasil di klien ini:
        # ini kombinasi yang bikin tracker gabungan flap sebelum fix C1.
        for i in range(n):
            worker.submit("acc")
            worker.run_once(now=mulai + i * 0.2)
        return mulai + n * 0.2

    with caplog.at_level(logging.WARNING, logger="palmgrade.plc"):
        t = tick(0.0, 10)
    gagal = [r.getMessage() for r in _log_plc(caplog) if r.getMessage().startswith("Coil PLC gagal ditulis")]
    pulih = [r.getMessage() for r in _log_plc(caplog) if r.getMessage().startswith("Coil PLC bisa ditulis lagi")]
    assert len(gagal) == 1
    assert len(pulih) == 0

    caplog.clear()
    klien._rusak = -1  # coil 1000 pulih
    tick(t, 3)
    pulih_lagi = [r.getMessage() for r in _log_plc(caplog) if r.getMessage().startswith("Coil PLC bisa ditulis lagi")]
    assert len(pulih_lagi) == 1


def test_awal_putus_plc_error_supaya_sampai_discord_pulihnya_warning():
    """Review akhir 1, I3: satu-satunya kanal keluar pabrik (digest Discord) cuma
    membawa ERROR. PLC yang putus berarti buah lewat tanpa disortir seharian, jadi
    awal kejadiannya ERROR, sekali per kejadian; pulihnya tetap WARNING."""
    jam = _Jam()
    jejak = JejakSambunganPlc("10.0.0.1", 1025, jam=jam)
    catatan: list[logging.LogRecord] = []

    class _Tangkap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            catatan.append(record)

    log = logging.getLogger("palmgrade.plc.jejak_sambungan")
    penangkap = _Tangkap(level=logging.WARNING)
    log.addHandler(penangkap)
    try:
        jejak.gagal_sambung("timed out")
        jejak.gagal_sambung("timed out")
        jam.t = 30.0
        jejak.berhasil()
        jejak.terputus(OSError("reset"))
        jejak.terputus(OSError("reset"))
        jam.t = 90.0
        jejak.berhasil()
    finally:
        log.removeHandler(penangkap)
    assert [(r.levelno, r.getMessage().split(" ")[2]) for r in catatan] == [
        (logging.ERROR, "tidak"), (logging.WARNING, "tersambung"),
        (logging.ERROR, "terputus"), (logging.WARNING, "tersambung"),
    ]


def test_input_plc_gagal_dibaca_tetap_warning():
    """Baca input cuma konfirmasi piston; sortirnya tetap jalan. Bukan ERROR."""

    class _KlienBacaRusak:
        connected = True

        def write_coil(self, address: int, value: bool) -> bool:
            return True

        def read_discrete_inputs(self, start: int, count: int) -> list[bool] | None:
            return None

        def close(self) -> None:
            pass

    worker = PlcWorker(_KlienBacaRusak(), PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20), _Cfg())
    catatan: list[logging.LogRecord] = []

    class _Tangkap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            catatan.append(record)

    log = logging.getLogger("palmgrade.plc.worker")
    penangkap = _Tangkap(level=logging.WARNING)
    log.addHandler(penangkap)
    try:
        _tick(worker, 0.0, 5)
    finally:
        log.removeHandler(penangkap)
    assert [(r.levelno, r.getMessage()) for r in catatan] == [
        (logging.WARNING, "Input PLC gagal dibaca, memakai keadaan terakhir")
    ]
