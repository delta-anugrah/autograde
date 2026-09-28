"""Cap waktu penjaga AI di `RuntimeState` (batch 2.1).

Keempat cap ditulis thread yang berbeda (capture, deteksi) dan dibaca penilai
dari thread lain lagi; yang dijaga di sini aturan kecil yang kalau salah membuat
alarm AI mati tidak pernah menyala (tenggang yang terus diperbarui) atau
menyala palsu (aliran yang tidak pernah dianggap mulai lagi).
"""
from __future__ import annotations

import time

from palmgrade.domain.kesehatan_ai import JEDA_ALIRAN_DETIK
from palmgrade.workers.runtime_state import RuntimeState


class JamPalsu:
    def __init__(self, mulai: float = 1_000.0) -> None:
        self.sekarang = mulai

    def __call__(self) -> float:
        return self.sekarang


def _state() -> tuple[RuntimeState, JamPalsu]:
    jam = JamPalsu()
    return RuntimeState(jam=jam), jam


def test_jam_bawaan_monotonic():
    assert RuntimeState().jam is time.monotonic


def test_mulai_dicap_sekali_saja_walau_thread_dinyalakan_ulang():
    state, jam = _state()
    state.catat_ai_dimulai()
    jam.sekarang += 500
    state.catat_ai_dimulai()
    assert state.ai_dimulai_at == 1_000.0


def test_frame_pertama_memulai_aliran():
    state, _ = _state()
    state.catat_frame_masuk()
    assert (state.frame_terakhir_at, state.aliran_frame_sejak) == (1_000.0, 1_000.0)


def test_frame_beruntun_tidak_memulai_aliran_baru():
    state, jam = _state()
    state.catat_frame_masuk()
    for _ in range(10):
        jam.sekarang += 0.05
        state.catat_frame_masuk()
    assert state.aliran_frame_sejak == 1_000.0
    assert state.frame_terakhir_at == jam.sekarang


def test_jeda_panjang_memulai_aliran_baru():
    state, jam = _state()
    state.catat_frame_masuk()
    jam.sekarang += JEDA_ALIRAN_DETIK + 0.1
    state.catat_frame_masuk()
    assert state.aliran_frame_sejak == jam.sekarang


def test_inferensi_selesai_memakai_jam_yang_sama():
    state, jam = _state()
    jam.sekarang = 1_234.5
    state.catat_inferensi_selesai()
    assert state.inferensi_selesai_at == 1_234.5


def test_galat_dipotong_dan_membawa_jenisnya():
    state, _ = _state()
    state.catat_galat_ai(RuntimeError("CUDA error: an illegal memory access " + "x" * 500))
    assert state.ai_galat_terakhir.startswith("RuntimeError: CUDA error")
    assert len(state.ai_galat_terakhir) == 300
    assert state.ai_galat_at > 0
