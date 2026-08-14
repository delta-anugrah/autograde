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
