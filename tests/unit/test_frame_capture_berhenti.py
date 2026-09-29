"""Capture worker berhenti saat line menutup (parkiran Task 3 batch 2.2).

Langkah tutup "kamera" dulu cuma memanggil `camera.disconnect()`. Thread capture tetap
berputar: frame kosong lima kali memicu `_try_reconnect`, yang MEMBUKA kamera GigE lagi
di tengah penutupan, dan kamera itu dipegang sampai proses benar-benar pergi.
"""
from __future__ import annotations

import threading

from palmgrade.integrations.camera.base import CameraSource
from palmgrade.workers import frame_capture_worker as modul
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState


class _Kamera(CameraSource):
    supports_reconnect = True

    def __init__(self) -> None:
        super().__init__()
        self.sambung = 0

    def connect(self, index: int = 0, serial=None, feature_file=None) -> None:
        self.sambung += 1
        self.connected = True

    def grab_frame(self):
        return None if not self.connected else object()

    def disconnect(self) -> None:
        self.connected = False


def test_berhenti_mengakhiri_run_loop():
    kamera = _Kamera()
    kamera.connect()
    worker = FrameCaptureWorker(camera=kamera, state=RuntimeState(), target_fps=0)
    benang = threading.Thread(target=worker.run_loop, daemon=True)
    benang.start()

    worker.berhenti()
    benang.join(3)

    assert not benang.is_alive()


def test_tidak_menyambung_ulang_kamera_sesudah_berhenti(monkeypatch):
    monkeypatch.setattr(modul.time, "sleep", lambda _s: None)
    kamera = _Kamera()
    worker = FrameCaptureWorker(camera=kamera, state=RuntimeState(), target_fps=0)
    worker.berhenti()

    for _ in range(modul._MAX_CONSECUTIVE_FAILURES + 2):
        worker.run_once()

    assert kamera.sambung == 0
