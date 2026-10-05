"""`baca_kotak`: one frame's boxes read once, as plain numbers (batch 6.1).

The reference below is the reading the worker did before 6.1, value by value on the device.
Both must give the same numbers for every frame, or a bunch is graded on a different box.
"""
from __future__ import annotations

import pytest
from hasil_yolo_palsu import HasilPalsu, LineBerskrip, hasil, kotak, skenario_acak

from palmgrade.pipelines import kotak_deteksi
from palmgrade.pipelines.kotak_deteksi import Kotak, baca_kotak
from palmgrade.workers import frame_processing_worker


def baca_kotak_cara_lama(results) -> list[Kotak]:
    """The expressions of the three scans before 6.1, kept word for word."""
    if results.boxes is None:
        return []
    terbaca = []
    for box in results.boxes:
        cls_id = int(box.cls[0].item())
        track_id = int(box.id[0].item()) if box.id is not None else -1
        score = float(box.conf[0].item())
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        terbaca.append(Kotak(track_id, cls_id, score, x1, y1, x2, y2))
    return terbaca


def test_satu_kotak_terbaca_sebagai_angka_python_biasa():
    (satu,) = baca_kotak(hasil(kotak(7, "Ripe", 500.9, 300.2, 1300.5, 1100.99, conf=0.875)))

    assert satu == Kotak(track_id=7, cls_id=1, conf=0.875, x1=500, y1=300, x2=1300, y2=1100)
    assert [type(nilai) for nilai in satu] == [int, int, float, int, int, int, int]


def test_koordinat_negatif_dipotong_ke_arah_nol_seperti_int():
    (satu,) = baca_kotak(hasil(kotak(7, "Ripe", -3.7, -0.2, 10.9, 20.5)))

    assert (satu.x1, satu.y1, satu.x2, satu.y2) == (-3, 0, 10, 20)


def test_frame_tanpa_id_memberi_minus_satu_untuk_semua_kotak():
    terbaca = baca_kotak(hasil(kotak(7, "Ripe", 0, 0, 10, 10), kotak(8, "TP", 5, 5, 9, 9), berjejak=False))

    assert [k.track_id for k in terbaca] == [-1, -1]
    assert [k.cls_id for k in terbaca] == [1, 2]


@pytest.mark.parametrize("results", [HasilPalsu(None), hasil()], ids=["boxes-none", "no-boxes"])
def test_frame_kosong_memberi_daftar_kosong_tanpa_memindahkan_apa_pun(results):
    assert baca_kotak(results) == []
    if results.boxes is not None:
        assert results.boxes.hitung.pindah_cpu == 0


def test_urutan_kotak_dipertahankan():
    frame = hasil(kotak(3, "JK", 0, 0, 1, 1), kotak(1, "Ripe", 0, 0, 1, 1), kotak(2, "TP", 0, 0, 1, 1))

    assert [k.track_id for k in baca_kotak(frame)] == [3, 1, 2]


def test_seribu_frame_acak_terbaca_sama_dengan_cara_lama():
    frames = [frame for benih in range(100, 120) for frame in skenario_acak(benih, 50)]

    assert sum(len(f.boxes) for f in frames if f.boxes is not None) > 1000
    for frame in frames:
        assert baca_kotak(frame) == baca_kotak_cara_lama(frame)


@pytest.mark.parametrize("benih", range(200, 212))
def test_worker_memutuskan_sama_dengan_pembaca_lama(benih):
    """The same conveyor through the real worker twice: once reading the old way, once the
    new way. Every frame's trace must match: PLC pulses, saved bunches and their stalk, screen
    events, `tp_telat`, track state."""

    def jalankan(pembaca) -> list[dict]:
        with pytest.MonkeyPatch.context() as tambal:
            tambal.setattr(frame_processing_worker, "baca_kotak", pembaca)
            line = LineBerskrip(tambal)
            return [line.proses(frame) for frame in skenario_acak(benih, 60)]

    lama, baru = jalankan(baca_kotak_cara_lama), jalankan(kotak_deteksi.baca_kotak)

    assert sum(len(frame["simpan"]) for frame in lama) > 0, "a conveyor with nothing graded proves nothing"
    assert baru == lama
