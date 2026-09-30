"""`PenjagaAi` untuk frame berhenti dan sumber selesai (batch 3.6).

Aturannya diuji di `test_kesehatan_ai.py`; di sini perakitannya: fakta kamera
dibaca dari `RuntimeState` dan `camera.exhausted`, coil ERROR ikut naik, dan
transisinya dicatat sekali masing-masing ke log.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.services.penjaga_ai import PenjagaAi
from palmgrade.workers.runtime_state import RuntimeState


class JamPalsu:
    def __init__(self) -> None:
        self.sekarang = 1_000.0

    def __call__(self) -> float:
        return self.sekarang


class KameraPalsu:
    def __init__(self) -> None:
        self.connected = True
        self.exhausted = False


def _rakit():
    jam = JamPalsu()
    state = RuntimeState(jam=jam)
    kamera = KameraPalsu()
    settings = replace(Settings(), ai_mati_detik=30, lic_enabled=False,
                       machine_id="a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02")   # line-2
    penjaga = PenjagaAi(settings=settings, state=state, kamera=kamera,
                        jam_dinding=lambda: 1_790_000_000.0)
    return penjaga, state, kamera, jam


def _sehat_lalu_gambar_berhenti(state, jam, detik_berhenti: int) -> None:
    state.catat_ai_dimulai()
    for _ in range(5):
        state.catat_frame_masuk()
        state.catat_inferensi_selesai()
        jam.sekarang += 1
    jam.sekarang += detik_berhenti


def test_frame_berhenti_menaikkan_error_dan_membawa_kodenya():
    penjaga, state, _, jam = _rakit()
    _sehat_lalu_gambar_berhenti(state, jam, 31)
    assert penjaga.sehat_untuk_plc() is False
    ringkas = penjaga.ringkas()
    assert (ringkas["keadaan"], ringkas["mati"], ringkas["kode"]) == (
        "frame_berhenti", False, "FRAME_BERHENTI"
    )
    assert ringkas["sejak"] == 1_790_000_000.0 - 32.0


def test_kamera_bolak_balik_sambung_dibaca_dari_state():
    penjaga, state, kamera, jam = _rakit()
    _sehat_lalu_gambar_berhenti(state, jam, 1)
    state.catat_sambung_kamera(berhasil=True)   # sambung ulang pertama berhasil,
    jam.sekarang += 31                           # gambar tetap tidak datang,
    state.catat_sambung_kamera(berhasil=True)   # sambung berikutnya juga berhasil,
    kamera.connected = False                     # dan tepat di sela sambung berikutnya
    assert penjaga.nilai().keadaan.value == "frame_berhenti"


def test_sambung_ulang_gagal_dibaca_kamera_putus():
    penjaga, state, kamera, jam = _rakit()
    _sehat_lalu_gambar_berhenti(state, jam, 31)
    state.catat_sambung_kamera(berhasil=False)
    kamera.connected = False
    assert penjaga.nilai().keadaan.value == "kamera_putus"
    assert penjaga.sehat_untuk_plc() is False     # coil ERROR seperti dulu


def test_video_habis_dibaca_dari_kamera_dan_tidak_menaikkan_error():
    penjaga, state, kamera, jam = _rakit()
    _sehat_lalu_gambar_berhenti(state, jam, 60)
    kamera.exhausted, kamera.connected = True, False
    assert penjaga.nilai().keadaan.value == "sumber_selesai"
    assert penjaga.sehat_untuk_plc() is True


def test_kamera_tanpa_atribut_exhausted_tetap_bisa_dinilai():
    penjaga, state, kamera, jam = _rakit()
    del kamera.exhausted
    _sehat_lalu_gambar_berhenti(state, jam, 1)
    assert penjaga.nilai().keadaan.value == "sehat"


def test_transisi_frame_berhenti_dicatat_sekali_masing_masing(caplog):
    penjaga, state, _, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _sehat_lalu_gambar_berhenti(state, jam, 31)
    for _ in range(25):                          # lima detik tick PLC
        penjaga.sehat_untuk_plc()
    state.catat_frame_masuk()
    state.catat_inferensi_selesai()
    for _ in range(25):
        penjaga.sehat_untuk_plc()

    error = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    pulih = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(error) == 1
    assert "line-2" in error[0] and "FRAME_BERHENTI" in error[0] and "restart line" in error[0]
    assert pulih == ["Kamera line-2 tidak lagi dinilai berhenti mengirim (keadaan sehat)"]


def test_ai_mati_lalu_frame_berhenti_mencatat_error_baru_tanpa_mengaku_pulih(caplog):
    penjaga, state, _, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    state.catat_ai_dimulai()
    for _ in range(32):                          # gambar mengalir, tidak ada yang selesai
        state.catat_frame_masuk()
        jam.sekarang += 1
    assert penjaga.nilai().mati
    jam.sekarang += 40                           # lalu gambarnya ikut berhenti
    assert penjaga.nilai().keadaan.value == "frame_berhenti"

    error = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error) == 2 and "AI_MATI" in error[0] and "FRAME_BERHENTI" in error[1]
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    # Baris ini yang dibaca support di tab Log dan Discord: tindakannya ikut.
    assert error[0].endswith("Restart line lewat Setelan, Danger Zone, lalu periksa log line itu.")
    assert error[1].endswith(
        "Periksa kabel data dan switch kamera, lalu restart line lewat Setelan, Danger Zone."
    )
