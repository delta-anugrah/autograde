"""What `FrameProcessingWorker` decides for a frame, pinned before and after batch 6.1.

Batch 6.1 changed HOW the boxes are read (one `boxes.cpu().numpy()` per frame, not one
`.item()` or `.tolist()` per value in three scans). It must not change WHAT is decided: the
same PLC pulses, the same bunches saved, the same stalk on the same bunch (rule 1c), one
trigger per bunch (rule 2).

Three layers, all through the real worker with fake results (`hasil_yolo_palsu`, no torch):

* named scenes with the expected outcome written out;
* a golden file made by the code BEFORE the change, replayed on seeded random conveyors;
* the cost itself: one transfer per frame and no value read on the device.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hasil_yolo_palsu import HasilPalsu, LineBerskrip, hasil, kotak, ringkasan_skenario

EMAS = Path(__file__).with_name("frame_processing_jejak_lama.json")

# The capture line sits at 300 px of the 1280 px stream, which is x = 573 on the 2448 px
# sensor frame. A bunch is photographed when its box touches that line.
BELUM = (1500, 300, 2300, 1100)     # right of the line
MENYENTUH = (500, 300, 1300, 1100)  # on the line, 800 x 800 px (above MINIMUM_SIZE)
LEWAT = (300, 300, 1100, 1100)      # still on the line one frame later


@pytest.fixture
def line(monkeypatch) -> LineBerskrip:
    return LineBerskrip(monkeypatch)


def test_janjang_matang_satu_pulse_dan_satu_simpan_saat_menyentuh_garis(line):
    sebelum = line.proses(hasil(kotak(7, "Ripe", *BELUM)))
    saat = line.proses(hasil(kotak(7, "Ripe", *MENYENTUH, conf=0.875)))

    assert sebelum["plc"] == [] and sebelum["simpan"] == []
    assert saat["plc"] == ["acc"]
    assert saat["simpan"] == [{
        "status": "acc", "kelas": "Ripe", "conf": 0.875,
        "kotak": {"x_min": 500, "y_min": 300, "x_max": 1300, "y_max": 1100}, "tp": None,
    }]
    assert saat["acara"][0]["ripeness_status"] == "acc"


def test_janjang_yang_terus_menyentuh_garis_hanya_dipicu_sekali(line):
    """Rule 2: an active track is never triggered twice, however long it stays on the line."""
    line.proses(hasil(kotak(7, "Ripe", *MENYENTUH)))
    lagi = line.proses(hasil(kotak(7, "Ripe", *LEWAT)))
    hilang = line.proses(hasil())
    kembali = line.proses(hasil(kotak(7, "Ripe", *LEWAT)))

    assert lagi["plc"] == [] and lagi["simpan"] == []
    assert hilang["sudah_diproses"] == [7]
    assert kembali["plc"] == [] and kembali["simpan"] == [], "a returning id fired again"


@pytest.mark.parametrize(("kelas", "status"), [("Unripe", "rej"), ("JK", "rej")])
def test_kelas_buang_menembak_rej_dan_tetap_membawa_kelasnya(line, kelas, status):
    saat = line.proses(hasil(kotak(3, kelas, *MENYENTUH)))

    assert saat["plc"] == [status]
    assert (saat["simpan"][0]["status"], saat["simpan"][0]["kelas"]) == (status, kelas)


def test_janjang_terlalu_kecil_dibuang_tapi_kelasnya_tetap_ripe(line):
    saat = line.proses(hasil(kotak(4, "Ripe", 500, 300, 900, 700)))  # 400 x 400 px

    assert saat["plc"] == ["rej"]
    assert (saat["simpan"][0]["status"], saat["simpan"][0]["kelas"]) == ("rej", "Ripe")


def test_dua_buah_bertumpuk_di_roi_dipaksa_rej(line):
    saat = line.proses(hasil(
        kotak(1, "Ripe", *MENYENTUH),
        kotak(2, "Ripe", 1400, 300, 2200, 1100),  # in the ROI, not on the line yet
    ))

    assert saat["plc"] == ["rej"]
    assert [job["status"] for job in saat["simpan"]] == ["rej"]


def test_kotak_tanpa_track_id_tidak_digrading(line):
    tanpa_id = line.proses(hasil(kotak(7, "Ripe", *MENYENTUH), berjejak=False))
    id_minus = line.proses(hasil(kotak(-1, "Ripe", *MENYENTUH)))
    kosong = line.proses(HasilPalsu(None))

    for frame in (tanpa_id, id_minus, kosong):
        assert frame["plc"] == [] and frame["simpan"] == []


@pytest.mark.parametrize("tp_dulu", [True, False], ids=["tp-first", "tp-last"])
def test_tp_terdekat_yang_terpasang_apa_pun_urutan_kotaknya(line, tp_dulu):
    """Rule 1c: the stalk is paired by distance, and box order inside a frame is not a rule."""
    janjang = kotak(1, "Ripe", *MENYENTUH)
    dekat = kotak(21, "TP", 1250, 650, 1400, 800, conf=0.81)
    jauh = kotak(22, "TP", 2200, 1800, 2350, 1950, conf=0.95)
    baris = (jauh, dekat, janjang) if tp_dulu else (janjang, dekat, jauh)

    saat = line.proses(hasil(*baris))

    tp = saat["simpan"][0]["tp"]
    assert tp is not None and tp[0] == 21, "the far stalk, or none, was attached"
    assert tp[3] == [1250, 650, 1400, 800]
    assert saat["acara"][0]["tp_status"] == "PASS"
    assert saat["sudah_diproses"] == [1, 21], "the stalk must be marked as used"


def test_tp_milik_janjang_yang_sudah_difoto_tidak_pindah_ke_tetangganya(line):
    """Rule 1c: a photographed bunch still competes for the stalk next to it."""
    atas = (500, 100, 1300, 900)
    bawah = (500, 1000, 1800, 1900)
    line.proses(hasil(kotak(1, "Ripe", *atas)))
    # The stalk sits inside the upper bunch, within reach of the lower one.
    saat = line.proses(hasil(
        kotak(1, "Ripe", *atas), kotak(2, "Ripe", *bawah), kotak(21, "TP", 850, 700, 950, 800),
    ))

    assert [job["tp"] for job in saat["simpan"]] == [None]
    assert saat["tp_telat"] == 1, "the late stalk of the upper bunch must be counted"


def test_tp_untuk_janjang_rej_tidak_dicari(line):
    saat = line.proses(hasil(
        kotak(3, "Unripe", *MENYENTUH), kotak(21, "TP", 1250, 650, 1400, 800),
    ))

    assert saat["simpan"][0]["tp"] is None
    assert saat["sudah_diproses"] == [3]


def test_satu_tangkai_tidak_ikut_ke_janjang_berikutnya(line):
    tangkai = kotak(21, "TP", 1250, 650, 1400, 800)
    pertama = line.proses(hasil(kotak(1, "Ripe", *MENYENTUH), tangkai))
    kedua = line.proses(hasil(kotak(2, "Ripe", *MENYENTUH), tangkai))

    assert pertama["simpan"][0]["tp"][0] == 21
    assert kedua["simpan"][0]["tp"] is None, "one stalk was paid on two bunches"


def test_tp_telat_dihitung_sekali_per_tangkai(line):
    line.proses(hasil(kotak(1, "Ripe", *MENYENTUH)))
    tangkai = kotak(21, "TP", 1250, 650, 1400, 800)
    satu = line.proses(hasil(kotak(1, "Ripe", *LEWAT), tangkai))
    dua = line.proses(hasil(kotak(1, "Ripe", *LEWAT), tangkai))

    assert (satu["tp_telat"], dua["tp_telat"]) == (1, 1)


def test_koordinat_pecahan_dipotong_bukan_dibulatkan(line):
    saat = line.proses(hasil(kotak(7, "Ripe", 500.9, 300.99, 1300.5, 1100.01)))

    assert saat["simpan"][0]["kotak"] == {"x_min": 500, "y_min": 300, "x_max": 1300, "y_max": 1100}


# ------------------------------------------------------------------ golden, from the old code


def _emas() -> list[dict]:
    return json.loads(EMAS.read_text(encoding="utf-8"))["skenario"]


def test_berkas_emas_memang_menguji_sesuatu():
    """A golden file of empty conveyors would pass whatever the worker does."""
    emas = _emas()

    assert len(emas) >= 40
    assert sum(s["janjang_disimpan"] for s in emas) > 200
    assert sum(s["tp_terpasang"] for s in emas) > 10
    assert sum(s["tp_telat"] for s in emas) > 10
    assert sum(s["rej"] for s in emas) > 50 and sum(s["acc"] for s in emas) > 50


@pytest.mark.parametrize("harapan", _emas(), ids=lambda s: f"seed-{s['benih']}")
def test_konveyor_acak_sama_persis_dengan_kode_sebelum_6_1(monkeypatch, harapan):
    """The file was written by the worker as it stood before batch 6.1 (commit fe3873d), by
    running `ringkasan_skenario` on the same seeds. `sidik` covers every frame: PLC pulses,
    saved bunches with their stalk, screen events, `tp_telat`, and the worker's track state."""
    assert ringkasan_skenario(monkeypatch, harapan["benih"]) == harapan


# ------------------------------------------------------------------ the cost (batch 6.1)


def test_satu_frame_satu_pemindahan_ke_cpu_dan_nol_baca_di_device(line):
    """Before 6.1 this frame cost 43 value reads on the device (three scans); each is a GPU
    synchronisation on CUDA. Now the boxes cross once and the scans read plain numbers."""
    frame = hasil(
        kotak(1, "Ripe", *MENYENTUH), kotak(2, "Unripe", *BELUM),
        kotak(21, "TP", 1250, 650, 1400, 800), kotak(-1, "JK", 100, 100, 300, 300),
    )

    saat = line.proses(frame)

    assert saat["plc"] == ["rej"], "the frame must still be graded"
    assert frame.boxes.hitung.pindah_cpu == 1
    assert frame.boxes.hitung.baca_di_device == 0


def test_frame_tanpa_kotak_tidak_memindahkan_apa_pun(line):
    frame = hasil()

    line.proses(frame)

    assert frame.boxes.hitung.pindah_cpu == 0
    assert frame.boxes.hitung.baca_di_device == 0
