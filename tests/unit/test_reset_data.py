"""`make reset-data` menghapus data yang tidak bisa dikembalikan, jadi penjaganya dites.

Target ini menghapus foto, sidecar, dan semua SQLite di PC ini — termasuk akun
buatan `make operator`, antrean yang belum terkirim, dan foto yang belum naik R2.
Tidak ada backup dan tidak ada cara mengembalikannya (keputusan operator
2026-09-18). Dua akun bawaan image dibuat ulang sendiri saat konsol start, jadi
layar tetap bisa dibuka sesudahnya.

Yang dijaga berkas ini bukan perilakunya (itu `rm -rf`, tidak perlu diuji), tapi
tiga hal yang membuatnya tidak meledak di tangan orang yang salah ketik:

* dua target terpisah — `reset-data` cuma melihat, `reset-data-fresh` menghapus —
  dan yang menghapus minta **konfirmasi diketik**. Layar sentuh bisa mendaftarkan
  sentuhan tak sengaja sebagai klik dan Enter bisa terkirim dari riwayat perintah,
  tapi tidak ada yang mengetik satu kata tertentu tanpa maksud;
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


def test_dua_target_terpisah():
    """`reset-data` melihat, `reset-data-fresh` menghapus."""
    assert "\nreset-data:\n" in MAKEFILE
    assert "\nreset-data-fresh:\n" in MAKEFILE


def test_target_yang_dilihat_tidak_menghapus_apa_pun():
    """Penjaga utama: mengetik `make reset-data` tidak boleh menghapus.

    Nama yang mirip adalah cara paling mudah kehilangan data karena salah ketik,
    jadi yang bernama pendek justru yang aman.
    """
    blok = _target("reset-data")
    assert "rm -rf" not in blok, "target lihat-saja ikut menghapus"
    assert "down" not in blok, "target lihat-saja mematikan container"


def test_yang_menghapus_minta_konfirmasi_diketik():
    """Bukan y/n: satu huruf bisa terkirim dari riwayat perintah atau sentuhan
    tak sengaja. Pola yang sama dipakai Uji PLC di konsol."""
    blok = _target("reset-data-fresh")
    assert "read jawab" in blok, "tidak ada konfirmasi"
    assert "HAPUS" in blok, "konfirmasinya bukan kata tertentu"
    # Batal harus menghentikan target, bukan cuma mencetak pesan.
    assert "exit 1" in blok, "jawaban salah tidak membatalkan"
    # Dan `rm -rf` harus SESUDAH pembacaan jawaban.
    assert blok.index("read jawab") < blok.index("rm -rf")


def test_container_dimatikan_sebelum_berkas_dihapus():
    """SQLite dibuka tiga line + konsol. Menghapus WAL di bawah proses yang
    hidup meninggalkan basis data separuh jadi, bukan basis data kosong."""
    blok = _target("reset-data-fresh")
    posisi_down = blok.find("down")
    posisi_rm = blok.find("rm -rf")
    assert posisi_down != -1, "container tidak dimatikan dulu"
    assert posisi_down < posisi_rm, "berkas dihapus sebelum container mati"


def test_dua_folder_dihapus_bersamaan():
    """`artifacts/` tanpa `state/` meninggalkan foto yatim: retensi menemukan
    pekerjaan lewat manifest di `state/`, jadi foto tanpa manifest tidak pernah
    dibersihkan dan disk terisi sampai grading berhenti menyimpan."""
    blok = _target("reset-data-fresh")
    baris = next(b for b in blok.splitlines() if "rm -rf" in b)
    assert "artifacts" in baris and "state" in baris, f"cuma satu folder: {baris.strip()}"


def test_folder_dibuat_lagi_supaya_line_bisa_start():
    """Tanpa ini `docker compose up` membuat folder milik root, dan line gagal
    menulis dengan galat permission yang tidak menyebut sebabnya."""
    assert "mkdir -p" in _target("reset-data-fresh")


def test_peringatan_menyebut_akun_yang_hilang_dan_yang_kembali():
    """Bedanya penting dan mudah salah: dua akun bawaan image dibuat ulang
    sendiri oleh `seed_default_accounts` saat konsol start, jadi layar tetap bisa
    dibuka. Yang TIDAK kembali cuma akun buatan `make operator`.

    Peringatan yang menulis "akun operator hilang" begitu saja membuat orang
    mengira konsolnya terkunci dan tidak berani menjalankannya.
    """
    blok = _target("reset-data")
    assert "make operator" in blok, "tidak menyebut akun mana yang benar-benar hilang"
    assert re.search(r"[Bb]awaan", blok), "tidak menyebut akun bawaan yang kembali sendiri"


def test_pesan_akhir_tidak_menyuruh_bikin_akun_yang_sudah_ada():
    """Sesudah reset, `make start` saja sudah cukup untuk bisa masuk."""
    blok = _target("reset-data-fresh")
    assert "make start" in blok
