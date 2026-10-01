"""Stempel kamera untuk health jujur (batch 3.6) di `RuntimeState`.

Dua aturan kecil yang kalau salah membuat alarm frame berhenti tidak pernah
menyala (tenggang yang terus diperbarui oleh sambung ulang yang berhasil) atau
menyala palsu (kamera yang baru kembali dari putus langsung dituntut gambar).
"""
from __future__ import annotations

import pytest

from palmgrade.workers.runtime_state import JENDELA_FPS_DETIK, RuntimeState


class JamPalsu:
    def __init__(self, mulai: float = 1_000.0) -> None:
        self.sekarang = mulai

    def __call__(self) -> float:
        return self.sekarang


def _state() -> tuple[RuntimeState, JamPalsu]:
    jam = JamPalsu()
    return RuntimeState(jam=jam), jam


def test_bawaan_belum_pernah_sambung_ulang():
    state, _ = _state()
    assert (state.kamera_sambung_ok, state.kamera_pulih_at, state.fps_kamera) == (None, 0.0, 0.0)
    assert state.kamera_sambung_ok_sejak_frame is False


def test_sambung_berhasil_tanpa_gagal_sebelumnya_tidak_mencap_pulih():
    """Hikrobot yang diam: sambung ulangnya berhasil tanpa pernah gagal. Itu bukan
    kamera yang kembali dari putus, jadi tidak ada tenggang gambar baru."""
    state, jam = _state()
    jam.sekarang = 1_010.0
    state.catat_sambung_kamera(berhasil=True)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (True, 0.0)
    assert state.kamera_sambung_ok_sejak_frame is True


def test_sambung_berhasil_beruntun_tidak_memperbarui_pulih():
    """Hikrobot yang berhenti mengirim: tiap lima grab gagal worker menyambung
    ulang, dan tiap sambungnya BERHASIL. Kalau itu memperbarui tenggang, alarm
    frame berhenti tidak pernah menyala."""
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=False)
    jam.sekarang += 3
    state.catat_sambung_kamera(berhasil=True)
    for _ in range(20):
        jam.sekarang += 3
        state.catat_sambung_kamera(berhasil=True)
    assert state.kamera_pulih_at == 1_003.0


def test_sambung_berselang_gagal_dan_berhasil_mencap_pulih_sekali_saja():
    """Sambung ulang yang bergantian gagal dan berhasil tidak boleh memperbarui
    tenggang tiap kali berhasil: kamera diam itu tidak pernah beralarm."""
    state, jam = _state()
    state.catat_frame_masuk()
    for i in range(30):
        jam.sekarang += 2
        state.catat_sambung_kamera(berhasil=i % 2 == 1)
    assert state.kamera_pulih_at == 1_004.0     # sukses pertama, sesudah gagal pertama
    assert state.kamera_sambung_ok is True
    assert state.kamera_sambung_ok_sejak_frame is True


def test_gambar_masuk_mengosongkan_sambung_ok_sejak_frame():
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=True)
    jam.sekarang += 1
    state.catat_frame_masuk()
    assert state.kamera_sambung_ok_sejak_frame is False
    assert state.kamera_sambung_ok is None      # gambar membuktikan kameranya tersambung
    jam.sekarang += 10
    state.catat_sambung_kamera(berhasil=False)
    assert state.kamera_sambung_ok_sejak_frame is False


def test_sambung_gagal_lalu_berhasil_sesudah_gambar_mencap_pulih_baru():
    """Kamera sungguh putus lalu kembali: tenggang gambar dimulai dari sambung yang
    berhasil, sekali per putus (gambar yang masuk memulai hitungan baru)."""
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=False)
    jam.sekarang += 10
    state.catat_sambung_kamera(berhasil=True)
    assert state.kamera_pulih_at == 1_010.0
    jam.sekarang += 5
    state.catat_frame_masuk()
    jam.sekarang += 60
    state.catat_sambung_kamera(berhasil=False)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (False, 1_010.0)
    jam.sekarang += 60
    state.catat_sambung_kamera(berhasil=True)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (True, 1_135.0)


def test_gambar_sesudah_sambung_berhasil_tidak_menyisakan_gagal_lama():
    """Gagal yang terjadi SEBELUM gambar terakhir bukan milik kejadian sekarang."""
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=False)
    jam.sekarang += 1
    state.catat_frame_masuk()
    jam.sekarang += 30
    state.catat_sambung_kamera(berhasil=True)
    assert state.kamera_pulih_at == 0.0


def test_fps_kamera_dihitung_tiap_jendela():
    state, jam = _state()
    for _ in range(int(JENDELA_FPS_DETIK * 15) + 1):   # 15 fps selama satu jendela
        state.catat_frame_masuk()
        jam.sekarang += 1 / 15
    assert state.fps_kamera == pytest.approx(15.0, rel=0.02)


def test_fps_kamera_nol_saat_aliran_baru_mulai_sesudah_jeda():
    state, jam = _state()
    for _ in range(80):
        state.catat_frame_masuk()
        jam.sekarang += 1 / 15
    assert state.fps_kamera > 0
    jam.sekarang += 60
    state.catat_frame_masuk()
    assert state.fps_kamera == 0.0
