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

Yang dilakukan di sini: satu fixture autouse, cakupan sesi, yang menghapus
variabel titipan `.env` SEBELUM test pertama jalan. Test yang memang butuh
sebuah variabel tetap menyetelnya sendiri lewat `monkeypatch.setenv`, seperti
sekarang — yang hilang cuma nilai yang tidak pernah diminta siapa pun.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_ENV = Path(__file__).resolve().parents[1] / ".env"


def _kunci_env() -> list[str]:
    """Nama variabel di `.env` repo ini. Berkasnya boleh tidak ada (CI)."""
    if not _ENV.is_file():
        return []
    kunci = []
    for baris in _ENV.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci.append(baris.split("=", 1)[0].strip())
    return kunci


# Disimpan saat conftest di-import, SEBELUM modul test mana pun di-import dan
# karenanya sebelum `load_dotenv` sempat jalan. Inilah environ yang asli.
_ASLI = dict(os.environ)
_TITIPAN = [k for k in _kunci_env() if k not in _ASLI]


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
