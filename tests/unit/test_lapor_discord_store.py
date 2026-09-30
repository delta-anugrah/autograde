"""`LaporDiscordStore` (batch 3.5): galat menunggu → kiriman, tanpa hilang dan tanpa ganda."""
from __future__ import annotations

import sqlite3

import pytest

from palmgrade.domain.digest_galat import BATAS_KELOMPOK_MENUNGGU, PESAN_LAIN
from palmgrade.repositories import lapor_discord_repository
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.repositories.log_serap_line import TambahGalat


class _Jam:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _susun_mentah(kelompok) -> list[str]:
    return [f"{k.jumlah}x {k.line_code or 'konsol'} {k.message}" for k in sorted(kelompok, key=lambda k: k.message)]


def test_galat_konsol_dan_line_sekelompok_per_jenis_dengan_hitungan(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    # Dua id 8+ hex yang berbeda tapi teks lain identik: `normalkan_pesan` (Task 5,
    # `domain/sidik_log.py`) menganggap keduanya id yang berganti-ganti, jadi sidik-nya
    # SAMA dan keduanya digabung satu kelompok dengan hitungan naik. Pesan yang tersimpan
    # tetap milik kejadian PERTAMA (`_antre_satu`: ON CONFLICT tidak menimpa `message`).
    store.write("ERROR", "palmgrade.x", "truk gagal assign deadbeef01", "traceback tidak ikut", now=10.0)
    store.write("ERROR", "palmgrade.x", "truk gagal assign facade0102", None, now=20.0)
    store.antre_line([TambahGalat("ERROR", "palmgrade.y", "line-2", "grab gagal", 5.0, 30.0, 7)])

    store.susun(_susun_mentah, now=100.0)

    isi = []
    while (k := store.kiriman_berikut()) is not None:
        isi.append(k.isi)
        store.tandai_terkirim(k.id, now=101.0)
    assert isi == ["7x line-2 grab gagal", "2x konsol truk gagal assign deadbeef01"]


def test_galat_beda_angka_pendek_tetap_dua_kelompok(tmp_path):
    """Pin R2: angka pendek yang berarti (dua truk berbeda) TIDAK dilebur, beda dengan
    id acak 8+ hex di atas. `normalkan_pesan` sengaja tidak menyentuh bilangan pendek."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "palmgrade.x", "truk 11 gagal", None, now=10.0)
    store.write("ERROR", "palmgrade.x", "truk 12 gagal", None, now=20.0)

    assert store.susun(_susun_mentah, now=100.0) == 2
    r = store.ringkasan()
    assert r["kiriman"] == 2


def test_susun_memindah_semuanya_dalam_satu_transaksi(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    assert store.susun(_susun_mentah, now=5.0) == 1
    assert store.tertua_masuk_at() is None
    assert store.ada_kiriman()
    assert store.ringkasan_terakhir_at() == 5.0
    assert store.susun(_susun_mentah, now=6.0) == 0


def test_susun_yang_gagal_meninggalkan_galat_menunggu(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    def _meledak(kelompok):
        raise RuntimeError("susun rusak")

    with pytest.raises(RuntimeError):
        store.susun(_meledak, now=5.0)

    assert store.tertua_masuk_at() == 1000.0
    assert not store.ada_kiriman()
    assert store.ringkasan_terakhir_at() is None


def test_antrean_selamat_sesudah_konsol_restart(tmp_path):
    """Ringkasan yang disusun saat offline terkirim sesudah restart, tidak dibuang."""
    jalur = tmp_path / "lapor.db"
    store = LaporDiscordStore(jalur, jam=_Jam())
    store.write("ERROR", "a", "sebelum restart", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    store.write("ERROR", "a", "belum disusun", None, now=3.0)

    baru = LaporDiscordStore(jalur, jam=_Jam())

    assert baru.kiriman_berikut().isi == "1x konsol sebelum restart"
    assert baru.ringkasan()["menunggu_jenis"] == 1
    assert baru.ringkasan_terakhir_at() == 2.0


def test_gagal_tetap_menyimpan_pesan_dan_mencatat_galat(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    k = store.kiriman_berikut()

    store.tandai_gagal(k.id, galat="Discord menjawab HTTP 404", status_http=404, now=3.0)
    store.tandai_gagal(k.id, galat="Discord tidak terjangkau (ConnectError)", status_http=None, now=4.0)

    ulang = store.kiriman_berikut()
    assert (ulang.id, ulang.percobaan) == (k.id, 2)
    r = store.ringkasan()
    assert (r["galat"], r["galat_at"], r["status_http"], r["kiriman"]) == (
        "Discord tidak terjangkau (ConnectError)", 4.0, None, 1,
    )


def test_terkirim_menghapus_pesan_dan_membersihkan_galat(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    k = store.kiriman_berikut()
    store.tandai_gagal(k.id, galat="HTTP 503", status_http=503, now=3.0)

    store.tandai_terkirim(k.id, now=9.0)

    r = store.ringkasan()
    assert (r["kiriman"], r["galat"], r["status_http"], r["terkirim_terakhir_at"]) == (0, None, None, 9.0)


def test_jenis_galat_terlalu_banyak_dilebur_ke_kelompok_lain_bukan_dibuang(tmp_path, monkeypatch):
    monkeypatch.setattr(lapor_discord_repository, "BATAS_KELOMPOK_MENUNGGU", 1)
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "pertama", None, now=1.0)
    store.write("ERROR", "a", "kedua", None, now=2.0)
    store.write("ERROR", "a", "ketiga", None, now=3.0)
    store.write("ERROR", "a", "pertama", None, now=4.0)  # jenis lama tetap dihitung di tempatnya

    kelompok = []
    store.susun(lambda ks: kelompok.extend(ks) or ["x"], now=5.0)

    assert sorted((k.message, k.jumlah) for k in kelompok) == [(PESAN_LAIN, 2), ("pertama", 2)]


def test_batas_jenis_bawaan():
    assert BATAS_KELOMPOK_MENUNGGU == 500


def test_berkas_memakai_wal(tmp_path):
    LaporDiscordStore(tmp_path / "lapor.db")
    db = sqlite3.connect(str(tmp_path / "lapor.db"))
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
