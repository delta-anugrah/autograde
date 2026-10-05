"""Batch 6.3, real parts together: `DisplayWorker` + `RuntimeState` + `StreamingService`.

The worker runs in its own thread, as on a line; a viewer is a thread reading the real
`generate_frames()`. Only `cv2` and the pipeline are the fakes of `tests/tampilan_palsu.py`,
so this runs in CI. What is checked is the hand-over between the three: the worker renders
only between the first chunk a viewer asks for and the moment that viewer leaves.
"""
from __future__ import annotations

import threading
import time

from tampilan_palsu import CvPalsu, FramePalsu, PipelinePalsu

from palmgrade.core.config import Settings
from palmgrade.services.streaming_service import StreamingService
from palmgrade.workers.display_worker import DisplayWorker
from palmgrade.workers.runtime_state import RuntimeState

BATAS_TUNGGU_S = 5.0
FPS_UJI = 200  # a short interval so the test does not wait on real render pacing


def _sampai(syarat, pesan: str) -> None:
    tenggat = time.monotonic() + BATAS_TUNGGU_S
    while not syarat():
        assert time.monotonic() < tenggat, pesan
        time.sleep(0.002)


class Line:
    def __init__(self) -> None:
        self.jejak: list = []
        self.state = RuntimeState()
        self.worker = DisplayWorker(
            state=self.state, pipeline=PipelinePalsu(self.jejak), settings=Settings(),
            target_fps=FPS_UJI, cv=CvPalsu(self.jejak),
        )
        self.stream = StreamingService(self.state, wait_timeout=0.05)
        self._berhenti = threading.Event()
        self._thread = threading.Thread(target=self._putar, daemon=True)

    def _putar(self) -> None:
        while not self._berhenti.is_set():
            self.state.last_yolo_frame = FramePalsu(2448, 2048, self.jejak)
            self.state.last_yolo_results = "hasil"
            self.state.last_yolo_frame_at = time.time()
            self.worker.run_once()

    def __enter__(self) -> Line:
        self._thread.start()
        return self

    def __exit__(self, *_galat) -> None:
        self._berhenti.set()
        self._thread.join(timeout=BATAS_TUNGGU_S)

    def render(self) -> int:
        return sum(1 for catatan in list(self.jejak) if catatan[0] == "imencode")


def _frame_pertama(stream) -> bytes:
    for potongan in stream:
        if b"Content-Type: image/jpeg" in potongan:
            return potongan
    raise AssertionError("the stream ended without a frame")


def test_line_tidak_merender_sampai_ada_yang_menonton_dan_berhenti_saat_ditinggal():
    with Line() as line:
        time.sleep(0.1)
        assert line.render() == 0, "frames were rendered with nobody watching"
        assert line.state.latest_frame is None

        stream = line.stream.generate_frames()
        pertama = _frame_pertama(stream)
        assert b"jpeg-" in pertama
        assert line.state.penonton_stream == 1
        _sampai(lambda: line.render() >= 5, "the display did not keep rendering for its viewer")

        stream.close()
        assert line.state.penonton_stream == 0
        _sampai(lambda: line.state.latest_frame is None, "the last picture was kept after the viewer left")
        diam = line.render()
        time.sleep(0.1)
        assert line.render() == diam, "the display kept rendering after the last viewer left"


def test_penonton_kedua_tetap_dilayani_saat_yang_pertama_pergi():
    with Line() as line:
        satu, dua = line.stream.generate_frames(), line.stream.generate_frames()
        _frame_pertama(satu)
        _frame_pertama(dua)
        assert line.state.penonton_stream == 2

        satu.close()
        sebelum = line.render()
        _sampai(lambda: line.render() >= sebelum + 5, "the display stopped while one viewer was still watching")
        assert b"jpeg-" in _frame_pertama(dua)
        dua.close()


def test_penonton_yang_kembali_mendapat_gambar_baru_bukan_gambar_lama():
    with Line() as line:
        stream = line.stream.generate_frames()
        _frame_pertama(stream)
        stream.close()
        _sampai(lambda: line.state.latest_frame is None, "the last picture was kept after the viewer left")
        terakhir = line.render()

        kembali = line.stream.generate_frames()
        pertama = _frame_pertama(kembali)
        kembali.close()

    nomor = int(pertama.split(b"jpeg-")[1].split(b"\r\n")[0])
    assert nomor > terakhir, "the returning viewer was handed a picture rendered before the pause"
