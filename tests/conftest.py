"""Menjaga test tidak membaca `.env` mesin yang menjalankannya.

`main.py` dan `console_main.py` memanggil `load_dotenv()` di tingkat modul, jadi
begitu salah satunya di-import — oleh test mana pun, termasuk yang tidak peduli
konfigurasi — seluruh isi `.env` masuk ke `os.environ` proses pytest dan menetap
di sana untuk semua test sesudahnya.

Akibatnya hasil test ikut isi `.env` mesin:

- `Settings().plc_enabled` jadi `True` di laptop yang `.env`-nya `PLC_ENABLED=true`,
  padahal test menuntut default `False`.
- `UPLOAD_RETENTION_DAYS=180` di `.env` menimpa asumsi 7 hari, jadi item yang
  dimundurkan 8 hari belum lewat cutoff dan test retensi gagal.

Dua-duanya gagal HANYA kalau dijalankan bersama test lain, dan lulus kalau
dijalankan sendirian — gejala yang terbaca seperti test rapuh padahal kodenya
sehat. Di CI dua-duanya hijau karena `.env` tidak ikut di-commit, jadi cacat ini
tidak pernah terlihat di PR dan cuma menyusahkan orang yang kerja lokal.
Di worktree `.env` yang terbaca milik checkout utama; lihat tests/dotenv_mesin.py.

Yang dilakukan di sini: satu fixture autouse, cakupan sesi, yang menghapus
variabel titipan `.env` SEBELUM test pertama jalan. Test yang memang butuh
sebuah variabel tetap menyetelnya sendiri lewat `monkeypatch.setenv`, seperti
sekarang — yang hilang cuma nilai yang tidak pernah diminta siapa pun.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv_mesin import berkas_env_leluhur, kunci_env

# `load_dotenv()` mencari `.env` mulai dari folder kode lalu NAIK (lihat
# tests/dotenv_mesin.py). Di worktree yang terbaca `.env` checkout utama, jadi
# yang dibersihkan semua `.env` di jalur itu, bukan cuma `<repo>/.env`.
_KODE = Path(__file__).resolve().parents[1] / "src" / "palmgrade"

# Disimpan saat conftest di-import, SEBELUM modul test mana pun di-import dan
# karenanya sebelum `load_dotenv` sempat jalan. Inilah environ yang asli.
_ASLI = dict(os.environ)
_TITIPAN = [k for k in kunci_env(berkas_env_leluhur(_KODE)) if k not in _ASLI]


def _bersihkan() -> None:
    for kunci in _TITIPAN:
        os.environ.pop(kunci, None)


# Sekali saat conftest dimuat: kalau `.env` sudah sempat terbaca oleh apa pun
# yang berjalan lebih dulu, nilainya dibuang sekarang.
_bersihkan()


def pytest_collection_finish(session) -> None:  # noqa: ARG001
    """Sapu lagi sesudah collection.

    Collection meng-import setiap berkas test, dan sebagian menarik `main` atau
    `console_main` — yang memanggil `load_dotenv()` di tingkat modul. Jadi
    environ bisa sudah terisi ulang di sini, sebelum test pertama jalan.
    """
    _bersihkan()


@pytest.fixture(autouse=True)
def tanpa_dotenv_mesin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setiap test mulai tanpa nilai titipan `.env`.

    Cakupannya per-test, bukan per-sesi, karena `load_dotenv` bisa terpanggil
    lagi di tengah jalan: sebuah test yang me-reload modul atau mengimpor
    `main` untuk pertama kalinya akan mengisi environ lagi, dan test SESUDAHNYA
    yang menanggung akibatnya.

    `monkeypatch.delenv` dipakai supaya penghapusan ini dibatalkan otomatis di
    akhir test — test yang memang sengaja menyetel salah satu variabel lewat
    `monkeypatch.setenv` tetap bekerja seperti biasa.
    """
    for kunci in _TITIPAN:
        monkeypatch.delenv(kunci, raising=False)
