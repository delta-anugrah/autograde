"""Janjang yang DITOLAK konsol tercatat di tab Log (final review batch 2, konsol I1).

Line menyimpan janjang yang dijawab 400 dan mencobanya lagi tiap 10 menit selamanya.
Dulu penolakan itu cuma sampai di `docker logs` line (line tidak punya log_sink), jadi
tab Log konsol, alat utama support, tidak menyebut apa pun. Sekarang satu WARNING per
`event_id` per proses: cukup untuk ditemukan, tidak membanjiri log tiap 10 menit.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services import console_service
from palmgrade.services.console_service import ConsoleService


class _Line:
    pass


@pytest.fixture
def service(tmp_path):
    return ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), ConsoleStore(tmp_path / "console.db"), _Line())


def _janjang(service: ConsoleService, event_id: str, timestamp: str = "bukan-jam") -> dict:
    return {
        "event_id": event_id, "machine_id": service.lines[1].machine_id, "timestamp": timestamp,
        "ripeness_status": "ACC",
    }


def _ditolak(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "DITOLAK konsol" in r.getMessage()]


def test_penolakan_satu_warning_menyebut_line_janjang_jam_dan_alasan(service, caplog):
    with caplog.at_level(logging.DEBUG, logger=console_service.__name__), pytest.raises(ValueError):
        service.ingest(_janjang(service, "ev-rusak"))

    [catatan] = _ditolak(caplog)
    pesan = catatan.getMessage()
    assert catatan.levelno == logging.WARNING
    assert service.lines[1].line_code in pesan
    assert "ev-rusak" in pesan and "bukan-jam" in pesan
    assert "MANUAL" in pesan


def test_kiriman_ulang_janjang_yang_sama_tidak_mengulang_warning(service, caplog):
    """Line mengirim ulang tiap 10 menit: WARNING tiap kali mengulang masalah yang sama."""
    with caplog.at_level(logging.DEBUG, logger=console_service.__name__):
        for _ in range(3):
            with pytest.raises(ValueError):
                service.ingest(_janjang(service, "ev-rusak"))

    assert [r.levelno for r in _ditolak(caplog)] == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_janjang_lain_yang_ditolak_dapat_warning_sendiri(service, caplog):
    with caplog.at_level(logging.WARNING, logger=console_service.__name__):
        for event_id in ("ev-a", "ev-b"):
            with pytest.raises(ValueError):
                service.ingest(_janjang(service, event_id))

    assert len(_ditolak(caplog)) == 2


def test_janjang_sah_tidak_mencatat_apa_pun(service, caplog):
    with caplog.at_level(logging.DEBUG, logger=console_service.__name__):
        service.ingest(_janjang(service, "ev-sah", "2026-09-28T03:00:00+00:00"))

    assert _ditolak(caplog) == []
