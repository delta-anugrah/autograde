from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.di = [False] * 16

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]


class _Cfg:
    plc_coil_base = 3
    plc_coil_alive = (11,)
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


def _worker(health_check=None):
    client = _FakeClient()
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_Cfg(),
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


def test_alive_coils_toggle_between_ticks():
    w, client = _worker()
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


def test_start_plc_worker_called_twice_returns_same_worker_one_client(monkeypatch):
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
        plc_queue_max = 20
        plc_coil_ok = 3
        plc_coil_ng = 4
        plc_coil_error = 5
        plc_coil_alive = (11,)

    settings = _Settings()
    first = plc.start_plc_worker(settings)
    second = plc.start_plc_worker(settings)

    assert first is second
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


def test_alive_coil_success_clears_stale_failed_retry():
    # Urutan: tick1 write alive GAGAL, tick2 retry-nya (level basi) GAGAL lagi tapi
    # write alive segar di tick yang sama SUKSES, tick3 tidak boleh menagih level basi.
    client = _AliveFlakyClient(alive_outcomes=[False, False, True])
    w = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_Cfg(),
    )
    w.run_once(now=0.0)   # alive toggle -> True, write gagal
    w.run_once(now=1.0)   # step 2 retry level basi (True) gagal; step 3 toggle -> False, sukses
    w.run_once(now=1.1)   # belum waktunya toggle lagi; tidak boleh ada retry level basi

    alive_writes = [v for (addr, v) in client.writes if addr == 11]
    assert alive_writes == [False]


def test_error_coil_raised_when_pulses_are_dropped():
    w, client = _worker()
    w.scheduler.queue_max = 1
    for _ in range(5):
        w.submit("rej")
    w.run_once(now=0.0)
    assert (5, True) in client.writes      # coil base+2 = 5


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
