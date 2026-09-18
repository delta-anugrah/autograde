"""Yang benar-benar tergambar di layar operator: garis biru ada, angka hilang.

Unit test membuktikan letak garisnya dihitung benar. Yang tidak bisa dibuktikan
di sana justru yang dilihat operator: piksel birunya sungguh tertulis ke frame,
dan label janjang tidak lagi membawa persen.

Butuh cv2 + numpy, jadi tinggal di e2e.
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.core.constants import COLOR_TRIGGER  # noqa: E402
from palmgrade.pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline  # noqa: E402

STREAM_W, STREAM_H = 1280, 720


class _Registry:
    device = "cpu"
    model = None


class _Box:
    """Satu kotak hasil YOLO, sebanyak yang dibaca `draw_boxes`."""

    def __init__(self, xyxy, cls_id, conf):
        self.xyxy = [_Tensor(xyxy)]
        self.cls = [_Scalar(cls_id)]
        self.conf = [_Scalar(conf)]
        self.id = None


class _Tensor(list):
    def tolist(self):
        return list(self)


class _Scalar:
    def __init__(self, v):
        self._v = v

    def item(self):
        return self._v


class _Results:
    def __init__(self, boxes, names):
        self.boxes = boxes
        self.names = names


def _pipeline(monkeypatch, roi=(0, 0, 0, 0)) -> RealtimeInspectionPipeline:
    x1, y1, x2, y2 = roi
    for key, val in (("ROI_X1", x1), ("ROI_Y1", y1), ("ROI_X2", x2), ("ROI_Y2", y2)):
        monkeypatch.setenv(key, str(val))
    monkeypatch.setenv("STREAM_WIDTH", str(STREAM_W))
    monkeypatch.setenv("STREAM_HEIGHT", str(STREAM_H))
    return RealtimeInspectionPipeline(_Registry(), Settings())


def _frame():
    return np.zeros((STREAM_H, STREAM_W, 3), dtype=np.uint8)


# ----------------------------------------------------------- garis pemicu


def test_the_trigger_line_is_actually_drawn_in_blue(monkeypatch):
    """Operator meminta biru supaya bisa dibedakan dari hijau ROI dan bbox."""
    p = _pipeline(monkeypatch, roi=(100, 100, 900, 600))
    out = p.draw_roi(_frame())

    kolom = out[100:600, 900]
    cocok = [tuple(int(v) for v in px) for px in kolom if tuple(px) == COLOR_TRIGGER]
    assert len(cocok) > 400, "garis biru tidak tergambar di batas kanan ROI"


def test_the_line_marks_the_right_hand_edge_not_the_left(monkeypatch):
    """Buah bergerak kanan → kiri, jadi sisi kanan ROI yang dilewati lebih dulu.

    Menandai sisi kiri akan membuat operator menggeser ROI ke arah yang salah
    saat menyetel kapan foto diambil.
    """
    p = _pipeline(monkeypatch, roi=(100, 100, 900, 600))
    out = p.draw_roi(_frame())

    def biru_di(x):
        return sum(1 for px in out[100:600, x] if tuple(px) == COLOR_TRIGGER)

    assert biru_di(900) > 400, "sisi kanan harus bergaris tebal"
    # Label CAPTURE juga biru, jadi yang dibandingkan tingginya: garis penuh
    # setinggi ROI, teks cuma setinggi beberapa puluh piksel.
    assert biru_di(100) < 50, "sisi kiri bukan titik pemicu"


def test_a_full_screen_roi_still_shows_the_line(monkeypatch):
    """`0,0,0,0` itu keadaan bawaan DAN keadaan PC Lampung saat ini.

    Justru di sinilah garisnya paling perlu: ROI penuh layar berarti janjang
    difoto begitu terdeteksi di mana pun. Garis yang digambar tepat di kolom
    terakhir terpotong separuh oleh cv2 dan berhimpit dengan bingkai video di
    browser, jadi dia ditarik masuk dari tepi.
    """
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame())

    # Kolom garisnya harus utuh dari atas ke bawah, bukan sekadar "ada biru"
    # (label CAPTURE juga biru, dan itu bukan bukti garisnya kelihatan).
    kolom = [
        x for x in range(STREAM_W)
        if sum(1 for px in out[:, x] if tuple(px) == COLOR_TRIGGER) > STREAM_H * 0.9
    ]
    assert kolom, "tidak ada satu pun kolom penuh biru — garis tenggelam di tepi"
    assert max(kolom) < STREAM_W - 1, "garis masih menempel kolom terakhir"
    assert max(kolom) > STREAM_W - 20, "garis terlalu jauh masuk, tidak lagi menandai tepi"


def test_the_line_is_labelled_so_it_needs_no_explaining(monkeypatch):
    """Garis berwarna tanpa keterangan cuma memindahkan pertanyaannya.

    Diuji lewat piksel biru DI LUAR kolom garis: itu hanya bisa datang dari
    teksnya.
    """
    p = _pipeline(monkeypatch, roi=(100, 100, 900, 600))
    out = p.draw_roi(_frame())

    tanpa_garis = out.copy()
    tanpa_garis[:, 895:905] = 0
    teks = int(((tanpa_garis == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum())
    assert teks > 50, "garis tidak punya label"


def test_an_inverted_roi_draws_nothing_rather_than_a_wrong_line(monkeypatch):
    """X2 < X1 itu salah ketik; garis di tempat salah lebih buruk dari tanpa garis."""
    p = _pipeline(monkeypatch, roi=(900, 100, 200, 600))
    out = p.draw_roi(_frame())

    assert int(((out == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum()) == 0


# ------------------------------------------------------------ label janjang


def _label_pixels(monkeypatch, conf):
    """Gambar satu janjang lalu kembalikan jumlah piksel yang bukan hitam.

    Teksnya tidak bisa dibaca balik dari gambar, tapi panjangnya bisa diukur:
    "Ripe 54%" memakai jauh lebih banyak piksel daripada "Ripe".
    """
    p = _pipeline(monkeypatch)
    results = _Results([_Box([400, 300, 600, 500], 0, conf)], {0: "Ripe"})
    out = p.draw_boxes(_frame(), results)
    # Baris teks di atas kotak; kotaknya sendiri mulai di y=300.
    pita = out[240:300, :]
    return int((pita.any(axis=2)).sum())


def test_the_label_no_longer_carries_a_confidence_number(monkeypatch):
    """Diminta operator 2026-09-18.

    Angkanya keyakinan MODEL, bukan mutu buah, dan dari beberapa meter "54%"
    terbaca seperti "54% matang". Ambangnya sudah diputuskan `CONF_THRESHOLD`:
    apa pun yang tergambar sudah lolos ambang itu.

    Diuji lewat lebar teks, karena nilai `conf` yang berbeda tidak boleh lagi
    mengubah satu piksel pun kalau angkanya memang sudah tidak dicetak.
    """
    assert _label_pixels(monkeypatch, 0.54) == _label_pixels(monkeypatch, 0.99), (
        "lebar label berubah mengikuti confidence — angkanya masih dicetak"
    )


def test_the_class_name_is_still_shown(monkeypatch):
    """Yang dibuang angkanya, bukan labelnya: operator tetap harus tahu kelasnya."""
    assert _label_pixels(monkeypatch, 0.54) > 0, "label janjang hilang seluruhnya"


def test_confidence_is_still_recorded_even_though_it_is_not_drawn():
    """Nilainya tetap masuk sidecar dan payload API — yang dibuang tampilannya.

    Kalau ini ikut hilang, rekap dan penilaian model ke depan kehilangan datanya
    tanpa ada yang sadar sampai berbulan-bulan kemudian.
    """
    from palmgrade.domain.vision_event import build_event_payload

    payload = build_event_payload(
        machine_id="m", file_ts="2026-09-18_095207_000000",
        timestamp="2026-09-18T02:52:07+00:00", ripeness_status="acc",
        ripeness_confidence=0.54, capture_type="auto",
        image_path="captures/results/x.webp", truck_id=None, assignment_id=None,
    )
    assert payload["ripeness_confidence"] == 0.54
