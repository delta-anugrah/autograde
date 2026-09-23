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


# ── fire_test_coil / testable_coils: layar uji PLC untuk commissioning ──────────


def test_testable_coils_mengecualikan_alive_dan_error():
    from palmgrade import plc

    # _Cfg default: plc_coil_manual=10, plc_coil_base=0 -> ok=0, ng=1, error=2.
    assert plc.testable_coils(_Cfg()) == frozenset({0, 1, 10})   # bukan 2 (error) atau alive


def test_testable_coils_mengecualikan_coil_alive_walau_dikonfigurasi():
    from palmgrade import plc

    # coil 9 = HEARTBIT PC ON. Memicunya manual bisa membuat panel mengira PC
    # mati dan membunyikan alarm seven-segment — harus TIDAK PERNAH masuk daftar.
    class _CfgDenganAlive(_Cfg):
        plc_coil_alive = (9,)

    assert 9 not in plc.testable_coils(_CfgDenganAlive())


def test_testable_coils_tanpa_piston_manual_dikonfigurasi():
    from palmgrade import plc

    class _CfgTanpaManual(_Cfg):
        plc_coil_manual = None

    assert plc.testable_coils(_CfgTanpaManual()) == frozenset({0, 1})


def test_fire_test_coil_modul_ditolak_kalau_plc_mati():
    from palmgrade import plc

    plc._worker = None
    assert plc.fire_test_coil(0) is False


def test_fire_test_coil_modul_meneruskan_ke_worker():
    from palmgrade import plc

    w, _ = _worker()
    plc._worker = w
    try:
        assert plc.fire_test_coil(0) is True
    finally:
        plc._worker = None                # jangan bocor ke test lain di suite ini


def test_fire_test_coil_modul_meneruskan_penolakan_antrean_penuh():
    from palmgrade import plc

    client = _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=_Cfg(),
    )
    w.fire_test_coil(0)                         # penuhi antrean coil 0
    plc._worker = w
    try:
        assert plc.fire_test_coil(0) is False   # antrean penuh -> tidak dipicu, bukan error
    finally:
        plc._worker = None


# ── alamat absolut vs indeks blok (MC Protocol: blok tidak mulai dari 0) ─────


class _CfgBerbasis200:
    """Panel MC Protocol: blok yang dibaca mulai di M200, bukan 0.

    `PLC_DI_MANUAL` ditulis sebagai alamat ABSOLUT (M212) di compose dan di
    dokumen panel — sama seperti semua alamat lain. Kalau worker memperlakukan
    angka itu sebagai indeks ke dalam blok, ia membaca bit ke-212 dari blok
    20-bit dan konfirmasi piston tidak pernah datang, tanpa satu pun error.
    """

    plc_enabled = True
    plc_host = "192.168.3.39"
    plc_port = 1025
    plc_unit_id = 1
    plc_protocol = "mc"
    plc_device_prefix = "M"
    plc_pulse_ms = 200
    plc_pulse_gap_ms = 100
    plc_poll_ms = 200
    plc_queue_max = 1
    plc_coil_ok = 100
    plc_coil_ng = 101
    plc_coil_error = 102
    plc_coil_alive = ()
    plc_alive_toggle_ms = 0
    plc_coil_manual = 103
    plc_di_base = 200
    plc_di_count = 20
    plc_di_manual = 212     # absolut: M212 = konfirmasi piston line 1


def test_konfirmasi_piston_dibaca_dari_alamat_absolut_bukan_indeks():
    from palmgrade.plc.pulse import PulseScheduler
    from palmgrade.plc.worker import PlcWorker

    w = PlcWorker(
        client=object(),
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=_CfgBerbasis200(),
    )
    # Blok M200..M219; yang menyala cuma M212 = offset 12 di dalam blok.
    w.inputs = [False] * 20
    w.inputs[12] = True

    assert w.piston_state()["confirmed_open"] is True


def test_konfirmasi_piston_alamat_di_luar_blok_terbaca_tidak_diketahui():
    from palmgrade.plc.pulse import PulseScheduler
    from palmgrade.plc.worker import PlcWorker

    cfg = _CfgBerbasis200()
    cfg.plc_di_manual = 999     # jauh di luar M200..M219
    w = PlcWorker(
        client=object(),
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=cfg,
    )
    w.inputs = [True] * 20
    # Bukan True: alamat itu tidak ada di blok yang dibaca, jadi jawabannya
    # "tidak tahu", bukan "terbuka".
    assert w.piston_state()["confirmed_open"] is None
