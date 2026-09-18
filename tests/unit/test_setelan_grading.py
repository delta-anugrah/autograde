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
    }


def test_angka_berbentuk_teks_diterima():
    """Yang mengirim itu layar, dan input HTML selalu memberi string."""
    assert bersihkan_setelan(
        {"conf_threshold": "0.75", "minimum_size": "460000", "garis_capture": "900"}
    ) == {
        "conf_threshold": 0.75,
        "minimum_size": 460000,
        "garis_capture": 900,
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
