"""Rakitan line TANPA torch untuk test penjaga AI mati (batch 2.1).

Kamera dan pipeline palsu cukup untuk menjalankan `FrameCaptureWorker` dan
`FrameProcessingWorker` yang ASLI, satu putaran demi satu putaran, dengan jam
palsu yang sama untuk cap waktu dan penilai. Terimpor sebagai `ai_palsu`
(pola `model_palsu`).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from palmgrade.core.config import Settings
from palmgrade.domain.kesehatan_kamera import StatistikAliran
from palmgrade.domain.setelan_kamera import NilaiSetelan
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.services.penjaga_ai import PenjagaAi
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.frame_processing_worker import FrameProcessingWorker
from palmgrade.workers.runtime_state import RuntimeState

JAM_DINDING = 1_790_000_000.0


class JamPalsu:
    def __init__(self, mulai: float = 1_000.0) -> None:
        self.sekarang = mulai

    def __call__(self) -> float:
        return self.sekarang


class KameraPalsu(CameraSource):
    """Mengirim frame hitam kecil selama `mengirim`; `habis` meniru video tanpa ulang.

    Batch 3.6: `bisa_sambung_ulang` menyalakan jalur sambung ulang
    `FrameCaptureWorker` (Hikrobot/webcam), dan `sambung_gagal` membuat
    `connect()` melempar seperti kamera yang kabelnya dicabut.
    """

    def __init__(self) -> None:
        super().__init__()
        self.connected = True
        self.mengirim = True
        self.habis = False
        self.bisa_sambung_ulang = False
        self.sambung_gagal = False
        self.suhu: float | None = None      # None = sumber tanpa sensor (webcam/video)
        self.suhu_dibaca = 0                # berapa kali line bertanya
        self.suhu_melempar = False          # SDK melempar, bukan memberi kode
        self.statistik: StatistikAliran | None = None   # None = sumber tanpa hitungan aliran
        self.statistik_melempar = False
        self.setelan: list[NilaiSetelan] | None = None   # None = not a Hikrobot camera

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        if self.sambung_gagal:
            raise RuntimeError("kamera tidak ditemukan")
        self.connected = True

    def grab_frame(self):
        if not (self.connected and self.mengirim) or self.habis:
            return None
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def disconnect(self) -> None:
        self.connected = False

    def get_temperature(self) -> float | None:
        self.suhu_dibaca += 1
        if self.suhu_melempar:
            raise OSError("handle kamera sudah dilepas")
        return self.suhu

    def get_statistik_aliran(self) -> StatistikAliran | None:
        if self.statistik_melempar:
            raise OSError("handle kamera sudah dilepas")
        return self.statistik

    @property
    def punya_setelan(self) -> bool:
        return self.setelan is not None

    def baca_setelan(self) -> list[NilaiSetelan]:
        if not self.connected:
            raise RuntimeError("camera not connected")
        return list(self.setelan or [])

    @property
    def exhausted(self) -> bool:
        return self.habis

    @property
    def supports_reconnect(self) -> bool:
        return self.bisa_sambung_ulang


class HasilKosong:
    boxes = None
    names: dict = {}


class PipelinePalsu:
    """`galat` terisi = `track_ripeness` melempar, seperti CUDA yang rusak."""

    def __init__(self) -> None:
        self.galat: Exception | None = None
        self.dipanggil = 0

    def track_ripeness(self, frame, conf=None):
        self.dipanggil += 1
        if self.galat is not None:
            raise self.galat
        return HasilKosong()

    def reset_tracker(self) -> None:
        pass

    def draw_boxes(self, frame, results, **_):
        return frame


class PenulisPalsu:
    def submit(self, job) -> None:
        pass


class LinePalsu:
    """Satu line: state + kamera + dua worker asli + penjaga, satu jam palsu."""

    def __init__(self, **setelan) -> None:
        self.jam = JamPalsu()
        self.state = RuntimeState(jam=self.jam)
        self.kamera = KameraPalsu()
        self.pipeline = PipelinePalsu()
        self.settings = replace(Settings(), **{"ai_mati_detik": 30, "lic_enabled": False, **setelan})
        self.capture = FrameCaptureWorker(camera=self.kamera, state=self.state, target_fps=0)
        self.deteksi = FrameProcessingWorker(
            pipeline=self.pipeline, state=self.state, storage=object(), webhook=None,
            settings=self.settings, outbox_store=None, capture_saver=PenulisPalsu(),
            tidur=lambda _detik: None,
        )
        self.penjaga = PenjagaAi(
            settings=self.settings, state=self.state, kamera=self.kamera,
            jam_dinding=lambda: JAM_DINDING + (self.jam.sekarang - 1_000.0),
        )
        self.state.penjaga_ai = self.penjaga

    def mulai(self) -> None:
        """Yang dilakukan `run_loop` sebelum putaran pertama: `mulai()` worker ASLI."""
        self.deteksi.mulai()

    def jalan(self, detik: int, *, deteksi: bool = True) -> None:
        """Satu frame per detik: kamera mengambil, deteksi (kalau jalan) memproses."""
        for _ in range(detik):
            self.capture.run_once()
            if deteksi:
                self.deteksi.putaran()
            self.jam.sekarang += 1
