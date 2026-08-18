import logging
import threading

from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.di = [False] * 16
        self.closed = False

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]

    def close(self):
        self.closed = True


class _Cfg:
    plc_coil_base = 3
    plc_coil_alive = (11,)
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_count = 16

    @property
    def plc_coil_ok(self):
        return self.plc_coil_base

    @property
    def plc_coil_ng(self):
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self):
        return self.plc_coil_base + 2


class _CfgToggle(_Cfg):
    plc_alive_toggle_ms = 1000


def _worker(health_check=None, settings=None):
    client = _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=settings or _Cfg(),
        health_check=health_check,
    )
    return w, client


def test_acc_maps_to_ok_coil_of_this_line():
    w, client = _worker()
    w.submit("acc")
    w.run_once(now=0.0)
    assert (3, True) in client.writes


def test_rej_maps_to_ng_coil_of_this_line():
    w, client = _worker()
    w.submit("rej")
    w.run_once(now=0.0)
    assert (4, True) in client.writes


def test_submit_never_blocks_when_queue_is_full():
    # Thread deteksi memanggil ini. Antrean penuh harus dibuang, bukan menggantung.
    w, _ = _worker()
    for _ in range(500):
        w.submit("rej")          # tidak boleh raise, tidak boleh menggantung
    # Tanpa assert ini, test lolos bahkan kalau submit() diam-diam jadi no-op
    # total. 50 pertama masuk antrean (maxsize), 450 sisanya HARUS terhitung.
    assert w._queue.qsize() == 50
    assert w.dropped_submissions == 450


def test_alive_coil_is_held_on_by_default():
    # Skematik ODOT menulis "HEARTBIT PC ON" dan ladder pak Ocit membaca LEVEL
    # ("coil OFF berarti PC mati"). Toggle akan memadamkan coil separuh periode
    # dan memicu alarm PC-mati palsu terus-menerus. Ditulis ulang tiap detik,
    # bukan sekali: fault action coupler bisa me-reset output saat link putus.
    w, client = _worker()
    w.run_once(now=0.0)
    w.run_once(now=1.0)
    w.run_once(now=2.0)
    assert [v for (addr, v) in client.writes if addr == 11] == [True, True, True]


def test_alive_coil_toggles_only_when_toggle_ms_set():
    # Jalur cadangan kalau pak Ocit memilih ladder penghitung-perubahan: itu satu
    # -satunya cara mendeteksi proses hang yang socket-nya masih hidup.
    w, client = _worker(settings=_CfgToggle())
    w.run_once(now=0.0)
    w.run_once(now=1.0)
    w.run_once(now=2.0)
    assert [v for (addr, v) in client.writes if addr == 11] == [True, False, True]


def test_discrete_inputs_are_snapshotted():
    w, client = _worker()
    client.di[10] = True          # EMERGENCY STOP
    w.run_once(now=0.0)
    assert w.inputs[10] is True


def test_unknown_status_is_ignored_not_crashed():
    w, client = _worker()
    w.submit("tp")
    w.run_once(now=0.0)
    assert all(addr not in (3, 4) for (addr, _) in client.writes)


class _OffCfg:
    plc_enabled = False
    plc_host = ""


class _NoHostCfg:
    plc_enabled = True
    plc_host = ""


def test_facade_is_noop_when_plc_disabled(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    assert plc.start_plc_worker(_OffCfg()) is None
    plc.submit_grading("rej")     # tidak boleh raise
    assert plc.inputs() == []


def test_enabled_without_host_refuses_to_start(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    assert plc.start_plc_worker(_NoHostCfg()) is None


class _FlakyOffClient(_FakeClient):
    """Gagal persis satu kali di write_coil OFF ke coil 3, sukses setelahnya."""

    def __init__(self):
        super().__init__()
        self._off_failures_left = 1

    def write_coil(self, address, value):
        if address == 3 and value is False and self._off_failures_left > 0:
            self._off_failures_left -= 1
            return False
        return super().write_coil(address, value)


def test_failed_off_write_is_retried_next_tick_and_lands():
    client = _FlakyOffClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_Cfg(),
    )
    w.submit("acc")
    w.run_once(now=0.0)          # ON diterapkan
    w.run_once(now=0.3)          # tick() laporkan OFF, write gagal
    assert (3, False) not in client.writes
    assert w._failed_writes.get(3) is False

    w.run_once(now=0.3)          # tidak ada perubahan level baru dari tick(), tapi retry jalan
    assert (3, False) in client.writes
    assert 3 not in w._failed_writes


class _FlakyReadClient(_FakeClient):
    def __init__(self):
        super().__init__()
        self._fail_next_read = False

    def read_discrete_inputs(self, start, count):
        if self._fail_next_read:
            return None
        return super().read_discrete_inputs(start, count)


def test_failed_read_does_not_clobber_previous_input_state():
    client = _FlakyReadClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_Cfg(),
    )
    client.di[10] = True
    w.run_once(now=0.0)
    assert w.inputs[10] is True

    client._fail_next_read = True
    client.di[10] = False        # kalau ini bocor ke w.inputs, testnya salah
    w.run_once(now=0.1)
    assert w.inputs[10] is True


def test_submit_overflow_increments_dropped_submissions_not_scheduler_dropped():
    w, _ = _worker()
    for _ in range(60):
        w.submit("rej")
    assert w.dropped_submissions > 0
    assert w.scheduler.dropped == 0


def test_start_plc_worker_called_twice_returns_none_and_builds_one_client(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)

    created = []

    class _FakeModbusClient:
        def __init__(self, *args, **kwargs):
            created.append(self)

    monkeypatch.setattr(plc, "ModbusPlcClient", _FakeModbusClient)

    class _Settings:
        plc_enabled = True
        plc_host = "10.0.0.5"
        plc_port = 502
        plc_unit_id = 1
        plc_pulse_ms = 200
        plc_pulse_gap_ms = 100
        plc_poll_ms = 200
        plc_queue_max = 20
        plc_coil_ok = 3
        plc_coil_ng = 4
        plc_coil_error = 5
        plc_coil_alive = (11,)

    settings = _Settings()
    first = plc.start_plc_worker(settings)
    second = plc.start_plc_worker(settings)

    assert first is not None
    # Panggilan kedua HARUS None, bukan worker yang sama. Pemanggil (main.py)
    # memakai `is not None` untuk memutuskan start thread; mengembalikan worker
    # yang sama membuat thread KEDUA jalan di run_loop yang sama, di atas socket
    # ModbusTcpClient yang sama — ADU interleaved dan transaction id tidak cocok,
    # lebih buruk daripada satu slot coupler yang dihemat guard ini.
    assert second is None
    assert len(created) == 1


class _AliveFlakyClient(_FakeClient):
    """Kendalikan sukses/gagal write coil alive (11) per panggilan; coil lain selalu sukses."""

    def __init__(self, alive_outcomes):
        super().__init__()
        self._alive_outcomes = list(alive_outcomes)

    def write_coil(self, address, value):
        if address == 11:
            ok = self._alive_outcomes.pop(0) if self._alive_outcomes else True
            if not ok:
                return False
        return super().write_coil(address, value)


def test_alive_toggle_overwrites_stale_retry_without_runt_pulse():
    # tick1: write alive gagal, level basi (True) nyangkut di _failed_writes.
    # tick2: tick toggle — level basi dan level segar (False) mengenai coil yang
    # SAMA. Kalau keduanya benar-benar ditulis, PLC melihat pasangan ON/OFF
    # selebar ~1ms di bit alive (runt pulse). Harus tepat SATU write, level segar.
    client = _AliveFlakyClient(alive_outcomes=[False])
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=_CfgToggle(),
    )
    w.run_once(now=0.0)   # toggle -> True, write gagal
    w.run_once(now=1.0)   # retry True + toggle False jatuh di tick yang sama

    assert [v for (addr, v) in client.writes if addr == 11] == [False]


def test_alive_coil_success_clears_stale_failed_retry():
    # Urutan: tick1 write alive GAGAL, tick2 level segar (yang menimpa level basi)
    # GAGAL lagi, tick3 retry level segar itu SUKSES dan tidak menagih apa pun lagi.
    client = _AliveFlakyClient(alive_outcomes=[False, False, True])
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_CfgToggle(),
    )
    w.run_once(now=0.0)   # alive toggle -> True, write gagal
    w.run_once(now=1.0)   # step 2 retry level basi (True) gagal; step 3 toggle -> False, sukses
    w.run_once(now=1.1)   # belum waktunya toggle lagi; tidak boleh ada retry level basi

    alive_writes = [v for (addr, v) in client.writes if addr == 11]
    assert alive_writes == [False]


def test_sustained_overflow_never_raises_error_coil():
    # Overflow adalah steady state yang DIDEKLARASIKAN di bawah beban
    # (docs/plc-integration.md): kamera bisa ~10 keputusan/detik, satu coil muat
    # ~3,3. Kalau drop menaikkan ERROR, CAM_N_ERROR menyala sepanjang shift dan
    # artinya berubah jadi "line ini jalan normal" — entah menghentikan produksi
    # atau cuma jadi hiasan. ERROR = health check gagal (kamera mati), titik.
    w, client = _worker(health_check=lambda: True)
    w.scheduler.queue_max = 1
    for tick in range(10):
        for _ in range(5):
            w.submit("rej")
        w.run_once(now=tick * 0.2)

    assert w.scheduler.dropped > 0          # benar-benar overflow, terus-menerus
    assert [v for (addr, v) in client.writes if addr == 5] == [False]


def test_error_coil_raised_when_health_check_says_unhealthy():
    w, client = _worker(health_check=lambda: False)
    w.run_once(now=0.0)
    assert (5, True) in client.writes


def test_error_coil_written_once_not_every_tick():
    w, client = _worker(health_check=lambda: True)
    w.run_once(now=0.0)
    w.run_once(now=0.2)
    w.run_once(now=0.4)
    assert [v for (addr, v) in client.writes if addr == 5] == [False]


class _DeadClient:
    """Link mati total: semua I/O melempar. Dipakai untuk membuktikan shutdown
    tetap tuntas walau kabel sudah dicabut duluan."""

    def write_coil(self, address, value):
        raise OSError("kabel dicabut")

    def read_discrete_inputs(self, start, count):
        raise OSError("kabel dicabut")

    def close(self):
        raise OSError("socket sudah mati")


def test_run_loop_exits_when_stopped():
    # daemon=True saja tidak cukup: proses yang keluar tanpa menghentikan loop
    # ini meninggalkan coil OK/NG nyangkut ON di tengah pulse.
    w, _ = _worker()
    t = threading.Thread(target=w.run_loop, daemon=True)
    t.start()
    w.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()


def test_deenergise_writes_off_to_every_coil_of_this_line():
    w, client = _worker()
    # Bookkeeping bilang ERROR sudah OFF dan tidak ada write tertunda —
    # de-energise harus mengabaikan itu semua dan tetap menulis OFF.
    w._error_level = False
    w._failed_writes = {}
    w.deenergise()
    assert set(client.writes) == {(3, False), (4, False), (5, False), (11, False)}


def test_deenergise_does_not_raise_on_dead_link():
    w = PlcWorker(
        client=_DeadClient(),
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=_Cfg(),
    )
    w.deenergise()   # best-effort: dicatat, tidak di-retry, tidak di-raise


def test_shutdown_plc_worker_is_safe_noop_when_never_started(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    plc.shutdown_plc_worker()          # tidak boleh raise
    plc.shutdown_plc_worker(None)      # juga tanpa thread


def test_shutdown_plc_worker_deenergises_closes_and_clears_singleton(monkeypatch):
    import palmgrade.plc as plc

    w, client = _worker()
    w._error_level = False
    monkeypatch.setattr(plc, "_worker", w, raising=False)

    plc.shutdown_plc_worker()

    assert set(client.writes) == {(3, False), (4, False), (5, False), (11, False)}
    assert client.closed is True
    assert plc._worker is None


def test_shutdown_plc_worker_stops_loop_before_final_writes(monkeypatch):
    # Urutan wajib: hentikan loop DULU, baru matikan coil. Kebalikannya bikin
    # loop balapan dan menyalakan ulang bit alive sesudah kita mematikannya.
    import palmgrade.plc as plc

    w, client = _worker()
    monkeypatch.setattr(plc, "_worker", w, raising=False)
    t = threading.Thread(target=w.run_loop, daemon=True)
    t.start()

    plc.shutdown_plc_worker(t)

    assert not t.is_alive()
    last_level: dict[int, bool] = {}
    for addr, level in client.writes:
        last_level[addr] = level
    assert last_level and all(level is False for level in last_level.values())


def test_shutdown_plc_worker_clears_singleton_even_when_link_is_dead(monkeypatch):
    import palmgrade.plc as plc

    w = PlcWorker(
        client=_DeadClient(),
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
        settings=_Cfg(),
    )
    monkeypatch.setattr(plc, "_worker", w, raising=False)

    plc.shutdown_plc_worker()   # tidak boleh raise

    assert plc._worker is None


def test_diagnostics_is_none_when_plc_is_disabled(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    assert plc.diagnostics() is None


def test_diagnostics_exposes_estop_and_both_drop_counters(monkeypatch):
    # Commissioning menyuruh operator "baca inputs()[10]" (E-stop) dan memantau
    # kedua counter drop sepanjang shift. Tanpa ini, dua-duanya cuma bisa dilihat
    # lewat shell Python di dalam kontainer.
    import palmgrade.plc as plc

    w, client = _worker()
    client.di[10] = True                 # EMERGENCY STOP
    w.scheduler.queue_max = 1
    for _ in range(5):
        w.submit("rej")
    w.run_once(now=0.0)                  # -> scheduler.dropped naik
    for _ in range(80):
        w.submit("rej")                  # -> _queue (maxsize 50) meluap
    monkeypatch.setattr(plc, "_worker", w, raising=False)

    snapshot = plc.diagnostics()

    assert snapshot["inputs"][10] is True
    assert snapshot["dropped_pulses"] == w.scheduler.dropped
    assert snapshot["dropped_submissions"] == w.dropped_submissions
    assert snapshot["dropped_pulses"] > 0
    assert snapshot["dropped_submissions"] > 0


def test_diagnostics_inputs_is_a_copy_not_worker_state(monkeypatch):
    import palmgrade.plc as plc

    w, client = _worker()
    w.run_once(now=0.0)
    monkeypatch.setattr(plc, "_worker", w, raising=False)

    plc.diagnostics()["inputs"][10] = True
    assert w.inputs[10] is False


class _StartCfg:
    """Settings minimal yang cukup buat start_plc_worker (client-nya di-fake)."""

    plc_enabled = True
    plc_host = "10.0.0.5"
    plc_port = 502
    plc_unit_id = 1
    plc_pulse_ms = 200
    plc_pulse_gap_ms = 100
    plc_poll_ms = 200
    plc_queue_max = 1
    plc_coil_ok = 3
    plc_coil_ng = 4
    plc_coil_error = 5
    plc_coil_alive = (11,)


def _patch_start(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)
    monkeypatch.setattr(plc, "ModbusPlcClient", lambda **kwargs: _FakeClient())
    return plc


def test_pulse_shorter_than_poll_warns_but_still_starts(monkeypatch, caplog):
    # Loop cuma bangun tiap PLC_POLL_MS, jadi pulse yang lebih pendek dari itu
    # secara fisik tidak bisa dihasilkan: ON dan OFF-nya jatuh di tick yang sama
    # dan PLC tidak pernah melihat rising edge-nya. Warning, bukan raise — PLC
    # itu fitur opsional, salah tuning tidak boleh menjatuhkan grading.
    plc = _patch_start(monkeypatch)
    cfg = _StartCfg()
    cfg.plc_pulse_ms = 100        # < plc_poll_ms 200

    with caplog.at_level(logging.WARNING, logger="palmgrade.plc"):
        worker = plc.start_plc_worker(cfg)

    assert worker is not None
    assert any("PLC_PULSE_MS" in r.message for r in caplog.records)


def test_pulse_equal_to_poll_does_not_warn(monkeypatch, caplog):
    plc = _patch_start(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="palmgrade.plc"):
        worker = plc.start_plc_worker(_StartCfg())

    assert worker is not None
    assert not [r for r in caplog.records if "PLC_PULSE_MS" in r.message]
