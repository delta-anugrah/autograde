"""What the operator sees after batch 6.3: boxes, capture line and ROI box in the same place.

The unit tests prove the order of work with fakes. What only real pixels can prove is the
part the operator looks at: with the frame shrunk FIRST and the boxes drawn on the small
frame, every overlay must sit where it sat when the boxes were drawn at full size and the
picture shrunk afterwards.

Needs cv2 + numpy (and torch, which the pipeline module imports), so it lives in e2e and
skips in CI like `test_garis_pemicu_render.py`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
pytest.importorskip("torch")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.core.constants import COLOR_FAIL, COLOR_PASS, COLOR_ROI, COLOR_TRIGGER  # noqa: E402
from palmgrade.domain.skala_tampilan import skala_ke  # noqa: E402
from palmgrade.pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline  # noqa: E402
from palmgrade.workers.display_worker import DisplayWorker  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402

SENSOR_W, SENSOR_H = 2448, 2048
STREAM_W, STREAM_H = 1280, 720
NAMA = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}
MATANG = (500, 400, 1300, 1200)       # sensor pixels
MENTAH = (1500, 900, 2300, 1900)
TOLERANSI_PX = 2


class _Registry:
    device = "cpu"
    model = None


class _Tensor(list):
    def tolist(self):
        return list(self)


class _Scalar:
    def __init__(self, v):
        self._v = v

    def item(self):
        return self._v


class _Box:
    def __init__(self, xyxy, cls_id, conf=0.9):
        self.xyxy = [_Tensor(xyxy)]
        self.cls = [_Scalar(cls_id)]
        self.conf = [_Scalar(conf)]
        self.id = None


class _Results:
    def __init__(self, boxes):
        self.boxes = boxes
        self.names = NAMA


def _settings(**setelan) -> Settings:
    # The style the factory `.env` uses for the 2448x2048 frame.
    return replace(
        Settings(), stream_width=STREAM_W, stream_height=STREAM_H,
        border_thickness=8, font_scale=2.5, font_thickness=5,
        roi_x1=100, roi_y1=80, roi_x2=1180, roi_y2=640, garis_capture=300, sumbu_garis="tegak",
        mode_dev=False, **setelan,
    )


def _hasil() -> _Results:
    return _Results([_Box(MATANG, 1), _Box(MENTAH, 3)])


def _sensor():
    """A dark, slightly noisy conveyor: no pixel is pure green, red or blue by accident."""
    return np.random.default_rng(3).integers(10, 60, (SENSOR_H, SENSOR_W, 3), dtype=np.uint8)


def _lama(pipeline: RealtimeInspectionPipeline, frame, results):
    """The render before 6.3: copy, draw the boxes at full size, shrink."""
    penuh = pipeline.draw_boxes(frame.copy(), results)
    return cv2.resize(penuh, (STREAM_W, STREAM_H), interpolation=cv2.INTER_NEAREST)


def _baru(pipeline: RealtimeInspectionPipeline, frame, results):
    """The render since 6.3: shrink, draw the boxes on the small frame."""
    kecil = cv2.resize(frame, (STREAM_W, STREAM_H), interpolation=cv2.INTER_NEAREST)
    return pipeline.draw_boxes(kecil, results, skala=skala_ke(SENSOR_W, SENSOR_H, STREAM_W, STREAM_H))


def _rentang(garis, warna) -> list[tuple[int, int]]:
    """Runs of `warna` along one row or column: (first, last) of each run."""
    kena = np.flatnonzero((garis == np.array(warna, dtype=np.uint8)).all(axis=1))
    if kena.size == 0:
        return []
    putus = np.flatnonzero(np.diff(kena) > 1)
    awal = np.concatenate(([kena[0]], kena[putus + 1]))
    akhir = np.concatenate((kena[putus], [kena[-1]]))
    return list(zip(awal.tolist(), akhir.tolist(), strict=True))


def _tepi(gambar, kotak_sensor, warna) -> dict[str, tuple[int, int]]:
    """The four border runs of one box, read along the row and column through its middle."""
    sx, sy = STREAM_W / SENSOR_W, STREAM_H / SENSOR_H
    x1, y1, x2, y2 = kotak_sensor
    baris = round((y1 + y2) / 2 * sy)
    kolom = round((x1 + x2) / 2 * sx)
    mendatar = _rentang(gambar[baris, :], warna)
    tegak = _rentang(gambar[:, kolom], warna)
    assert len(mendatar) == 2 and len(tegak) == 2, (mendatar, tegak)
    return {"kiri": mendatar[0], "kanan": mendatar[1], "atas": tegak[0], "bawah": tegak[1]}


@pytest.mark.parametrize(("kotak", "warna"), [(MATANG, COLOR_PASS), (MENTAH, COLOR_FAIL)], ids=["ripe", "unripe"])
def test_kotak_janjang_mendarat_di_tempat_yang_sama(kotak, warna):
    pipeline = RealtimeInspectionPipeline(_Registry(), _settings())
    frame, results = _sensor(), _hasil()

    lama = _tepi(_lama(pipeline, frame, results), kotak, warna)
    baru = _tepi(_baru(pipeline, frame, results), kotak, warna)

    for sisi in ("kiri", "kanan", "atas", "bawah"):
        tengah_lama = sum(lama[sisi]) / 2
        tengah_baru = sum(baru[sisi]) / 2
        assert abs(tengah_baru - tengah_lama) <= TOLERANSI_PX, (sisi, lama[sisi], baru[sisi])
        tebal = baru[sisi][1] - baru[sisi][0] + 1
        assert 2 <= tebal <= 5, f"border {sisi} is {tebal} px on the stream"


def test_tanpa_skala_gambar_bukti_tidak_berubah_satu_piksel_pun():
    """The saved evidence photo is drawn at full size through the same function."""
    pipeline = RealtimeInspectionPipeline(_Registry(), _settings())
    frame, results = _sensor(), _hasil()

    bawaan = pipeline.draw_boxes(frame.copy(), results)
    eksplisit = pipeline.draw_boxes(frame.copy(), results, skala=(1.0, 1.0))

    assert np.array_equal(bawaan, eksplisit)
    assert _tepi(cv2.resize(bawaan, (STREAM_W, STREAM_H), interpolation=cv2.INTER_NEAREST), MATANG, COLOR_PASS)


def test_label_tetap_terbaca_di_atas_kotaknya():
    """The label is drawn in the box colour just above the box, about as tall as before."""
    pipeline = RealtimeInspectionPipeline(_Registry(), _settings())
    baru = _baru(pipeline, _sensor(), _hasil())
    sx, sy = STREAM_W / SENSOR_W, STREAM_H / SENSOR_H
    x1, y1 = round(MATANG[0] * sx), round(MATANG[1] * sy)

    di_atas = baru[max(0, y1 - 40):y1 - 3, x1:x1 + 120]
    baris_hijau = np.flatnonzero((di_atas == np.array(COLOR_PASS, dtype=np.uint8)).all(axis=2).any(axis=1))

    assert baris_hijau.size >= 12, "the label above the ripe box is missing or too small to read"
    assert baris_hijau.size <= 36, "the label was drawn at sensor size on the stream frame"


def test_satu_render_penuh_garis_capture_dan_roi_di_tempat_yang_disetel():
    """The whole worker with real cv2: one viewer, one YOLO frame, one JPEG of stream size."""
    settings = _settings()
    state = RuntimeState()
    frame = _sensor()
    asli = frame.copy()
    state.last_yolo_frame = frame
    state.last_yolo_results = _hasil()
    jam = 1_000.0
    state.last_yolo_frame_at = jam
    state.penonton_masuk()
    worker = DisplayWorker(
        state=state, pipeline=RealtimeInspectionPipeline(_Registry(), settings), settings=settings,
        target_fps=12, jam=lambda: jam, tidur=lambda _detik: None,
    )

    worker.run_once()

    gambar = cv2.imdecode(np.frombuffer(state.latest_frame, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert gambar.shape == (STREAM_H, STREAM_W, 3)
    assert np.array_equal(frame, asli), "the sensor frame was drawn on"

    def dekat(piksel, warna) -> bool:  # JPEG is lossy: close to the colour, not equal
        return all(abs(int(p) - int(w)) < 70 for p, w in zip(piksel, warna, strict=True))

    # Capture line: a vertical blue line at x = 300 of the stream, top to bottom.
    assert dekat(gambar[360, 300], COLOR_TRIGGER) and dekat(gambar[700, 300], COLOR_TRIGGER)
    assert not dekat(gambar[360, 340], COLOR_TRIGGER)
    # ROI box: its left side at x = 100, its top side at y = 80.
    assert dekat(gambar[500, 100], COLOR_ROI) and dekat(gambar[80, 800], COLOR_ROI)
    # A bunch box, left border, at the place the old render had it.
    assert dekat(gambar[round(800 * STREAM_H / SENSOR_H), round(500 * STREAM_W / SENSOR_W)], COLOR_PASS)


def test_tanpa_penonton_render_sungguhan_tidak_menghasilkan_gambar():
    settings = _settings()
    state = RuntimeState()
    state.last_yolo_frame = _sensor()
    state.last_yolo_results = _hasil()
    state.last_yolo_frame_at = 1_000.0
    worker = DisplayWorker(
        state=state, pipeline=RealtimeInspectionPipeline(_Registry(), settings), settings=settings,
        target_fps=12, jam=lambda: 1_000.0, tidur=lambda _detik: None,
    )

    worker.run_once()

    assert state.latest_frame is None
