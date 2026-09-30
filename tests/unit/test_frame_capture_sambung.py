"""`FrameCaptureWorker` mencatat hasil tiap sambung ulang (batch 3.6).

Worker ASLI dengan kamera palsu. Yang dijaga: lima grab gagal memicu satu sambung
ulang, dan hasilnya (berhasil / gagal) sampai ke `RuntimeState`, karena dari
situ penjaga membedakan kamera putus dari kamera yang tersambung tapi diam.
"""
from __future__ import annotations

import pytest
from ai_palsu import LinePalsu

from palmgrade.workers import frame_capture_worker


@pytest.fixture(autouse=True)
def tanpa_tidur(monkeypatch):
    """Sambung ulang menunggu 1 detik sungguhan; test tidak perlu menunggunya."""
    monkeypatch.setattr(frame_capture_worker.time, "sleep", lambda _detik: None)


def _grab_gagal(line: LinePalsu, kali: int) -> None:
    for _ in range(kali):
        line.capture.run_once()


def test_sambung_ulang_yang_berhasil_dicatat_berhasil():
    line = LinePalsu()
    line.kamera.bisa_sambung_ulang = True
    line.kamera.mengirim = False
    _grab_gagal(line, 5)
    assert line.state.kamera_sambung_ok is True
    assert line.state.kamera_pulih_at == 1_000.0


def test_sambung_ulang_yang_gagal_dicatat_gagal():
    line = LinePalsu()
    line.kamera.bisa_sambung_ulang = True
    line.kamera.sambung_gagal = True
    line.kamera.connected = False
    _grab_gagal(line, 5)
    assert line.state.kamera_sambung_ok is False


def test_sebelum_lima_grab_gagal_belum_ada_sambung_ulang():
    line = LinePalsu()
    line.kamera.bisa_sambung_ulang = True
    line.kamera.mengirim = False
    _grab_gagal(line, 4)
    assert line.state.kamera_sambung_ok is None


def test_sumber_tanpa_sambung_ulang_tidak_mencatat_apa_pun():
    """Berkas video tidak disambung ulang (`supports_reconnect` False)."""
    line = LinePalsu()
    line.kamera.mengirim = False
    _grab_gagal(line, 10)
    assert line.state.kamera_sambung_ok is None
