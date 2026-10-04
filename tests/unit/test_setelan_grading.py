"""Setelan grading yang bisa diubah dari konsol (`role=support`).

`CONF_THRESHOLD` dan `MINIMUM_SIZE` sebelumnya cuma hidup di `.env`, jadi
mengubahnya berarti SSH/AnyDesk ke PC pabrik, edit berkas, restart tiga
container. Sekarang keduanya bisa diatur dari layar developer.

Yang dijaga di sini, dan kenapa:

- **Angka ini mengubah uang.** `MINIMUM_SIZE` menentukan janjang kecil dibuang
  atau lolos; `CONF_THRESHOLD` menentukan apa yang dianggap buah sama sekali.
  Nilai di luar akal (negatif, 0, di atas 1) harus ditolak di pintu, bukan
  diam-diam membuat satu line berhenti menghitung selama satu shift.
- **Nilainya satu untuk semua line** (keputusan operator 2026-09-16), jadi
  sumbernya satu baris di `sync_state` — bukan tiga.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.setelan_grading import (
    BATAS,
    SetelanTidakSah,
    bersihkan_setelan,
)


def test_nilai_wajar_diterima_apa_adanya():
    # `garis_capture` menyusul 2026-09-18 dan opsional: payload tanpa dia tetap
    # sah, dan diisi 0 = garis mati = perilaku sebelum fitur itu ada. Bentuk
    # lengkapnya dikunci di sini karena inilah yang disimpan ke `sync_state` dan
    # dikirim ke tiga line.
    assert bersihkan_setelan({"conf_threshold": 0.5, "minimum_size": 3000}) == {
        "conf_threshold": 0.5,
        "minimum_size": 3000,
        "garis_capture": 0,
        "sumbu_garis": "tegak",
        "mode_dev": False,
        "tampil_garis": True,
        "tampil_roi": True,
        "roi_x1": None, "roi_y1": None, "roi_x2": None, "roi_y2": None,
    }


def test_angka_berbentuk_teks_diterima():
    """Yang mengirim itu layar, dan input HTML selalu memberi string."""
    assert bersihkan_setelan(
        {"conf_threshold": "0.75", "minimum_size": "460000", "garis_capture": "900"}
    ) == {
        "conf_threshold": 0.75,
        "minimum_size": 460000,
        "garis_capture": 900,
        "sumbu_garis": "tegak",
        "mode_dev": False,
        "tampil_garis": True,
        "tampil_roi": True,
        "roi_x1": None, "roi_y1": None, "roi_x2": None, "roi_y2": None,
    }


def test_koma_diterima_sebagai_desimal():
    """Papan ketik Indonesia. `0,5` yang ditolak di gerbang bikin operator
    mengetik ulang tanpa tahu apa yang salah."""
    assert bersihkan_setelan({"conf_threshold": "0,5", "minimum_size": 3000})[
        "conf_threshold"
    ] == 0.5


@pytest.mark.parametrize("nilai", [0, -0.1, 1.5, 2, "abc", "", None])
def test_conf_di_luar_nol_sampai_satu_ditolak(nilai):
    """`conf=0` membuat model melaporkan setiap bercak sebagai buah; di atas 1
    membuatnya tidak pernah melaporkan apa pun. Dua-duanya mematikan grading
    tanpa satu pun pesan error."""
    with pytest.raises(SetelanTidakSah):
        bersihkan_setelan({"conf_threshold": nilai, "minimum_size": 3000})


@pytest.mark.parametrize("nilai", [0, -1, "abc", "", None, 10**9])
def test_minimum_size_di_luar_akal_ditolak(nilai):
    """0 mematikan penjaga ukuran; terlalu besar membuat SEMUA janjang dianggap
    kekecilan dan di-REJ — satu shift penuh tonase salah."""
    with pytest.raises(SetelanTidakSah):
        bersihkan_setelan({"conf_threshold": 0.5, "minimum_size": nilai})


def test_pesan_salah_menyebut_batasnya():
    """Operator harus tahu angka yang boleh, bukan cuma 'tidak sah'."""
    with pytest.raises(SetelanTidakSah) as e:
        bersihkan_setelan({"conf_threshold": 5, "minimum_size": 3000})
    pesan = str(e.value)
    assert str(BATAS["conf_threshold"][0]) in pesan or "0" in pesan
    assert "conf" in pesan.lower()


def test_field_yang_tidak_dikenal_ditolak():
    """Menerima field asing diam-diam berarti salah ketik nama field terlihat
    seperti berhasil padahal tidak mengubah apa pun."""
    with pytest.raises(SetelanTidakSah):
        bersihkan_setelan({"conf_threshold": 0.5, "minimum_size": 3000, "yolo_skip": 2})


def test_dua_duanya_wajib_ada():
    with pytest.raises(SetelanTidakSah):
        bersihkan_setelan({"conf_threshold": 0.5})


def test_saklar_tampil_bawaannya_nyala_dan_bisa_dimatikan():
    """Display only (2026-10-04). A payload without them is an older console, where the
    capture line and the ROI box were always drawn; False hides the drawing."""
    dasar = {"conf_threshold": 0.5, "minimum_size": 3000}
    bersih = bersihkan_setelan(dasar)
    assert (bersih["tampil_garis"], bersih["tampil_roi"]) == (True, True)
    bersih = bersihkan_setelan({**dasar, "tampil_garis": False, "tampil_roi": False})
    assert (bersih["tampil_garis"], bersih["tampil_roi"]) == (False, False)
    # Hiding the line never moves it: the capture trigger keeps its position.
    assert bersihkan_setelan({**dasar, "garis_capture": 900, "tampil_garis": False})["garis_capture"] == 900


# ── detection area box (ROI) from the console, 2026-10-04 ───────────────────

_DASAR = {"conf_threshold": 0.5, "minimum_size": 3000}
_KOSONG = {"roi_x1": None, "roi_y1": None, "roi_x2": None, "roi_y2": None}


def test_kotak_tidak_dikirim_berarti_ikut_env():
    """An older console, or a row saved before the box existed, must not reset a calibrated
    box: None means "the line keeps its own ROI_*", never "full frame"."""
    from palmgrade.domain.setelan_grading import kotak_dari

    bersih = bersihkan_setelan(_DASAR)
    assert {k: bersih[k] for k in _KOSONG} == _KOSONG
    assert kotak_dari(bersih) is None
    # Four empty inputs from the screen mean the same.
    bersih = bersihkan_setelan({**_DASAR, **dict.fromkeys(_KOSONG, "")})
    assert kotak_dari(bersih) is None


def test_kotak_diisi_jadi_empat_bilangan_bulat():
    from palmgrade.domain.setelan_grading import kotak_dari

    bersih = bersihkan_setelan({**_DASAR, "roi_x1": "100", "roi_y1": 50, "roi_x2": "1180", "roi_y2": 620})
    assert kotak_dari(bersih) == (100, 50, 1180, 620)
    # All zeros is a real value: the full frame, on purpose.
    assert kotak_dari(bersihkan_setelan({**_DASAR, **dict.fromkeys(_KOSONG, 0)})) == (0, 0, 0, 0)
    # 0 on the far edge alone = up to the edge of the picture, as in `.env`.
    assert kotak_dari(bersihkan_setelan({**_DASAR, "roi_x1": 100, "roi_y1": 0, "roi_x2": 0, "roi_y2": 0})) == (100, 0, 0, 0)


@pytest.mark.parametrize("kotak", [
    {"roi_x1": 100, "roi_y1": None, "roi_x2": 500, "roi_y2": 400},   # one left empty
    {"roi_x1": 500, "roi_y1": 0, "roi_x2": 500, "roi_y2": 400},      # no width
    {"roi_x1": 0, "roi_y1": 400, "roi_x2": 500, "roi_y2": 300},      # upside down
    {"roi_x1": -1, "roi_y1": 0, "roi_x2": 500, "roi_y2": 400},
    {"roi_x1": 0, "roi_y1": 0, "roi_x2": 20000, "roi_y2": 400},
    {"roi_x1": "abc", "roi_y1": 0, "roi_x2": 500, "roi_y2": 400},
])
def test_kotak_cacat_ditolak(kotak):
    """A box with no area filters every bunch out while the line looks healthy."""
    with pytest.raises(SetelanTidakSah):
        bersihkan_setelan({**_DASAR, **kotak})
