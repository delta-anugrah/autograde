"""Frame clean diteruskan capture worker ke recorder — tanpa pernah
membahayakan line.

Titik sadapnya `FrameCaptureWorker`, sebelum inference, jadi yang direkam
otomatis bersih tanpa bbox. Yang dijaga di sini: recorder yang rusak atau lambat
tidak boleh menjatuhkan capture worker, karena itu berarti mematikan line demi
fitur yang cuma dipakai saat menelusuri masalah.
"""
from __future__ import annotations

import numpy as np

from palmgrade.integrations.camera.base import CameraSource
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState


class RecorderPalsu:
    def __init__(self, meledak: bool = False) -> None:
        self.diterima: list = []
        self._meledak = meledak

    def tulis(self, frame) -> None:
        if self._meledak:
            raise RuntimeError("encoder rusak")
        self.diterima.append(frame)


class KameraPalsu(CameraSource):
    def __init__(self, frames) -> None:
        super().__init__()
        self._frames = list(frames)

    def connect(self, index: int = 0, serial=None, feature_file=None) -> None:
        self.connected = True

    def grab_frame(self):
        return self._frames.pop(0) if self._frames else None

    def disconnect(self) -> None:
        self.connected = False


def _worker(state: RuntimeState, frames) -> FrameCaptureWorker:
    return FrameCaptureWorker(camera=KameraPalsu(frames), state=state, target_fps=0)


def _frame():
    return np.zeros((4, 4, 3), dtype=np.uint8)


def test_frame_diteruskan_ke_recorder():
    state = RuntimeState()
    rec = RecorderPalsu()
    state.video_recorder = rec

    _worker(state, [_frame()]).run_once()

    assert len(rec.diterima) == 1


def test_frame_yang_direkam_sama_dengan_yang_dipakai_deteksi():
    # Kalau recorder menerima salinan yang sudah diubah, rekamannya bukan lagi
    # bukti apa yang dilihat model.
    state = RuntimeState()
    rec = RecorderPalsu()
    state.video_recorder = rec
    frame = _frame()

    _worker(state, [frame]).run_once()

    assert rec.diterima[0] is state.latest_raw_frame


def test_tanpa_recorder_capture_tetap_jalan():
    state = RuntimeState()
    state.video_recorder = None

    _worker(state, [_frame()]).run_once()

    assert state.latest_raw_frame is not None


def test_recorder_meledak_tidak_menjatuhkan_capture():
    # Fitur developer tidak boleh bisa mematikan line.
    state = RuntimeState()
    state.video_recorder = RecorderPalsu(meledak=True)

    _worker(state, [_frame()]).run_once()

    assert state.latest_raw_frame is not None


def test_frame_kosong_tidak_diteruskan():
    # Kamera yang gagal memberi frame bukan alasan menulis None ke rekaman.
    state = RuntimeState()
    rec = RecorderPalsu()
    state.video_recorder = rec

    _worker(state, [None]).run_once()

    assert rec.diterima == []


def test_bawaan_runtime_state_tanpa_recorder():
    # Line yang tidak pernah merekam tidak boleh menyentuh modul rekam.
    assert RuntimeState().video_recorder is None
