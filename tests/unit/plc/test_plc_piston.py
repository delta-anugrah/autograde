"""Piston manual: coil level yang diminta operator, dieksekusi ladder PLC.

Yang dijaga di sini semuanya keputusan keselamatan, bukan kenyamanan:
permintaan tidak boleh hidup lagi sendiri sesudah gangguan, dan layar tidak
boleh mengklaim piston terbuka kalau PLC tidak membenarkan.
"""
from __future__ import annotations

from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.di = [False] * 16
        self.gagal = False

    def write_coil(self, address, value):
        if self.gagal:
            return False
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]

    def close(self):
        pass


class _Cfg:
    plc_coil_base = 0
    plc_coil_alive = ()
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_count = 16
    plc_coil_manual = 10
    plc_di_manual = 11

    @property
    def plc_coil_ok(self):
        return self.plc_coil_base

    @property
    def plc_coil_ng(self):
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self):
        return self.plc_coil_base + 2


def _worker(cfg=None):
    client = _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=cfg or _Cfg(),
        health_check=lambda: True,
    )
    return w, client


def test_permintaan_buka_menaikkan_coil_sekali():
    w, client = _worker()
    w.request_piston(True)
    w.run_once(now=0.0)
    assert (10, True) in client.writes

    client.writes.clear()
    w.run_once(now=0.2)
    assert [wr for wr in client.writes if wr[0] == 10] == []   # level, bukan pulse


def test_permintaan_tutup_menurunkan_coil():
    w, client = _worker()
    w.request_piston(True)
    w.run_once(now=0.0)
    w.request_piston(False)
    w.run_once(now=0.2)
    assert (10, False) in client.writes


def test_tulis_buka_yang_gagal_tidak_dicoba_ulang():
    # Kalau ON gagal lalu di-retry, piston bisa membuka SENDIRI beberapa detik
    # kemudian saat koneksi pulih — padahal operator sudah tidak di situ.
    w, client = _worker()
    w.request_piston(True)
    client.gagal = True
    w.run_once(now=0.0)
    client.gagal = False
    w.run_once(now=0.2)
    assert [wr for wr in client.writes if wr == (10, True)] == []
    assert w.piston_state()["requested"] is False


def test_pembukaan_yang_tidak_dikonfirmasi_plc_dibatalkan():
    # E-stop atau interlock lain: ladder menolak. Coil harus turun supaya klik
    # berikutnya jadi tepi naik yang baru, bukan level yang sudah tinggi.
    w, client = _worker()
    w.request_piston(True)
    w.run_once(now=0.0)
    w.run_once(now=2.5)                 # DI tetap 0 melewati tenggang
    assert (10, False) in client.writes
    assert w.piston_state()["requested"] is False


def test_di_yang_membenarkan_membuat_status_terbuka():
    w, client = _worker()
    w.request_piston(True)
    w.run_once(now=0.0)
    client.di[11] = True
    w.run_once(now=0.2)
    assert w.piston_state() == {"requested": True, "confirmed_open": True}


def test_tanpa_di_yang_dikonfigurasi_status_mengikuti_permintaan():
    class _CfgTanpaDI(_Cfg):
        plc_di_manual = None

    w, _ = _worker(_CfgTanpaDI())
    w.request_piston(True)
    w.run_once(now=0.0)
    w.run_once(now=2.5)                 # tanpa DI tidak ada pembatalan
    assert w.piston_state() == {"requested": True, "confirmed_open": None}


def test_shutdown_menutup_piston():
    w, client = _worker()
    w.request_piston(True)
    w.run_once(now=0.0)
    client.writes.clear()
    w.deenergise()
    assert (10, False) in client.writes


def test_permintaan_piston_ditolak_kalau_plc_mati():
    from palmgrade import plc

    # Singleton modul: test lain di suite ini bisa meninggalkannya terisi, dan
    # hasil test tidak boleh bergantung urutan eksekusi.
    plc._worker = None

    assert plc.request_piston(True) is False      # tidak ada worker = tidak ada piston
    assert plc.piston_state() is None
