"""Aturan "AI line ini masih memproses?" (batch 2.1), murni tanpa I/O.

Yang paling mahal kalau salah ada dua arah: diam saat buah lewat tanpa disortir
(tujuan fitur ini), dan berteriak saat tidak ada yang rusak (alarm yang sering
salah diajari untuk diabaikan). Tiap keadaan yang BUKAN AI mati punya test
sendiri di sini.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from palmgrade.domain.kesehatan_ai import (
    AMBANG_BAWAAN_DETIK,
    AMBANG_MAKS_DETIK,
    AMBANG_MIN_DETIK,
    KODE_AI_MATI,
    FaktaAi,
    KeadaanAi,
    PenilaianAi,
    ambang_dari_teks,
    ke_kawat,
    kode_http_health,
    nilai_ai,
)

MULAI = 1_000.0

#: Line yang sehat: loop jalan sejak MULAI, gambar mengalir, frame terakhir
#: selesai digrading sedetik lalu.
SEHAT = FaktaAi(
    sekarang=MULAI + 100, ambang_detik=30, kamera_tersambung=True, grading_diblokir=False,
    dimulai_at=MULAI, frame_terakhir_at=MULAI + 100, aliran_frame_sejak=MULAI + 1,
    inferensi_selesai_at=MULAI + 99,
)


def test_line_sehat():
    p = nilai_ai(SEHAT)
    assert (p.keadaan, p.mati, p.error_plc) == (KeadaanAi.SEHAT, False, False)
    assert p.umur_detik == pytest.approx(1.0)


def test_gambar_mengalir_tapi_tidak_ada_yang_selesai_digrading_melewati_ambang_adalah_ai_mati():
    p = nilai_ai(replace(SEHAT, inferensi_selesai_at=MULAI + 60))
    assert (p.keadaan, p.mati, p.error_plc) == (KeadaanAi.AI_MATI, True, True)
    assert p.diam_sejak == MULAI + 60
    assert p.umur_detik == pytest.approx(40.0)


def test_tepat_di_ambang_belum_mati():
    assert nilai_ai(replace(SEHAT, inferensi_selesai_at=MULAI + 70)).keadaan is KeadaanAi.SEHAT


def test_baru_mulai_dan_frame_pertama_belum_selesai_bukan_ai_mati():
    """Model sudah dimuat sebelum loop jalan (lifespan), tapi track pertama bisa
    beberapa detik. Selama masih di dalam ambang sejak loop mulai: MEMULAI."""
    f = replace(SEHAT, sekarang=MULAI + 20, frame_terakhir_at=MULAI + 20,
                aliran_frame_sejak=MULAI + 1, inferensi_selesai_at=0.0)
    p = nilai_ai(f)
    assert (p.keadaan, p.error_plc, p.umur_detik) == (KeadaanAi.MEMULAI, False, None)


def test_tidak_pernah_selesai_satu_frame_pun_sesudah_ambang_adalah_ai_mati():
    """Model yang melempar di frame PERTAMA (engine rusak, CUDA error) tidak
    pernah menulis jam selesai sama sekali. Itu tetap AI mati, bukan MEMULAI."""
    f = replace(SEHAT, sekarang=MULAI + 45, frame_terakhir_at=MULAI + 45,
                aliran_frame_sejak=MULAI + 1, inferensi_selesai_at=0.0)
    p = nilai_ai(f)
    assert p.keadaan is KeadaanAi.AI_MATI
    assert p.diam_sejak == MULAI + 1
    assert p.umur_detik is None


def test_loop_deteksi_belum_jalan_adalah_memulai():
    p = nilai_ai(replace(SEHAT, dimulai_at=0.0, inferensi_selesai_at=0.0))
    assert (p.keadaan, p.error_plc) == (KeadaanAi.MEMULAI, False)


def test_kamera_putus_didahulukan_dan_tetap_menaikkan_error_seperti_dulu():
    """Perilaku coil ERROR sebelum batch 2.1 dipertahankan persis."""
    p = nilai_ai(replace(SEHAT, kamera_tersambung=False, inferensi_selesai_at=MULAI))
    assert (p.keadaan, p.mati, p.error_plc) == (KeadaanAi.KAMERA_PUTUS, False, True)


def test_kamera_putus_saat_loop_belum_jalan_tetap_menaikkan_error():
    p = nilai_ai(replace(SEHAT, kamera_tersambung=False, dimulai_at=0.0))
    assert p.error_plc is True


def test_lisensi_habis_bukan_ai_mati_dan_tidak_menaikkan_error():
    """Grading dihentikan dengan sengaja; bit alive yang mati sudah memberi tahu PLC."""
    p = nilai_ai(replace(SEHAT, grading_diblokir=True, inferensi_selesai_at=MULAI))
    assert (p.keadaan, p.mati, p.error_plc) == (KeadaanAi.LISENSI, False, False)


def test_tidak_ada_gambar_masuk_adalah_sumber_diam_bukan_ai_mati():
    """Video tanpa ulang yang habis, atau kamera yang berhenti mengirim tanpa
    terputus: tidak ada yang bisa digrading, jadi bukan AI yang salah."""
    f = replace(SEHAT, frame_terakhir_at=MULAI + 50, inferensi_selesai_at=MULAI + 50)
    p = nilai_ai(f)
    assert (p.keadaan, p.mati, p.error_plc) == (KeadaanAi.SUMBER_DIAM, False, False)


def test_belum_pernah_ada_gambar_sejak_mulai_melewati_ambang_adalah_sumber_diam():
    f = replace(SEHAT, frame_terakhir_at=0.0, aliran_frame_sejak=0.0, inferensi_selesai_at=0.0)
    assert nilai_ai(f).keadaan is KeadaanAi.SUMBER_DIAM


def test_gambar_mengalir_lagi_sesudah_jeda_memberi_tenggang_baru():
    """Kamera tersambung lagi sesudah lima menit putus: jam selesai terakhir lima
    menit lalu, tapi AI baru boleh dituntut sejak gambar mengalir lagi."""
    f = replace(SEHAT, sekarang=MULAI + 400, frame_terakhir_at=MULAI + 400,
                aliran_frame_sejak=MULAI + 395, inferensi_selesai_at=MULAI + 100)
    p = nilai_ai(f)
    assert (p.keadaan, p.error_plc) == (KeadaanAi.MEMULAI, False)


def test_tenggang_aliran_baru_habis_tanpa_frame_selesai_adalah_ai_mati():
    f = replace(SEHAT, sekarang=MULAI + 440, frame_terakhir_at=MULAI + 440,
                aliran_frame_sejak=MULAI + 395, inferensi_selesai_at=MULAI + 100)
    p = nilai_ai(f)
    assert p.keadaan is KeadaanAi.AI_MATI
    assert p.diam_sejak == MULAI + 395


def test_kawat_membawa_kode_dan_jam_dinding_tanpa_galat_mentah():
    p = PenilaianAi(KeadaanAi.AI_MATI, umur_detik=40.04, diam_sejak=1_060.0)
    kawat = ke_kawat(p, ambang_detik=30, sekarang=1_100.0, jam_dinding=1_790_000_000.0)
    assert kawat == {
        "keadaan": "ai_mati", "mati": True, "kode": KODE_AI_MATI,
        "sejak": 1_790_000_000.0 - 40.0, "umur_detik": 40.0, "ambang_detik": 30,
    }


def test_kawat_line_sehat_tanpa_kode_dan_tanpa_jam():
    kawat = ke_kawat(nilai_ai(SEHAT), ambang_detik=30, sekarang=SEHAT.sekarang, jam_dinding=5.0)
    assert (kawat["keadaan"], kawat["mati"], kawat["kode"], kawat["sejak"]) == ("sehat", False, None, None)


@pytest.mark.parametrize(
    ("ai", "kode"),
    [
        (None, 200),
        ({"keadaan": "sehat", "mati": False}, 200),
        ({"keadaan": "kamera_putus", "mati": False}, 200),
        ({"keadaan": "lisensi", "mati": False}, 200),
        ({"keadaan": "sumber_diam", "mati": False}, 200),
        ({"keadaan": "ai_mati", "mati": True}, 503),
    ],
)
def test_health_503_hanya_untuk_ai_mati(ai, kode):
    assert kode_http_health(ai) == kode


@pytest.mark.parametrize(
    ("teks", "detik"),
    [
        (None, AMBANG_BAWAAN_DETIK),
        ("", AMBANG_BAWAAN_DETIK),
        ("  ", AMBANG_BAWAAN_DETIK),
        ("45", 45),
        (" 45 ", 45),
        ("3", AMBANG_MIN_DETIK),
        ("0", AMBANG_MIN_DETIK),
        ("-5", AMBANG_MIN_DETIK),
        ("99999", AMBANG_MAKS_DETIK),
        ("30s", None),
        ("tiga puluh", None),
    ],
)
def test_ambang_dari_env(teks, detik):
    assert ambang_dari_teks(teks) == detik
