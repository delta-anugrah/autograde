"""A line's display side without cv2: fake frames, a fake `cv2`, a fake pipeline.

Each fake records what was asked of it, in order, in one shared `jejak` list, so a test can
say "the frame was shrunk BEFORE anything was drawn on it" and "nothing was done at all".
Imported as `tampilan_palsu` (pattern of `ai_palsu`).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from palmgrade.core.config import Settings
from palmgrade.workers.display_worker import DisplayWorker
from palmgrade.workers.runtime_state import RuntimeState

SENSOR = (2448, 2048)
STREAM = (1280, 720)


class FramePalsu:
    """Stands in for a numpy frame: a shape, and a record of copies and drawings."""

    def __init__(self, lebar: int, tinggi: int, jejak: list, nama: str = "frame") -> None:
        self.shape = (tinggi, lebar, 3)
        self.nama = nama
        self.digambari: list[str] = []
        self._jejak = jejak

    @property
    def ukuran(self) -> tuple[int, int]:
        return self.shape[1], self.shape[0]

    def copy(self) -> FramePalsu:
        self._jejak.append(("copy", self.ukuran))
        return FramePalsu(*self.ukuran, self._jejak, nama=f"salinan-{self.nama}")


class _Buf:
    def __init__(self, isi: bytes) -> None:
        self._isi = isi

    def tobytes(self) -> bytes:
        return self._isi


class CvPalsu:
    INTER_NEAREST = "nearest"
    FONT_HERSHEY_SIMPLEX = "font"
    LINE_AA = "aa"
    IMWRITE_JPEG_QUALITY = 1

    def __init__(self, jejak: list) -> None:
        self._jejak = jejak
        self._nomor = 0

    def resize(self, frame: FramePalsu, ukuran: tuple[int, int], interpolation=None) -> FramePalsu:
        self._jejak.append(("resize", frame.ukuran, ukuran))
        return FramePalsu(*ukuran, self._jejak, nama="kecil")

    def getTextSize(self, teks: str, *_args) -> tuple[tuple[int, int], int]:  # noqa: N802 (cv2's name)
        # Not a drawing step: measuring the FPS text to place it top-right (2026-10-08).
        return (18 * len(teks), 22), 8

    def putText(self, frame: FramePalsu, teks: str, *_args) -> None:  # noqa: N802 (cv2's name)
        self._jejak.append(("putText", frame.ukuran, teks))
        frame.digambari.append("teks")

    def imencode(self, ekstensi: str, frame: FramePalsu, _params) -> tuple[bool, _Buf]:
        self._nomor += 1
        self._jejak.append(("imencode", frame.ukuran))
        return True, _Buf(b"jpeg-%d" % self._nomor)


class PipelinePalsu:
    def __init__(self, jejak: list) -> None:
        self._jejak = jejak

    def draw_boxes(self, frame: FramePalsu, results: Any, *, tampilkan_confidence: bool = False,
                   skala: tuple[float, float] = (1.0, 1.0), ukuran_label: int = 100) -> FramePalsu:
        self.ukuran_label = ukuran_label
        self._jejak.append(("draw_boxes", frame.ukuran, skala, tampilkan_confidence))
        frame.digambari.append("kotak")
        return frame

    def draw_roi(self, frame: FramePalsu, garis_capture: int = 0, sumbu: str = "tegak", **pilihan) -> FramePalsu:
        self._jejak.append(("draw_roi", frame.ukuran, garis_capture, sumbu, pilihan))
        frame.digambari.append("roi")
        return frame


class JamPalsu:
    def __init__(self, mulai: float = 1_000.0) -> None:
        self.sekarang = mulai

    def __call__(self) -> float:
        return self.sekarang


class TampilanPalsu:
    """`DisplayWorker` with everything around it faked; `jejak` is the order of work."""

    def __init__(self, **setelan) -> None:
        self.jejak: list = []
        self.jam = JamPalsu()
        self.tidur: list[float] = []
        self.state = RuntimeState()
        self.settings = replace(
            Settings(), stream_width=STREAM[0], stream_height=STREAM[1], garis_capture=300,
            sumbu_garis="tegak", mode_dev=False, **setelan,
        )
        self.worker = DisplayWorker(
            state=self.state, pipeline=PipelinePalsu(self.jejak), settings=self.settings,
            target_fps=12, cv=CvPalsu(self.jejak), jam=self.jam, tidur=self.tidur.append,
        )

    def frame(self, ukuran: tuple[int, int] = SENSOR, nama: str = "sensor") -> FramePalsu:
        return FramePalsu(*ukuran, self.jejak, nama=nama)

    def hasil_yolo(self, frame: FramePalsu, results: Any = "hasil") -> None:
        """What `FrameProcessingWorker` leaves for the display after one inference."""
        self.state.last_yolo_frame = frame
        self.state.last_yolo_results = results
        self.state.last_yolo_frame_at = self.jam.sekarang

    def langkah(self) -> list[str]:
        return [catatan[0] for catatan in self.jejak]
