"""Kotak ROI di layar harus sama dengan zona yang menghitung.

Dulu satu set angka dipakai di DUA ruang koordinat yang berbeda:

- `FrameProcessingWorker._roi_box()` menyaring di frame MENTAH dari kamera
  (Hikrobot 2448x2048), karena `frame_queue` tidak pernah di-resize.
- `RealtimeInspectionPipeline.draw_roi()` menggambar SESUDAH `DisplayWorker`
  me-resize ke ruang stream (`STREAM_WIDTH` x `STREAM_HEIGHT`, bawaan 1280x720).

Dengan `ROI=100,100,1180,620` kotak yang tampil hampir memenuhi layar 1280x720,
padahal yang benar-benar menyaring cuma ~11% pojok kiri-atas frame 2448x2048.
Operator mengkalibrasi lewat apa yang dia lihat, jadi janjang di luar pojok itu
dilacak, digambar, lalu dibuang tanpa pesan apa pun — terbaca sebagai "deteksi
kadang tidak masuk", bukan sebagai salah kalibrasi.

Satu ruang sekarang: ROI ditulis dalam ruang STREAM (sama dengan yang dilihat
operator), lalu diskalakan ke ukuran frame mentah saat menyaring.

`draw_roi()` sengaja tidak diuji di sini: dia menggambar lewat cv2, dan CI ini
sengaja tidak memasang cv2/numpy/torch. Yang diuji aritmetikanya — itu bagian
yang dulu salah, dan itu bagian yang tidak butuh gambar sungguhan.
"""
from __future__ import annotations

import pytest

from palmgrade.core.config import Settings

# Ruang stream yang dilihat operator, dan ruang sensor tempat deteksi berjalan.
STREAM_W, STREAM_H = 1280, 720
SENSOR_W, SENSOR_H = 2448, 2048

# ROI seperti yang dulu ada di `.env` pabrik — digambar di 1280x720.
ROI = (100, 100, 1180, 620)


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    x1, y1, x2, y2 = ROI
    for key, val in (
        ("ROI_X1", x1), ("ROI_Y1", y1), ("ROI_X2", x2), ("ROI_Y2", y2),
        ("STREAM_WIDTH", STREAM_W), ("STREAM_HEIGHT", STREAM_H),
    ):
        monkeypatch.setenv(key, str(val))
    return Settings()


def test_zona_penyaring_menutup_bagian_frame_yang_sama_dengan_kotak_di_layar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Porsi frame yang disaring == porsi layar yang dikotaki.

    Ini inti bugnya. Tanpa penskalaan, zona penyaring cuma ~11% frame sensor
    sementara kotak di layar ~92% — operator mengkalibrasi yang satu dan
    mendapat yang lain.
    """
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    settings = _settings(monkeypatch)
    roi = FrameProcessingWorker._roi_box_for(settings, SENSOR_W, SENSOR_H)

    x1, y1, x2, y2 = roi
    porsi_saring = ((x2 - x1) * (y2 - y1)) / (SENSOR_W * SENSOR_H)

    rx1, ry1, rx2, ry2 = ROI
    porsi_layar = ((rx2 - rx1) * (ry2 - ry1)) / (STREAM_W * STREAM_H)

    assert porsi_saring == pytest.approx(porsi_layar, abs=0.01), (
        f"zona penyaring {porsi_saring:.1%} frame, tapi kotak di layar "
        f"{porsi_layar:.1%} — operator mengkalibrasi yang salah"
    )


def test_titik_tengah_frame_ikut_terhitung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kotak ROI mencakup tengah layar, jadi tengah frame wajib ikut terhitung.

    Dengan bug lama titik ini jatuh DI LUAR zona (ROI berhenti di x=1180 dari
    2448), padahal di layar jelas berada di dalam kotak.
    """
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    settings = _settings(monkeypatch)
    roi = FrameProcessingWorker._roi_box_for(settings, SENSOR_W, SENSOR_H)

    assert FrameProcessingWorker._is_in_roi_box(SENSOR_W // 2, SENSOR_H // 2, roi)


def test_roi_nol_tetap_berarti_full_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """`0,0,0,0` = seluruh frame. Penskalaan tidak boleh merusak jalan keluar ini."""
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    for key in ("ROI_X1", "ROI_Y1", "ROI_X2", "ROI_Y2"):
        monkeypatch.setenv(key, "0")
    settings = Settings()

    assert FrameProcessingWorker._roi_box_for(settings, SENSOR_W, SENSOR_H) == (
        0, 0, SENSOR_W, SENSOR_H,
    )


def test_frame_seukuran_stream_tidak_diskalakan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webcam yang sudah 1280x720: ROI dipakai apa adanya, faktor skala = 1."""
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    settings = _settings(monkeypatch)
    assert FrameProcessingWorker._roi_box_for(settings, STREAM_W, STREAM_H) == ROI


def test_janjang_di_pinggir_kanan_ikut_terhitung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regresi yang terlihat di layar: buah di kanan frame dulu dibuang diam-diam.

    ROI lama berhenti di x=1180 dari 2448, jadi apa pun di paruh kanan frame
    sensor ada di luar zona — padahal di layar jelas di dalam kotak.
    """
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    settings = _settings(monkeypatch)
    roi = FrameProcessingWorker._roi_box_for(settings, SENSOR_W, SENSOR_H)

    # x=1800 pada frame sensor = x=941 di ruang stream — di dalam kotak (100..1180).
    assert FrameProcessingWorker._is_in_roi_box(1800, 1000, roi)


def test_roi_tidak_pernah_melampaui_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hasil penskalaan wajib tetap di dalam frame, bukan menunjuk piksel yang tidak ada."""
    from palmgrade.workers.frame_processing_worker import FrameProcessingWorker

    settings = _settings(monkeypatch)
    x1, y1, x2, y2 = FrameProcessingWorker._roi_box_for(settings, SENSOR_W, SENSOR_H)

    assert 0 <= x1 < x2 <= SENSOR_W
    assert 0 <= y1 < y2 <= SENSOR_H
