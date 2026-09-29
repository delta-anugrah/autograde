"""`PenjagaAi`: fakta dari `RuntimeState` + kamera + lisensi → satu penilaian.

Aturannya sendiri diuji di `test_kesehatan_ai.py`; di sini yang dijaga
perakitannya: jam yang sama untuk cap dan penilai, lisensi dibaca dari tempat
yang sama dengan gerbang grading, dan log transisi sekali, bukan tiap tick PLC
(lima kali per detik).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

from palmgrade.core.config import Settings
from palmgrade.services import penjaga_ai
from palmgrade.services.penjaga_ai import PenjagaAi, ringkas_ai_dari_state
from palmgrade.workers.runtime_state import RuntimeState


class JamPalsu:
    def __init__(self) -> None:
        self.sekarang = 1_000.0

    def __call__(self) -> float:
        return self.sekarang


class KameraPalsu:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected


def _rakit(**ubah):
    jam = JamPalsu()
    state = RuntimeState(jam=jam)
    kamera = KameraPalsu()
    settings = replace(Settings(), **{"ai_mati_detik": 30, "lic_enabled": False, **ubah})
    penjaga = PenjagaAi(settings=settings, state=state, kamera=kamera,
                        jam_dinding=lambda: 1_790_000_000.0)
    return penjaga, state, kamera, jam


def _gambar_mengalir_tanpa_selesai(state, jam, detik):
    state.catat_ai_dimulai()
    for _ in range(int(detik)):
        state.catat_frame_masuk()
        jam.sekarang += 1


def test_line_sehat_tidak_menaikkan_error():
    penjaga, state, _, jam = _rakit()
    state.catat_ai_dimulai()
    state.catat_frame_masuk()
    state.catat_inferensi_selesai()
    jam.sekarang += 1
    assert penjaga.nilai().keadaan.value == "sehat"
    assert penjaga.sehat_untuk_plc() is True


def test_ai_mati_menaikkan_error_dan_membawa_kode_di_ringkasan():
    penjaga, state, _, jam = _rakit()
    _gambar_mengalir_tanpa_selesai(state, jam, 31)
    state.catat_frame_masuk()

    assert penjaga.sehat_untuk_plc() is False
    ringkas = penjaga.ringkas()
    assert (ringkas["keadaan"], ringkas["mati"], ringkas["kode"]) == ("ai_mati", True, "AI_MATI")
    assert ringkas["sejak"] == 1_790_000_000.0 - 31.0
    assert ringkas["ambang_detik"] == 30


def test_kamera_putus_tetap_menaikkan_error_seperti_sebelum_batch_ini():
    penjaga, _, kamera, _ = _rakit()
    kamera.connected = False
    assert penjaga.sehat_untuk_plc() is False
    assert penjaga.ringkas()["mati"] is False


def test_lisensi_habis_dibaca_dari_gerbang_grading_bukan_ai_mati():
    penjaga, state, _, jam = _rakit(lic_enabled=True)
    state.license_exp = 0
    _gambar_mengalir_tanpa_selesai(state, jam, 60)
    assert penjaga.nilai().keadaan.value == "lisensi"
    assert penjaga.sehat_untuk_plc() is True


def test_ambang_dibaca_dari_settings():
    penjaga, state, _, jam = _rakit(ai_mati_detik=120)
    _gambar_mengalir_tanpa_selesai(state, jam, 60)
    assert penjaga.nilai().keadaan.value == "memulai"


def test_ringkasan_lengkap_membawa_galat_untuk_support_saja():
    penjaga, state, _, _ = _rakit()
    state.catat_galat_ai(RuntimeError("CUDA error: an illegal memory access"))
    assert "galat_terakhir" not in penjaga.ringkas()
    assert penjaga.ringkas_lengkap()["galat_terakhir"] == "RuntimeError: CUDA error: an illegal memory access"


def test_transisi_dicatat_sekali_masing_masing(caplog):
    penjaga, state, _, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _gambar_mengalir_tanpa_selesai(state, jam, 31)
    state.catat_frame_masuk()
    for _ in range(25):                      # lima detik tick PLC
        penjaga.sehat_untuk_plc()
    state.catat_inferensi_selesai()
    for _ in range(25):
        penjaga.sehat_untuk_plc()

    error = [r for r in caplog.records if r.levelno == logging.ERROR]
    pulih = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(error) == 1 and "AI_MATI" in error[0].getMessage()
    assert len(pulih) == 1 and "tidak lagi dinilai mati" in pulih[0].getMessage()


def test_keluar_dari_ai_mati_ke_kamera_putus_tidak_mengaku_memproses(caplog):
    penjaga, state, kamera, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _gambar_mengalir_tanpa_selesai(state, jam, 31)
    state.catat_frame_masuk()
    assert penjaga.nilai().mati
    kamera.connected = False
    penjaga.sehat_untuk_plc()

    pulih = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(pulih) == 1
    assert "memproses lagi" not in pulih[0]
    assert "kamera_putus" in pulih[0]


def test_penilaian_basi_yang_tiba_belakangan_tidak_membalik_transisi(caplog, monkeypatch):
    """Pembaca A (tick PLC) menilai tepat di ambang (`memulai`); sebelum A sempat
    mencatat, 0,5 detik lewat dan pembaca B (HTTP) menilai `ai_mati`. Kalau A
    boleh mencatat sesudah B, satu transisi nyata tercatat tiga baris
    (ERROR, WARNING, ERROR)."""
    penjaga, state, _, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _gambar_mengalir_tanpa_selesai(state, jam, 30)
    state.catat_frame_masuk()                 # jam 1030: tepat di ambang, belum mati

    asli = penjaga_ai.nilai_ai
    b: list[threading.Thread] = []

    def nilai_ai_a(fakta):
        hasil = asli(fakta)
        if not b:                             # hanya pembaca A yang disela
            jam.sekarang += 0.5
            b.append(threading.Thread(target=penjaga.sehat_untuk_plc))
            b[0].start()
            b[0].join(timeout=0.5)            # tanpa kunci, B selesai di sini
        return hasil

    monkeypatch.setattr(penjaga_ai, "nilai_ai", nilai_ai_a)
    penjaga.sehat_untuk_plc()                 # pembaca A
    b[0].join(timeout=5)
    assert not b[0].is_alive()
    monkeypatch.setattr(penjaga_ai, "nilai_ai", asli)
    for _ in range(5):
        penjaga.sehat_untuk_plc()

    error = [r for r in caplog.records if r.levelno == logging.ERROR]
    pulih = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(error) == 1 and "AI_MATI" in error[0].getMessage()
    assert pulih == []


def test_ringkas_dari_state_tanpa_penjaga_adalah_none():
    assert ringkas_ai_dari_state(RuntimeState()) is None
    assert ringkas_ai_dari_state(None) is None


def test_ringkas_dari_state_memakai_penjaga_yang_dipasang():
    penjaga, state, _, _ = _rakit()
    state.penjaga_ai = penjaga
    assert ringkas_ai_dari_state(state)["keadaan"] == "memulai"
    assert "galat_terakhir" in ringkas_ai_dari_state(state, lengkap=True)


def test_modul_tidak_menarik_torch_cv2_atau_ultralytics():
    """Kalau modul ini menarik torch, semua test di atas dilewati di CI."""
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.services.penjaga_ai\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]


def _error_mati(caplog) -> str:
    [pesan] = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    return pesan


def test_error_mati_menyebut_galat_yang_terjadi_sesudah_ai_berhenti(caplog):
    penjaga, state, _, jam = _rakit()
    _gambar_mengalir_tanpa_selesai(state, jam, 20)
    state.ai_galat_terakhir, state.ai_galat_at = "RuntimeError: CUDA error", 1_790_000_000.0 - 5
    _gambar_mengalir_tanpa_selesai(state, jam, 12)

    with caplog.at_level(logging.ERROR, logger=penjaga_ai.__name__):
        penjaga.nilai()

    assert "Galat terakhir: RuntimeError: CUDA error" in _error_mati(caplog)


def test_error_mati_tidak_menyodorkan_galat_lama_sebagai_sebab(caplog):
    """Parkiran Task 6: galat terakhir itu sejak BOOT. Galat pagi tadi yang sudah pulih
    lalu tercetak di ERROR AI mati sore ini menyesatkan support ke sebab yang salah."""
    penjaga, state, _, jam = _rakit()
    state.ai_galat_terakhir, state.ai_galat_at = "RuntimeError: CUDA error pagi", 1_790_000_000.0 - 7_200
    _gambar_mengalir_tanpa_selesai(state, jam, 32)

    with caplog.at_level(logging.ERROR, logger=penjaga_ai.__name__):
        penjaga.nilai()

    pesan = _error_mati(caplog)
    assert "tidak ada galat sejak AI berhenti" in pesan
    assert "7200 detik lalu" in pesan and "CUDA error pagi" in pesan
