"""Alarm PLC ikut disimpan worker status line, supaya /api/console/state
membawanya tanpa memanggil line secara langsung (satu line mati tidak boleh
membekukan konsol — lihat docstring line_status_worker.py)."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers.line_status_worker import LineStatusWorker


class _Line:
    def __init__(self, jawab=None, down=False):
        self._jawab = jawab
        self._down = down

    async def status(self, line):
        if self._down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        return self._jawab


def _worker(line_client):
    # `console_lines` adalah PROPERTY (core/config.py), bukan method.
    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    return LineStatusWorker(lines, line_client, interval_s=0)


def test_alarms_disimpan_apa_adanya():
    w = _worker(_Line({"piston": None, "ffb_source": None,
                       "alarms": [{"code": "motor_fault", "n": 3}]}))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status["alarms"] == [{"code": "motor_fault", "n": 3}]


def test_line_versi_lama_tanpa_field_alarms_dibaca_kosong():
    w = _worker(_Line({"piston": None, "ffb_source": None}))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status["alarms"] == []


def test_line_mati_tidak_punya_alarms_palsu():
    w = _worker(_Line(down=True))
    asyncio.run(w.run_once())
    (status,) = w.snapshot().values()
    assert status == {"reachable": False}
