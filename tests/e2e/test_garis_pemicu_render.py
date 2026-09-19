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
# `realtime_inspection_pipeline` imports ultralytics, which imports torch. CI installs
# neither on purpose -- the rule is "no torch, no cv2, no SDK in CI", and cv2 was only
# added because the PLC lane tests need it. Guarding here keeps this one file skipping
# cleanly instead of failing collection for the whole e2e run.
pytest.importorskip("torch")

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


# ----------------------------------------------------------- garis capture


def test_the_capture_line_is_drawn_where_it_was_set(monkeypatch):
    """Garisnya berdiri sendiri di `garis_capture`, bukan menempel sisi ROI.

    Itu perubahan 2026-09-18: operator minta satu garis lurus yang bisa digeser,
    dan zonanya bukan lagi kotak. Kalau garis ini ikut sisi ROI, menggesernya
    berarti ikut mengubah wilayah yang dihitung — dua hal berbeda yang tidak
    boleh terikat satu angka.
    """
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=640)

    def biru_di(x):
        return sum(1 for px in out[:, x] if tuple(px) == COLOR_TRIGGER)

    assert biru_di(640) > STREAM_H * 0.9, "garis tidak ada di posisi yang disetel"
    assert biru_di(200) == 0, "ada garis di tempat yang tidak disetel"


def test_the_line_spans_the_whole_frame_height(monkeypatch):
    """Garis lurus dari atas ke bawah, bukan sepanjang sisi ROI saja.

    Janjang bisa lewat di ketinggian mana pun di conveyor; garis yang berhenti
    di batas ROI membuat operator mengira janjang di atas/bawahnya tidak
    terhitung, padahal terhitung.
    """
    p = _pipeline(monkeypatch, roi=(100, 200, 900, 400))
    out = p.draw_roi(_frame(), garis_capture=640)

    assert tuple(out[5, 640]) == COLOR_TRIGGER, "garis tidak sampai atas frame"
    assert tuple(out[STREAM_H - 5, 640]) == COLOR_TRIGGER, "garis tidak sampai bawah frame"


def test_no_line_is_drawn_when_it_is_switched_off(monkeypatch):
    """`0` = tanpa garis, dan itu perilaku sebelum fitur ini ada.

    Menggambar garis di x=0 akan terbaca seperti pemicu di tepi kiri layar —
    kebalikan dari yang sebenarnya terjadi (semua janjang lolos).
    """
    p = _pipeline(monkeypatch, roi=(100, 100, 900, 600))
    out = p.draw_roi(_frame(), garis_capture=0)

    assert int(((out == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum()) == 0


def test_a_line_at_the_very_edge_is_pulled_into_view(monkeypatch):
    """Garis di kolom terakhir terpotong cv2 dan berhimpit bingkai video browser."""
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=STREAM_W)

    kolom = [
        x for x in range(STREAM_W)
        if sum(1 for px in out[:, x] if tuple(px) == COLOR_TRIGGER) > STREAM_H * 0.9
    ]
    assert kolom, "garis tenggelam di tepi frame"
    assert max(kolom) < STREAM_W - 1, "garis masih menempel kolom terakhir"


def test_the_roi_box_is_still_drawn_next_to_the_line(monkeypatch):
    """ROI tidak dihapus: dia tetap menyaring WILAYAH, garis menentukan WAKTU."""
    p = _pipeline(monkeypatch, roi=(100, 100, 900, 600))
    out = p.draw_roi(_frame(), garis_capture=640)

    from palmgrade.core.constants import COLOR_ROI

    hijau = int(((out == np.array(COLOR_ROI, dtype=np.uint8)).all(axis=2)).sum())
    assert hijau > 1000, "kotak ROI hilang"


def test_the_line_is_labelled_so_it_needs_no_explaining(monkeypatch):
    """Garis berwarna tanpa keterangan cuma memindahkan pertanyaannya.

    Diuji lewat piksel biru DI LUAR kolom garis: itu hanya bisa datang dari
    teksnya.
    """
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=640)

    tanpa_garis = out.copy()
    tanpa_garis[:, 635:645] = 0
    teks = int(((tanpa_garis == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum())
    assert teks > 50, "garis tidak punya label"


def test_the_label_stays_on_screen_when_the_line_hugs_the_left_edge(monkeypatch):
    """Teks di kiri garis akan keluar layar kalau garisnya dekat tepi kiri."""
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=20)

    kanan = out[:, 25:]
    assert int(((kanan == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum()) > 50, (
        "label pindah ke kanan garis saat garisnya di tepi kiri"
    )


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


# ------------------------------------------------ sumbu mendatar (conveyor menurun)


def test_a_horizontal_conveyor_gets_a_horizontal_line(monkeypatch):
    """Conveyor menurun: garisnya mendatar, dan angkanya px dari ATAS.

    Menggambar garis tegak di sini akan menyuruh operator mengukur dari sisi
    yang salah, dan angkanya tetap terlihat masuk akal sampai ada yang mengecek.
    """
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=360, sumbu="mendatar")

    baris = sum(1 for px in out[360, :] if tuple(px) == COLOR_TRIGGER)
    assert baris > STREAM_W * 0.9, "garis mendatar tidak tergambar"
    # Dan tidak ada kolom penuh biru: itu akan berarti garisnya masih tegak.
    kolom_penuh = [
        x for x in range(STREAM_W)
        if sum(1 for px in out[:, x] if tuple(px) == COLOR_TRIGGER) > STREAM_H * 0.9
    ]
    assert kolom_penuh == [], "garis masih digambar tegak di sumbu mendatar"


def test_the_horizontal_line_keeps_its_label_on_screen(monkeypatch):
    """Label garis mendatar ditulis di atas garis, dan pindah ke bawah kalau
    garisnya menempel tepi atas — teks yang keluar layar sama saja hilang."""
    p = _pipeline(monkeypatch, roi=(0, 0, 0, 0))
    out = p.draw_roi(_frame(), garis_capture=8, sumbu="mendatar")

    bawah = out[12:, :]
    assert int(((bawah == np.array(COLOR_TRIGGER, dtype=np.uint8)).all(axis=2)).sum()) > 50, (
        "label tidak pindah ke bawah garis"
    )
