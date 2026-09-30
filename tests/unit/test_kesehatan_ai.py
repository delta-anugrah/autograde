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
    KODE_FRAME_BERHENTI,
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


def test_kamera_tersambung_tanpa_gambar_melewati_ambang_adalah_frame_berhenti():
    """Batch 3.6: Hikrobot yang berhenti mengirim tanpa terputus. Buah lewat
    tanpa disortir persis seperti AI mati: coil ERROR naik, `/health` 503."""
    f = replace(SEHAT, frame_terakhir_at=MULAI + 50, inferensi_selesai_at=MULAI + 50)
    p = nilai_ai(f)
    assert (p.keadaan, p.mati, p.gagal, p.error_plc) == (KeadaanAi.FRAME_BERHENTI, False, True, True)
    assert p.diam_sejak == MULAI + 50


def test_frame_berhenti_tepat_di_ambang_belum():
    f = replace(SEHAT, frame_terakhir_at=MULAI + 70, inferensi_selesai_at=MULAI + 70)
    assert nilai_ai(f).keadaan is KeadaanAi.SEHAT


def test_belum_pernah_ada_gambar_sejak_mulai_melewati_ambang_adalah_frame_berhenti():
    f = replace(SEHAT, frame_terakhir_at=0.0, aliran_frame_sejak=0.0, inferensi_selesai_at=0.0)
    p = nilai_ai(f)
    assert p.keadaan is KeadaanAi.FRAME_BERHENTI
    assert p.diam_sejak == MULAI


def test_sumber_yang_selesai_bukan_kerusakan():
    """Video tanpa ulang yang habis memutus dirinya sendiri: sumber uji yang
    berakhir tidak boleh terbaca sebagai line rusak di lapangan."""
    f = replace(SEHAT, kamera_tersambung=False, sumber_selesai=True,
                frame_terakhir_at=MULAI + 10, inferensi_selesai_at=MULAI + 10)
    p = nilai_ai(f)
    assert (p.keadaan, p.gagal, p.error_plc) == (KeadaanAi.SUMBER_SELESAI, False, False)


def test_kamera_bolak_balik_sambung_tanpa_gambar_tetap_frame_berhenti():
    """Lima grab gagal membuat worker memutus lalu menyambung lagi. Tepat di
    sela itu `connected` False, tapi sambung ulang terakhirnya BERHASIL: tetap
    frame berhenti, bukan berkedip ke kamera putus (200) tiap beberapa detik."""
    f = replace(SEHAT, kamera_tersambung=False, sambung_terakhir_ok=True, sambung_ok_sejak_frame=True,
                frame_terakhir_at=MULAI + 50, inferensi_selesai_at=MULAI + 50)
    assert nilai_ai(f).keadaan is KeadaanAi.FRAME_BERHENTI


def test_sambung_ulang_terakhir_gagal_tidak_membalik_frame_berhenti():
    """Hikrobot diam yang sambung ulangnya berselang berhasil dan gagal: satu
    sambung yang berhasil sejak gambar terakhir sudah membuktikan kameranya ada.
    Sambung berikutnya yang gagal tidak boleh membalik penilaian ke kamera putus,
    kalau tidak alarmnya berkedip tiap siklus sambung ulang."""
    f = replace(SEHAT, kamera_tersambung=False, sambung_terakhir_ok=False, sambung_ok_sejak_frame=True,
                frame_terakhir_at=MULAI + 50, inferensi_selesai_at=MULAI + 50)
    assert nilai_ai(f).keadaan is KeadaanAi.FRAME_BERHENTI


def test_connected_sebelum_hasil_sambung_dicatat_masih_kamera_putus():
    """Akhir putus panjang: `connect()` sudah menyetel `connected`, tapi hasil
    sambungnya belum dicatat (masih gagal dari percobaan sebelumnya). Satu tick
    di sela itu tidak boleh terbaca frame berhenti: itu ERROR palsu yang sampai ke
    Discord tepat saat kameranya kembali."""
    f = replace(SEHAT, sekarang=MULAI + 400, kamera_tersambung=True, sambung_terakhir_ok=False,
                frame_terakhir_at=MULAI + 50, inferensi_selesai_at=MULAI + 50)
    assert nilai_ai(f).keadaan is KeadaanAi.KAMERA_PUTUS


def test_sambung_ulang_yang_gagal_adalah_kamera_putus_walau_gambar_basi():
    """Kabel dicabut: sambung ulang gagal. Itu kamera putus (200, coil ERROR
    seperti dulu), bukan frame berhenti."""
    f = replace(SEHAT, kamera_tersambung=False, sambung_terakhir_ok=False,
                frame_terakhir_at=MULAI + 10, inferensi_selesai_at=MULAI + 10)
    p = nilai_ai(f)
    assert (p.keadaan, p.gagal, p.error_plc) == (KeadaanAi.KAMERA_PUTUS, False, True)


def test_kamera_putus_sebelum_sambung_ulang_pertama_tetap_kamera_putus():
    f = replace(SEHAT, kamera_tersambung=False, sambung_terakhir_ok=None,
                frame_terakhir_at=MULAI + 10, inferensi_selesai_at=MULAI + 10)
    assert nilai_ai(f).keadaan is KeadaanAi.KAMERA_PUTUS


def test_kamera_pulih_dari_putus_sungguhan_diberi_tenggang_gambar():
    """Kamera kembali sesudah lima menit putus: gambar terakhir lima menit lalu,
    tapi kamera baru boleh dituntut mengirim sejak pulih. Selama tenggang:
    MEMULAI, bukan frame berhenti dan bukan AI mati."""
    f = replace(SEHAT, sekarang=MULAI + 400, sambung_terakhir_ok=True, kamera_pulih_at=MULAI + 390,
                frame_terakhir_at=MULAI + 100, aliran_frame_sejak=MULAI + 1,
                inferensi_selesai_at=MULAI + 100)
    p = nilai_ai(f)
    assert (p.keadaan, p.gagal, p.error_plc) == (KeadaanAi.MEMULAI, False, False)


def test_kamera_pulih_tapi_tidak_pernah_mengirim_sesudah_tenggang_adalah_frame_berhenti():
    f = replace(SEHAT, sekarang=MULAI + 421, sambung_terakhir_ok=True, kamera_pulih_at=MULAI + 390,
                frame_terakhir_at=MULAI + 100, aliran_frame_sejak=MULAI + 1,
                inferensi_selesai_at=MULAI + 100)
    p = nilai_ai(f)
    assert p.keadaan is KeadaanAi.FRAME_BERHENTI
    assert p.diam_sejak == MULAI + 390


def test_lisensi_didahulukan_atas_frame_berhenti():
    f = replace(SEHAT, grading_diblokir=True, frame_terakhir_at=MULAI + 10,
                inferensi_selesai_at=MULAI + 10)
    assert nilai_ai(f).keadaan is KeadaanAi.LISENSI


def test_lisensi_dan_kamera_bolak_balik_tetap_kamera_putus_seperti_dulu():
    f = replace(SEHAT, grading_diblokir=True, kamera_tersambung=False, sambung_terakhir_ok=True,
                sambung_ok_sejak_frame=True, frame_terakhir_at=MULAI + 10, inferensi_selesai_at=MULAI + 10)
    assert nilai_ai(f).error_plc is True


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


def test_kawat_frame_berhenti_membawa_kodenya_sendiri_dan_mati_tetap_false():
    """`mati` tetap AI saja: konsol versi lama menulis "AI berhenti memproses"
    untuk `mati:true`, kalimat yang salah untuk kamera yang diam."""
    p = PenilaianAi(KeadaanAi.FRAME_BERHENTI, umur_detik=None, diam_sejak=1_050.0)
    kawat = ke_kawat(p, ambang_detik=30, sekarang=1_100.0, jam_dinding=1_790_000_000.0)
    assert (kawat["keadaan"], kawat["mati"], kawat["kode"]) == ("frame_berhenti", False, KODE_FRAME_BERHENTI)
    assert kawat["sejak"] == 1_790_000_000.0 - 50.0


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
        ({"keadaan": "sumber_diam", "mati": False}, 200),      # line versi 2.1
        ({"keadaan": "sumber_selesai", "mati": False}, 200),
        ({"keadaan": "frame_berhenti", "mati": False}, 503),
        ({"keadaan": "ai_mati", "mati": True}, 503),
    ],
)
def test_health_503_hanya_untuk_ai_mati_dan_frame_berhenti(ai, kode):
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
