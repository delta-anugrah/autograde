"""`DisplayWorker` shrinks first, draws small, and rests when nobody watches (batch 6.3).

Before: every render copied the 2448x2048 frame (14.3 MB), drew the boxes on it, shrank the
result to 1280x720 and encoded a JPEG, 12 times a second on every line, whether or not any
screen showed that line.

Rule 4 is pinned too: `DisplayWorker` stays the only writer of `state.latest_frame`, under
`frame_condition`, and wakes every waiting viewer.

No cv2 here: the worker takes its `cv2` as an argument, and the fakes record the order of
work (`tests/tampilan_palsu.py`).
"""
from __future__ import annotations

import threading

import pytest
from tampilan_palsu import SENSOR, STREAM, TampilanPalsu

from palmgrade.domain.skala_tampilan import TANPA_SKALA

SKALA = (STREAM[0] / SENSOR[0], STREAM[1] / SENSOR[1])


@pytest.fixture
def layar() -> TampilanPalsu:
    return TampilanPalsu()


# ------------------------------------------------------------------ nobody watching


def test_tanpa_penonton_tidak_ada_yang_dikerjakan(layar):
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()

    assert layar.jejak == [], "work was done for a stream nobody reads"
    assert layar.state.latest_frame is None


def test_tanpa_penonton_worker_tetap_berjeda_bukan_berputar_kosong(layar):
    layar.worker.run_once()
    layar.worker.run_once()

    assert layar.tidur and all(jeda > 0 for jeda in layar.tidur), "an idle loop must not spin a core"


def test_penonton_terakhir_pergi_gambar_lama_dibuang(layar):
    """A viewer that comes back an hour later must wait for a new picture, not be handed the
    last one rendered before the pause."""
    layar.hasil_yolo(layar.frame())
    layar.state.penonton_masuk()
    layar.worker.run_once()
    assert layar.state.latest_frame == b"jpeg-1"

    layar.state.penonton_keluar()
    layar.jejak.clear()
    layar.worker.run_once()

    assert layar.state.latest_frame is None
    assert layar.jejak == []


def test_penonton_datang_lagi_render_berjalan_lagi(layar):
    layar.hasil_yolo(layar.frame())
    layar.worker.run_once()
    assert layar.state.latest_frame is None

    layar.state.penonton_masuk()
    layar.worker.run_once()

    assert layar.state.latest_frame == b"jpeg-1"


# ------------------------------------------------------------------ shrink first, draw small


def test_frame_dikecilkan_dulu_baru_digambari(layar):
    layar.state.penonton_masuk()
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()

    assert layar.langkah() == ["resize", "draw_boxes", "draw_roi", "putText", "putText", "imencode"]
    assert layar.jejak[0] == ("resize", SENSOR, STREAM)
    assert all(catatan[1] == STREAM for catatan in layar.jejak[1:]), "something was drawn or encoded at full size"


def test_frame_sensor_tidak_disalin_dan_tidak_digambari(layar):
    """The sensor frame is shared with the detection thread, which hands the same array to the
    photo writer as the clean copy. It is read, never copied at full size, never drawn on."""
    sensor = layar.frame()
    layar.state.penonton_masuk()
    layar.hasil_yolo(sensor)

    layar.worker.run_once()

    assert "copy" not in layar.langkah()
    assert sensor.digambari == []


def test_kotak_digambar_dengan_skala_sensor_ke_stream(layar):
    layar.state.penonton_masuk()
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()

    _, ukuran, skala, _ = next(c for c in layar.jejak if c[0] == "draw_boxes")
    assert ukuran == STREAM
    assert skala == pytest.approx(SKALA)


def test_frame_yang_sudah_seukuran_stream_disalin_bukan_digambari_langsung(layar):
    """A webcam or a video already at 1280x720 needs no shrink, but still must not be drawn on."""
    sumber = layar.frame(STREAM, nama="video")
    layar.state.penonton_masuk()
    layar.hasil_yolo(sumber)

    layar.worker.run_once()

    assert layar.langkah()[0] == "copy" and "resize" not in layar.langkah()
    assert sumber.digambari == []
    assert next(c for c in layar.jejak if c[0] == "draw_boxes")[2] == TANPA_SKALA


def test_garis_capture_dan_roi_tetap_digambar_di_ruang_stream(layar):
    """Both are set by the operator in stream pixels and were always drawn after the shrink:
    they must be given the same numbers on the same frame size as before."""
    layar.state.penonton_masuk()
    layar.state.garis_capture_override = 640
    layar.state.sumbu_garis_override = "mendatar"
    layar.state.roi_override = (100, 100, 900, 600)
    layar.state.tampil_roi_override = False
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()

    assert next(c for c in layar.jejak if c[0] == "draw_roi") == (
        "draw_roi", STREAM, 640, "mendatar",
        {"tampil_garis": True, "tampil_roi": False, "roi": (100, 100, 900, 600)},
    )


def test_mode_dev_dari_konsol_sampai_ke_gambar_kotak(layar):
    layar.state.penonton_masuk()
    layar.state.mode_dev_override = True
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()

    assert next(c for c in layar.jejak if c[0] == "draw_boxes")[3] is True


def test_hasil_yolo_basi_jatuh_ke_frame_mentah_tanpa_kotak(layar):
    layar.state.penonton_masuk()
    layar.hasil_yolo(layar.frame())
    layar.state.latest_raw_frame = layar.frame(nama="mentah")
    layar.jam.sekarang += 0.6  # older than half a second: boxes would no longer sit on the fruit

    layar.worker.run_once()

    assert "draw_boxes" not in layar.langkah()
    assert layar.langkah()[0] == "resize" and layar.state.latest_frame == b"jpeg-1"


def test_tanpa_frame_sama_sekali_tidak_ada_yang_ditulis(layar):
    layar.state.penonton_masuk()

    layar.worker.run_once()

    assert layar.jejak == [] and layar.state.latest_frame is None


# ------------------------------------------------------------------ rule 4


def test_frame_baru_ditulis_di_bawah_condition_dan_membangunkan_penonton(layar):
    layar.state.penonton_masuk()
    layar.hasil_yolo(layar.frame())
    diterima: list[bytes | None] = []
    siap = threading.Event()

    def penonton() -> None:
        with layar.state.frame_condition:
            siap.set()
            layar.state.frame_condition.wait(timeout=5)
            diterima.append(layar.state.latest_frame)

    thread = threading.Thread(target=penonton)
    thread.start()
    assert siap.wait(timeout=5)
    with layar.state.frame_condition:
        pass  # the viewer is inside wait() once this lock can be taken

    layar.worker.run_once()
    thread.join(timeout=5)

    assert diterima == [b"jpeg-1"], "the waiting viewer was not woken with the new frame"


def test_tiap_render_menulis_objek_frame_baru(layar):
    """`StreamingService` sends a frame once, comparing by identity."""
    layar.state.penonton_masuk()
    layar.hasil_yolo(layar.frame())

    layar.worker.run_once()
    pertama = layar.state.latest_frame
    layar.worker.run_once()

    assert layar.state.latest_frame == b"jpeg-2" and layar.state.latest_frame is not pertama
