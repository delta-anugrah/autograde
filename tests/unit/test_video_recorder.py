"""Rekam video per line: antrean, drop policy, rem disk.

Yang dijaga di sini satu hal di atas segalanya: **`tulis()` tidak pernah
blocking**. Dipanggil dari thread capture setiap frame, jadi encoder yang
ketinggalan harus mengorbankan videonya (bolong), bukan deteksinya.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from palmgrade.services.video_recorder import (
    DiskMepet,
    RekamSedangJalan,
    RekamTidakJalan,
    VideoRecorder,
)

SETELAN = {"width": 320, "height": 240, "fps": 5}


def _frame(h: int = 240, w: int = 320):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _tunggu(kondisi, batas_s: float = 5.0) -> bool:
    """Tunggu sampai `kondisi()` benar. Encoder thread sendiri, jadi test tidak
    boleh memakai sleep tetap yang jadi flaky di CI yang sibuk."""
    tenggat = time.monotonic() + batas_s
    while time.monotonic() < tenggat:
        if kondisi():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def rekaman(tmp_path):
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    yield r
    if r.status()["merekam"]:
        r.stop()


# ── daur hidup ──────────────────────────────────────────────────────────────


def test_status_awal_tidak_merekam(rekaman):
    assert rekaman.status()["merekam"] is False


def test_mulai_lalu_stop_menghasilkan_berkas(rekaman, tmp_path):
    rekaman.mulai(SETELAN)
    for _ in range(10):
        rekaman.tulis(_frame())
    hasil = rekaman.stop()

    berkas = tmp_path / hasil["berkas"]
    assert berkas.exists()
    assert berkas.stat().st_size > 0


def test_nama_berkas_memuat_line_dan_waktu(rekaman):
    hasil = rekaman.mulai(SETELAN)
    assert hasil["berkas"].startswith("line1_")
    assert hasil["berkas"].endswith(".mp4")


def test_mulai_dua_kali_ditolak(rekaman):
    rekaman.mulai(SETELAN)
    with pytest.raises(RekamSedangJalan):
        rekaman.mulai(SETELAN)


def test_stop_tanpa_mulai_ditolak(rekaman):
    with pytest.raises(RekamTidakJalan):
        rekaman.stop()


def test_mulai_lagi_sesudah_stop_berkas_baru(rekaman):
    a = rekaman.mulai(SETELAN)["berkas"]
    rekaman.stop()
    b = rekaman.mulai(SETELAN)["berkas"]
    rekaman.stop()
    assert a != b


def test_folder_dibuat_kalau_belum_ada(tmp_path):
    tujuan = tmp_path / "belum" / "ada"
    r = VideoRecorder(videos_dir=tujuan, line_code="line1", disk_min_free_gb=0.0)
    r.mulai(SETELAN)
    try:
        assert tujuan.is_dir()
    finally:
        r.stop()


# ── aturan yang tidak boleh dilanggar: tulis() tidak pernah blocking ─────────


def test_tulis_saat_tidak_merekam_diabaikan_diam_diam(rekaman):
    # Thread capture memanggil ini tiap frame; melempar akan menjatuhkan
    # capture worker dan mematikan line demi fitur developer.
    rekaman.tulis(_frame())
    assert rekaman.status()["frame_ditulis"] == 0


def test_tulis_frame_none_diabaikan(rekaman):
    rekaman.mulai(SETELAN)
    rekaman.tulis(None)
    assert rekaman.status()["frame_dibuang"] == 0


def test_tulis_tidak_pernah_blocking_saat_antrean_penuh(tmp_path):
    r = VideoRecorder(
        videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0, ukuran_antrean=2
    )
    # Encoder ditahan supaya antrean pasti penuh.
    r._jeda_uji = threading.Event()
    r.mulai(SETELAN)
    try:
        mulai = time.monotonic()
        for _ in range(200):
            r.tulis(_frame())
        lama = time.monotonic() - mulai
        # 200 frame ke antrean berukuran 2 harus selesai seketika. Ambang
        # longgar supaya tidak flaky di CI yang sibuk; yang salah (menunggu
        # encoder) akan memakan puluhan detik, bukan 1.
        assert lama < 1.0
        assert r.status()["frame_dibuang"] > 0
    finally:
        r._jeda_uji.set()
        r.stop()


def test_frame_dihitung_ditulis_atau_dibuang(rekaman):
    rekaman.mulai(SETELAN)
    for _ in range(5):
        rekaman.tulis(_frame())
    assert _tunggu(lambda: rekaman.status()["frame_ditulis"] == 5)
    s = rekaman.status()
    assert s["frame_ditulis"] + s["frame_dibuang"] == 5


def test_frame_ukuran_beda_diresize_bukan_menjatuhkan_rekaman(rekaman):
    # Frame sensor 2448x2048 ke rekaman 320x240: ini kasus normal, bukan galat.
    rekaman.mulai(SETELAN)
    rekaman.tulis(_frame(h=2048, w=2448))
    assert _tunggu(lambda: rekaman.status()["frame_ditulis"] >= 1)
    assert rekaman.status()["merekam"] is True


# ── rem disk ────────────────────────────────────────────────────────────────


def test_disk_mepet_menolak_mulai(tmp_path):
    r = VideoRecorder(
        videos_dir=tmp_path, line_code="line1", disk_min_free_gb=10_000_000.0
    )
    with pytest.raises(DiskMepet):
        r.mulai(SETELAN)
    assert r.status()["merekam"] is False


def test_ambang_nol_mematikan_rem(tmp_path):
    # 0 = penjaga mati, dipakai test dan PC dev. Kontrol negatif untuk di atas.
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai(SETELAN)
    try:
        assert r.status()["merekam"] is True
    finally:
        r.stop()


def test_disk_mepet_di_tengah_rekaman_menghentikan_sendiri(tmp_path, monkeypatch):
    # Disk penuh = grading berhenti menulis = pabrik berhenti. Fitur developer
    # tidak boleh bisa menyebabkan itu.
    monkeypatch.setattr(
        "palmgrade.services.video_recorder._PERIKSA_DISK_TIAP", 2, raising=False
    )
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai(SETELAN)
    try:
        r._disk_min_free_gb = 10_000_000.0  # disk "menyusut" di tengah rekaman
        for _ in range(40):
            r.tulis(_frame())
            time.sleep(0.01)
        assert _tunggu(lambda: not r.status()["merekam"])
        assert r.status()["alasan_berhenti"] == "disk_mepet"
    finally:
        if r.status()["merekam"]:
            r.stop()


# ── status ──────────────────────────────────────────────────────────────────


def test_status_membawa_setelan_yang_dipakai(rekaman):
    rekaman.mulai(SETELAN)
    assert rekaman.status()["setelan"] == SETELAN


def test_status_membawa_ukuran_berkas(rekaman):
    rekaman.mulai(SETELAN)
    for _ in range(10):
        rekaman.tulis(_frame())
    assert _tunggu(lambda: rekaman.status()["bytes"] > 0)


def test_alasan_berhenti_diminta_saat_stop_manual(rekaman):
    rekaman.mulai(SETELAN)
    assert rekaman.stop()["alasan_berhenti"] == "diminta"


def test_frame_ditulis_naik_walau_berkas_belum_di_flush(rekaman):
    """Ukuran berkas bukan alat ukur yang jujur SELAMA merekam.

    `VideoWriter` menyangga di memori dan baru menulis ke disk sesekali, jadi
    layar yang cuma menampilkan byte akan diam di "0,0 MB" selama belasan detik
    pertama — terbaca persis seperti rekaman yang tidak berjalan. Hitungan
    frame naik seketika, jadi itu yang harus dipakai layar sebagai bukti hidup.
    """
    rekaman.mulai(SETELAN)
    for _ in range(10):
        rekaman.tulis(_frame())
    assert _tunggu(lambda: rekaman.status()["frame_ditulis"] == 10)
    # Sengaja TIDAK menuntut bytes > 0 di sini: itulah intinya.
    assert rekaman.status()["merekam"] is True


def test_ukuran_berkas_terbaca_sesudah_stop(rekaman, tmp_path):
    """Sesudah `release()` byte-nya sudah di disk dan boleh dipercaya."""
    hasil_mulai = rekaman.mulai(SETELAN)
    for _ in range(10):
        rekaman.tulis(_frame())
    assert _tunggu(lambda: rekaman.status()["frame_ditulis"] == 10)
    rekaman.stop()

    assert (tmp_path / hasil_mulai["berkas"]).stat().st_size > 0
    assert rekaman.status()["bytes"] > 0


# ── fps video = fps kamera ──────────────────────────────────────────────────


def test_fps_video_mengikuti_kamera_bukan_setelan(tmp_path):
    """Video ditulis pada laju kamera yang SEBENARNYA, bukan angka setelan.

    Kamera Hikrobot di Lampung mengirim 20 fps. Encoder menulis semua 20, tapi
    menandai berkasnya "5 fps" — hasilnya video 4x lebih lambat dari kejadian
    aslinya: 19 detik rekaman jadi 77 detik tontonan (diukur di pabrik
    2026-09-23). Yang diminta operator justru sebaliknya: apa yang terlihat di
    layar line adalah apa yang terekam.
    """
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai({**SETELAN, "fps": 5}, fps_kamera=20.0)
    try:
        assert r.status()["setelan"]["fps"] == 20
    finally:
        r.stop()


def test_fps_kamera_nol_jatuh_ke_setelan(tmp_path):
    """Sumber yang tidak bisa melapor (berkas video, webcam) tetap memakai
    angka setelan — itu memang gunanya angka itu ada."""
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai({**SETELAN, "fps": 5}, fps_kamera=0.0)
    try:
        assert r.status()["setelan"]["fps"] == 5
    finally:
        r.stop()


def test_fps_kamera_dibulatkan_dan_dibatasi(tmp_path):
    """Kamera melaporkan pecahan (19,97). Dibulatkan supaya header MP4 utuh,
    dan tetap lewat batas `setelan_rekam` supaya nilai ngawur dari kamera yang
    salah setel tidak lolos ke encoder."""
    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    r.mulai({**SETELAN, "fps": 5}, fps_kamera=19.97)
    try:
        assert r.status()["setelan"]["fps"] == 20
    finally:
        r.stop()


def test_durasi_video_sama_dengan_durasi_rekam(tmp_path):
    """Bukti yang sesungguhnya: 2 detik merekam pada 10 fps menghasilkan
    berkas berdurasi ~2 detik, bukan 4 atau 0,5."""
    import cv2

    r = VideoRecorder(videos_dir=tmp_path, line_code="line1", disk_min_free_gb=0.0)
    hasil = r.mulai({**SETELAN, "fps": 5}, fps_kamera=10.0)
    try:
        # 20 frame diserahkan pada laju 10 fps = 2 detik kejadian.
        for _ in range(20):
            r.tulis(_frame())
        assert _tunggu(lambda: r.status()["frame_ditulis"] == 20)
    finally:
        r.stop()

    cap = cv2.VideoCapture(str(tmp_path / hasil["berkas"]))
    try:
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        assert fps == 10, fps
        assert abs(n / fps - 2.0) < 0.3, f"{n} frame @ {fps} fps"
    finally:
        cap.release()
