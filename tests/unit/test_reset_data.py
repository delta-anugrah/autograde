"""`make reset-data` menghapus data yang tidak bisa dikembalikan, jadi penjaganya dites.

Target ini menghapus foto, sidecar, dan semua SQLite di PC ini — termasuk akun
operator lokal, antrean yang belum terkirim, dan foto yang belum naik R2. Tidak
ada backup dan tidak ada cara mengembalikannya (keputusan operator 2026-09-18).

Yang dijaga berkas ini bukan perilakunya (itu `rm -rf`, tidak perlu diuji), tapi
tiga hal yang membuatnya tidak meledak di tangan orang yang salah ketik:

* butuh `TULIS=1`, sehingga salah tempel tidak menghapus apa pun;
* mematikan container lebih dulu, karena SQLite dibuka empat proses dan menghapus
  WAL di bawah proses yang hidup meninggalkan basis data separuh jadi;
* menghapus `artifacts/` dan `state/` BERSAMAAN — menghapus salah satu saja
  meninggalkan foto yatim yang tidak pernah dibersihkan retensi (retensi bekerja
  lewat manifest di `state/`).

Dibaca sebagai teks, tanpa menjalankan make — sama seperti penjaga
`test_edge_realtime_outbox.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

MAKEFILE = (Path(__file__).resolve().parents[2] / "Makefile").read_text()


def _target(nama: str) -> str:
    """Isi satu target Makefile, sampai target berikutnya."""
    blok = re.search(rf"^{nama}:\n(.*?)(?=^[a-zA-Z][a-zA-Z0-9_-]*:)", MAKEFILE, re.S | re.M)
    assert blok, f"target {nama!r} tidak ditemukan"
    return blok.group(1)


def test_target_reset_data_ada():
    assert "\nreset-data:\n" in MAKEFILE


def test_menghapus_tanpa_tulis_tidak_mungkin():
    """Penjaga utama: tanpa `TULIS=1` target ini cuma menyebutkan.

    Data yang dihapusnya permanen, jadi satu salah tempel tidak boleh cukup.
    """
    blok = _target("reset-data")
    assert "ifndef TULIS" in blok, "tidak ada penjaga TULIS"
    # `rm -rf` harus berada SESUDAH `else`, bukan di cabang kering.
    kering, _, basah = blok.partition("else")
    assert "rm -rf" not in kering, "menghapus tanpa TULIS=1"
    assert "rm -rf" in basah


def test_container_dimatikan_sebelum_berkas_dihapus():
    """SQLite dibuka tiga line + konsol. Menghapus WAL di bawah proses yang
    hidup meninggalkan basis data separuh jadi, bukan basis data kosong."""
    _, _, basah = _target("reset-data").partition("else")
    posisi_down = basah.find("down")
    posisi_rm = basah.find("rm -rf")
    assert posisi_down != -1, "container tidak dimatikan dulu"
    assert posisi_down < posisi_rm, "berkas dihapus sebelum container mati"


def test_dua_folder_dihapus_bersamaan():
    """`artifacts/` tanpa `state/` meninggalkan foto yatim: retensi menemukan
    pekerjaan lewat manifest di `state/`, jadi foto tanpa manifest tidak pernah
    dibersihkan dan disk terisi sampai grading berhenti menyimpan."""
    _, _, basah = _target("reset-data").partition("else")
    baris = next(b for b in basah.splitlines() if "rm -rf" in b)
    assert "artifacts" in baris and "state" in baris, f"cuma satu folder: {baris.strip()}"


def test_folder_dibuat_lagi_supaya_line_bisa_start():
    """Tanpa ini `docker compose up` membuat folder milik root, dan line gagal
    menulis dengan galat permission yang tidak menyebut sebabnya."""
    _, _, basah = _target("reset-data").partition("else")
    assert "mkdir -p" in basah


def test_peringatan_menyebut_akun_operator():
    """Akibat yang paling tidak terduga: `console.db` memuat akun lokal, jadi
    menghapus data grading ikut menghapus cara masuk ke konsol."""
    blok = _target("reset-data")
    assert re.search(r"[Aa]kun operator", blok), "peringatan tidak menyebut akun operator"
