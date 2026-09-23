"""`/internal/status` membawa alarm PLC supaya konsol tidak perlu jalur baru.

`LineStatusWorker` sudah memanggil endpoint ini tiap detik untuk piston;
alarm cukup menumpang. Di `tests/e2e/` karena `internal_controller` menyeret
cv2/torch lewat CaptureService — lihat docstring test_internal_plc_lane.py.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("torch")

from palmgrade.controllers import internal_controller  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402


def _status(monkeypatch, bits):
    monkeypatch.setattr(internal_controller, "_plc_inputs", lambda: bits, raising=False)
    return asyncio.run(internal_controller.line_status(RuntimeState()))


def test_status_membawa_alarm_dari_bit_plc(monkeypatch):
    bits = [False] * 16
    bits[2] = True      # MOTOR 3
    bits[11] = True     # E-STOP
    jawab = _status(monkeypatch, bits)
    assert jawab.alarms == [{"code": "motor_fault", "n": 3}, {"code": "estop"}]


def test_plc_mati_berarti_alarms_kosong_bukan_error(monkeypatch):
    jawab = _status(monkeypatch, [])
    assert jawab.alarms == []


# ── /internal/plc ikut membawa peran tiap coil ──────────────────────────────


def test_plc_state_membawa_coil_base_supaya_layar_bisa_menamai(monkeypatch):
    """Konsol tidak boleh menebak coil mana yang OK/NG/ERROR dari nomornya.
    Tanpa `coil_base`, tombol "Test coil 1003" tidak bisa jadi "CAMERA 2 OK"
    kecuali dengan memaku angka — yang langsung salah kalau panel memberi
    blok alamat lain."""
    import asyncio

    from palmgrade import plc as plc_mod
    from palmgrade.controllers.internal_controller import plc_state
    from palmgrade.plc.pulse import PulseScheduler
    from palmgrade.plc.worker import PlcWorker

    class _Cfg:
        plc_coil_base = 1003
        plc_coil_alive = ()
        plc_alive_toggle_ms = 0
        plc_poll_ms = 200
        plc_di_count = 16
        plc_di_base = 1100
        plc_coil_manual = None
        plc_hold_ms = 0

        @property
        def plc_coil_ok(self): return self.plc_coil_base
        @property
        def plc_coil_ng(self): return self.plc_coil_base + 1
        @property
        def plc_coil_error(self): return self.plc_coil_base + 2

    class _Klien:
        def write_coil(self, *a): return True
        def read_discrete_inputs(self, *a): return [False] * 16
        def close(self): pass

    cfg = _Cfg()
    worker = PlcWorker(client=_Klien(),
                       scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
                       settings=cfg)
    monkeypatch.setattr(plc_mod, "_worker", worker, raising=False)
    monkeypatch.setattr("palmgrade.core.dependencies.get_settings", lambda: cfg)

    hasil = asyncio.run(plc_state())

    assert hasil.coil_base == 1003
    assert sorted(hasil.testable_coils) == [1003, 1004, 1005]
