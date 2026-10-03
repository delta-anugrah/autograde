"""Reconnect camera button: the capture thread reconnects on request (2026-10-04).

The real `FrameCaptureWorker` with a fake camera. The route only raises a flag on
`RuntimeState`; the capture thread is the one that touches the camera, under
`state.lock` (rule 3), on its next turn, with no backoff wait. A request that lands
while the automatic path is waiting out its backoff cuts that wait short.
"""
from __future__ import annotations

import logging

import pytest
from ai_palsu import KameraPalsu, LinePalsu

from palmgrade.workers import frame_capture_worker
from palmgrade.workers.runtime_state import RuntimeState


class KameraHitung(KameraPalsu):
    """Counts connects and disconnects, and records whether `state.lock` was held."""

    def __init__(self, state: RuntimeState) -> None:
        super().__init__()
        self._state = state
        self.sambung = 0
        self.putus = 0
        self.tanpa_kunci: list[str] = []

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        self.sambung += 1
        if not self._state.lock.locked():
            self.tanpa_kunci.append("connect")
        super().connect(index, serial, feature_file)

    def disconnect(self) -> None:
        self.putus += 1
        if not self._state.lock.locked():
            self.tanpa_kunci.append("disconnect")
        super().disconnect()


@pytest.fixture
def tidur(monkeypatch):
    """Every sleep the worker asks for, without waiting it out."""
    dicatat: list[float] = []
    monkeypatch.setattr(frame_capture_worker.time, "sleep", dicatat.append)
    return dicatat


def _line() -> tuple[LinePalsu, KameraHitung]:
    line = LinePalsu()
    kamera = KameraHitung(line.state)
    kamera.bisa_sambung_ulang = True
    line.kamera = kamera
    line.capture.camera = kamera
    return line, kamera


def test_state_hands_a_request_over_once():
    state = RuntimeState()
    assert state.ambil_permintaan_sambung_ulang() is None
    state.minta_sambung_ulang_kamera("Pak Budi")
    assert state.ambil_permintaan_sambung_ulang() == "Pak Budi"
    assert state.ambil_permintaan_sambung_ulang() is None


def test_a_request_reconnects_once_under_the_camera_lock(tidur):
    line, kamera = _line()
    line.state.minta_sambung_ulang_kamera("Pak Budi")

    line.capture.run_once()

    assert (kamera.putus, kamera.sambung) == (1, 1)
    assert kamera.tanpa_kunci == []
    assert line.state.kamera_sambung_ok is True
    # Consumed: the next turn grabs a frame instead of reconnecting again.
    line.capture.run_once()
    assert (kamera.putus, kamera.sambung) == (1, 1)
    assert line.state.frame_terakhir_at > 0


def test_a_manual_reconnect_does_not_wait_out_a_backoff(tidur):
    line, _kamera = _line()
    line.capture._reconnect_backoff = 30.0
    line.state.minta_sambung_ulang_kamera("Pak Budi")

    line.capture.run_once()

    assert sum(tidur) < 1.0, tidur


def test_a_healthy_camera_keeps_its_backoff_base_after_a_manual_reconnect(tidur):
    line, _kamera = _line()
    line.state.minta_sambung_ulang_kamera("Pak Budi")
    line.capture.run_once()
    assert line.capture._reconnect_backoff == frame_capture_worker._RECONNECT_BACKOFF_BASE


def test_the_outcome_names_who_asked(tidur, caplog):
    line, _kamera = _line()
    line.state.minta_sambung_ulang_kamera("Pak Budi")
    with caplog.at_level(logging.INFO, logger=frame_capture_worker.__name__):
        line.capture.run_once()
    baris = [r for r in caplog.records if "Pak Budi" in r.getMessage()]
    assert len(baris) == 1 and baris[0].levelno == logging.INFO, [r.getMessage() for r in caplog.records]


def test_a_failed_manual_reconnect_is_one_warning_not_an_error(tidur, caplog):
    line, kamera = _line()
    kamera.sambung_gagal = True
    line.state.minta_sambung_ulang_kamera("Pak Budi")
    with caplog.at_level(logging.DEBUG, logger=frame_capture_worker.__name__):
        line.capture.run_once()
    assert line.state.kamera_sambung_ok is False
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    gagal = [r for r in caplog.records if r.levelno == logging.WARNING and "Pak Budi" in r.getMessage()]
    assert len(gagal) == 1, [r.getMessage() for r in caplog.records]
    assert "kamera tidak ditemukan" in gagal[0].getMessage()


def test_a_source_without_reconnect_is_left_alone(tidur):
    line, kamera = _line()
    kamera.bisa_sambung_ulang = False
    line.state.minta_sambung_ulang_kamera("Pak Budi")
    line.capture.run_once()
    assert (kamera.putus, kamera.sambung) == (0, 0)
    assert line.state.ambil_permintaan_sambung_ulang() is None


def test_the_automatic_reconnect_also_holds_the_camera_lock(tidur):
    line, kamera = _line()
    kamera.mengirim = False
    for _ in range(frame_capture_worker._MAX_CONSECUTIVE_FAILURES):
        line.capture.run_once()
    assert (kamera.putus, kamera.sambung) == (1, 1)
    assert kamera.tanpa_kunci == []


def test_a_request_during_the_backoff_cuts_the_wait_short(monkeypatch):
    """The automatic path waits up to 30 s between tries. A press in that wait must not
    sit behind it, and must not cause a second reconnect right after the first."""
    line, kamera = _line()
    kamera.mengirim = False
    line.capture._reconnect_backoff = 30.0
    monkeypatch.setattr(frame_capture_worker.time, "sleep", lambda _detik: None)
    for _ in range(frame_capture_worker._MAX_CONSECUTIVE_FAILURES - 1):
        line.capture.run_once()
    dicatat: list[float] = []

    def tidur(detik: float) -> None:
        dicatat.append(detik)
        if len(dicatat) == 1:  # the operator presses the button during the first slice
            line.state.minta_sambung_ulang_kamera("Pak Budi")

    monkeypatch.setattr(frame_capture_worker.time, "sleep", tidur)
    line.capture.run_once()  # the fifth failed grab: the automatic reconnect starts its backoff

    assert dicatat and sum(dicatat) < 1.0, dicatat
    assert (kamera.putus, kamera.sambung) == (1, 1)
    assert line.state.ambil_permintaan_sambung_ulang() is None
