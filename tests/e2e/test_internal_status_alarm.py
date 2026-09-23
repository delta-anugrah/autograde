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
