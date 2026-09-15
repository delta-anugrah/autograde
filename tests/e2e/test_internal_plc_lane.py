"""`plc_coil_command` — the line-side handler the console's PLC test screen
proxies to. This is where the busy-line guard actually runs: the console
process never owns `RuntimeState`, only the line does (`main.py`, not
`console_main.py`, calls `start_plc_worker`), so this is the one place the
check can't be bypassed by a stale cross-process read.

In `tests/e2e/`, not `tests/unit/`: `internal_controller.py` imports
`CaptureService` at module scope (for `manual_reject_command`), which chains
to `core/constants.py` -> `cv2` — importing it from `tests/unit/` would break
CI collection there (CI's `pip install` list has no opencv-python; see
`ci.yml` and CLAUDE.md's "jangan seret hardware, torch, atau cv2 ke CI").
`tests/e2e/` is not CI-gated, so it can afford the real import.

Exercises the real `palmgrade.plc` module functions (`picu_coil`,
`testable_coils`) against a real `PlcWorker` + fake Modbus client, the same
`monkeypatch.setattr(plc, "_worker", ...)` pattern `test_plc_worker.py` uses
for `diagnostics()` — not a mock of the guard itself, so a regression that
silently removed the `state.current_assignment_id` check would fail this.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from palmgrade.controllers.internal_controller import plc_coil_command, plc_state
from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker
from palmgrade.schemas.internal_schema import PlcCoilCommandRequest
from palmgrade.workers.runtime_state import RuntimeState


class _FakeClient:
    def __init__(self):
        self.writes: list[tuple[int, bool]] = []
        self.di = [False] * 16

    def write_coil(self, address, value):
        self.writes.append((address, value))
        return True

    def read_discrete_inputs(self, start, count):
        return self.di[start:start + count]

    def close(self):
        pass


class _Cfg:
    plc_coil_base = 0
    plc_coil_alive = (9,)
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_count = 16
    plc_coil_manual = 11

    @property
    def plc_coil_ok(self):
        return self.plc_coil_base

    @property
    def plc_coil_ng(self):
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self):
        return self.plc_coil_base + 2


def _plc_aktif(monkeypatch, *, queue_max: int = 20):
    import palmgrade.plc as plc

    client = _FakeClient()
    worker = PlcWorker(
        client=client,
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=queue_max),
        settings=_Cfg(),
    )
    monkeypatch.setattr(plc, "_worker", worker, raising=False)
    # get_settings() is imported LOCALLY inside each controller function (same
    # style as piston_command/line_status already in this file), so the patch
    # target is its real source, not an attribute on internal_controller.
    monkeypatch.setattr("palmgrade.core.dependencies.get_settings", lambda: _Cfg())
    return worker, client


def test_line_menganggur_mengizinkan_coil_dipicu(monkeypatch):
    worker, client = _plc_aktif(monkeypatch)
    state = RuntimeState(current_assignment_id=None)
    req = PlcCoilCommandRequest(machine_id="m-1", coil=0, requested_by="s@b.c")

    hasil = _run(plc_coil_command(req, state))

    assert hasil.fired is True
    assert hasil.coil == 0
    worker.run_once(now=0.0)
    assert (0, True) in client.writes


def test_line_sibuk_menolak_409(monkeypatch):
    """The guard this whole feature exists to prove: `current_assignment_id`
    not None on THIS line's own RuntimeState refuses the fire outright."""
    worker, client = _plc_aktif(monkeypatch)
    state = RuntimeState(current_assignment_id="a-1")
    req = PlcCoilCommandRequest(machine_id="m-1", coil=0, requested_by="s@b.c")

    with pytest.raises(HTTPException) as exc:
        _run(plc_coil_command(req, state))

    assert exc.value.status_code == 409
    assert client.writes == []


def test_coil_asing_ditolak_422_sebelum_menyentuh_state(monkeypatch):
    """An unmapped coil is refused even on an idle line — validated against
    the computed set, not a hardcoded range, and before the busy check."""
    worker, client = _plc_aktif(monkeypatch)
    state = RuntimeState(current_assignment_id=None)
    req = PlcCoilCommandRequest(machine_id="m-1", coil=999, requested_by="s@b.c")

    with pytest.raises(HTTPException) as exc:
        _run(plc_coil_command(req, state))

    assert exc.value.status_code == 422
    assert client.writes == []


def test_coil_alive_ditolak_walau_line_menganggur(monkeypatch):
    """Coil 9 (HEARTBIT PC ON) must never be reachable from this lane, busy
    or not — firing it can make the panel believe the PC died."""
    worker, client = _plc_aktif(monkeypatch)
    state = RuntimeState(current_assignment_id=None)
    req = PlcCoilCommandRequest(machine_id="m-1", coil=9, requested_by="s@b.c")

    with pytest.raises(HTTPException) as exc:
        _run(plc_coil_command(req, state))

    assert exc.value.status_code == 422
    assert client.writes == []


def test_piston_manual_ada_di_daftar_saat_dikonfigurasi(monkeypatch):
    worker, client = _plc_aktif(monkeypatch)
    state = RuntimeState(current_assignment_id=None)
    req = PlcCoilCommandRequest(machine_id="m-1", coil=11, requested_by="s@b.c")

    hasil = _run(plc_coil_command(req, state))

    assert hasil.fired is True


def test_antrean_penuh_melapor_fired_false_bukan_error(monkeypatch):
    """`enqueue()` returning False (queue full, pulse dropped) must reach the
    caller as `fired: False`, HTTP 200 — the drop is real, but it is not a
    server error, and swallowing it would tell the screen "fired" for nothing."""
    worker, client = _plc_aktif(monkeypatch, queue_max=1)
    state = RuntimeState(current_assignment_id=None)
    worker.picu_coil(0)   # fill the one queue slot this coil gets
    req = PlcCoilCommandRequest(machine_id="m-1", coil=0, requested_by="s@b.c")

    hasil = _run(plc_coil_command(req, state))

    assert hasil.fired is False


def test_plc_state_melapor_mati_saat_worker_tidak_ada(monkeypatch):
    import palmgrade.plc as plc

    monkeypatch.setattr(plc, "_worker", None, raising=False)

    hasil = _run(plc_state())

    assert hasil.enabled is False


def test_plc_state_melapor_di_dan_coil_yang_bisa_diuji(monkeypatch):
    worker, client = _plc_aktif(monkeypatch)
    client.di[0] = True
    worker.run_once(now=0.0)   # worker.inputs is only populated by a poll tick

    hasil = _run(plc_state())

    assert hasil.enabled is True
    assert hasil.inputs[0] is True
    assert 9 not in hasil.testable_coils     # alive tetap tidak boleh muncul di layar


def _run(coro):
    """Drive one coroutine to completion — these controllers await nothing
    that needs a real event loop (no I/O), so asyncio.run is enough."""
    import asyncio

    return asyncio.run(coro)
