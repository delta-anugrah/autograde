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


def _siklus_sambung_ulang(penjaga, state, kamera, jam, *, berhasil: bool) -> list[str]:
    """Satu `_try_reconnect` seperti `FrameCaptureWorker`, dengan penilaian (tick PLC)
    di tiap sela: sesudah memutus, di jeda backoff, tepat sesudah `connect()`
    menyetel `connected` tapi SEBELUM hasilnya dicatat, dan sesudah dicatat."""
    keadaan = []
    kamera.connected = False                          # disconnect()
    keadaan.append(penjaga.nilai().keadaan.value)
    jam.sekarang += 1.0                               # tidur backoff
    keadaan.append(penjaga.nilai().keadaan.value)
    kamera.connected = berhasil                       # connect() selesai
    keadaan.append(penjaga.nilai().keadaan.value)
    state.catat_sambung_kamera(berhasil=kamera.connected)
    keadaan.append(penjaga.nilai().keadaan.value)
    jam.sekarang += 1.0                               # lima grab gagal lagi
    keadaan.append(penjaga.nilai().keadaan.value)
    return keadaan


def test_sambung_ulang_berselang_masuk_frame_berhenti_sekali_tanpa_berkedip(caplog):
    """Simulasi review akhir 2: satu gambar terakhir lalu diam, sambung ulang
    bergantian berhasil dan gagal tiap 2 detik selama 120 detik. Dulu: berkedip
    frame_berhenti/kamera_putus tiap siklus (60 transisi), atau tidak pernah
    beralarm sama sekali. Sekarang: masuk sekali, keluar hanya saat gambar datang."""
    penjaga, state, kamera, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _sehat_lalu_gambar_berhenti(state, jam, 1)
    riwayat = []
    for i in range(60):
        riwayat += _siklus_sambung_ulang(penjaga, state, kamera, jam, berhasil=i % 2 == 0)

    masuk = riwayat.index("frame_berhenti")
    assert set(riwayat[masuk:]) == {"frame_berhenti"}
    assert set(riwayat[:masuk]) <= {"sehat", "memulai", "kamera_putus"}
    error = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error) == 1 and "FRAME_BERHENTI" in error[0]
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    kamera.connected = True
    state.catat_frame_masuk()
    state.catat_inferensi_selesai()
    assert penjaga.nilai().keadaan.value == "sehat"
    pulih = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert pulih == ["Kamera line-2 tidak lagi dinilai berhenti mengirim (keadaan sehat)"]


def test_semua_sambung_ulang_gagal_tetap_kamera_putus(caplog):
    """Kabel dicabut: tiap sambung ulang sejak gambar terakhir gagal. Itu kamera
    putus sepanjang waktu, tidak pernah frame berhenti."""
    penjaga, state, kamera, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _sehat_lalu_gambar_berhenti(state, jam, 1)
    riwayat = []
    for _ in range(60):
        riwayat += _siklus_sambung_ulang(penjaga, state, kamera, jam, berhasil=False)
    assert set(riwayat) == {"kamera_putus"}
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_akhir_putus_panjang_tidak_menulis_frame_berhenti_palsu(caplog):
    """Lima menit putus sungguhan lalu kamera kembali. Tick PLC yang jatuh di sela
    `connect()` dan pencatatan hasilnya dulu menulis satu ERROR FRAME_BERHENTI palsu
    tepat saat kameranya kembali, dan ERROR itu sampai ke Discord."""
    penjaga, state, kamera, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    _sehat_lalu_gambar_berhenti(state, jam, 1)
    for _ in range(150):
        _siklus_sambung_ulang(penjaga, state, kamera, jam, berhasil=False)
    kembali = _siklus_sambung_ulang(penjaga, state, kamera, jam, berhasil=True)
    assert kembali == ["kamera_putus", "kamera_putus", "kamera_putus", "memulai", "memulai"]
    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


def test_gagal_sambung_saat_boot_dicatat_supaya_sambung_pertama_tidak_berteriak(caplog):
    """`main.py` mencatat hasil `connect()` saat boot. Tanpa itu, sambung ulang
    pertama sesudah boot yang gagal membaca `kamera_sambung_ok` None, dan tick di
    sela `connect()` dan pencatatan hasilnya terbaca frame berhenti."""
    penjaga, state, kamera, jam = _rakit()
    caplog.set_level(logging.WARNING, logger="palmgrade.services.penjaga_ai")
    kamera.connected = False
    state.catat_sambung_kamera(berhasil=False)       # connect() saat boot gagal
    state.catat_ai_dimulai()
    jam.sekarang += 120
    kembali = _siklus_sambung_ulang(penjaga, state, kamera, jam, berhasil=True)
    assert "frame_berhenti" not in kembali
    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []
