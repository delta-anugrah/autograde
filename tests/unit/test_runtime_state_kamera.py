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


def test_sambung_ulang_pertama_yang_berhasil_mencap_pulih():
    state, jam = _state()
    jam.sekarang = 1_010.0
    state.catat_sambung_kamera(berhasil=True)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (True, 1_010.0)


def test_sambung_berhasil_beruntun_tidak_memperbarui_pulih():
    """Hikrobot yang berhenti mengirim: tiap lima grab gagal worker menyambung
    ulang, dan tiap sambungnya BERHASIL. Kalau itu memperbarui tenggang, alarm
    frame berhenti tidak pernah menyala."""
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=True)
    for _ in range(20):
        jam.sekarang += 3
        state.catat_sambung_kamera(berhasil=True)
    assert state.kamera_pulih_at == 1_000.0


def test_sambung_gagal_lalu_berhasil_mencap_pulih_baru():
    state, jam = _state()
    state.catat_sambung_kamera(berhasil=True)
    jam.sekarang += 60
    state.catat_sambung_kamera(berhasil=False)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (False, 1_000.0)
    jam.sekarang += 60
    state.catat_sambung_kamera(berhasil=True)
    assert (state.kamera_sambung_ok, state.kamera_pulih_at) == (True, 1_120.0)


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
