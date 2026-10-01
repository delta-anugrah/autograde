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

import atexit
import logging
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from dotenv_mesin import berkas_env_leluhur, kunci_env

import palmgrade.core.config as config_palmgrade
import palmgrade.core.logging as logging_palmgrade

# `load_dotenv()` mencari `.env` mulai dari folder kode lalu NAIK (lihat
# tests/dotenv_mesin.py). Di worktree yang terbaca `.env` checkout utama, jadi
# yang dibersihkan semua `.env` di jalur itu, bukan cuma `<repo>/.env`.
_KODE = Path(__file__).resolve().parents[1] / "src" / "palmgrade"


#: Akar repo yang dipakai `Settings()` tanpa `repo_root` titipan.
AKAR_REPO = Path(config_palmgrade.__file__).resolve().parents[3]
#: Pengganti `<repo>/state` dan `<repo>/artifacts` selama sesi test.
DATA_SESI = Path(tempfile.mkdtemp(prefix="autograde-test-data-"))
atexit.register(shutil.rmtree, DATA_SESI, ignore_errors=True)
_STATE_DIR_ASLI = config_palmgrade.Settings.state_dir
_ARTIFACTS_DIR_ASLI = config_palmgrade.Settings.artifacts_dir


def _dialihkan(asli: property, env: str, nama: str) -> property:
    """Folder data bawaan repo diganti folder sesi; yang lain dibiarkan apa adanya.

    Tanpa ini, collection sudah menulis ke `state/` checkout yang menjalankan test:
    `console_main` membangun `app` di tingkat modul (console.db, erp_outbox.db,
    manifest_outbox.db), dan layanan `lru_cache` yang belum ditimpa test membuka
    log_kejadian.db. Di checkout utama itu `state/` dev milik orang sungguhan.

    Sengaja bukan `STATE_DIR`/`ARTIFACTS_DIR` di environ: puluhan test mengisolasi
    diri dengan `replace(Settings(), repo_root=tmp_path)` dan mengandalkan folder data
    yang ikut `repo_root`; env global akan menyatukan semuanya di satu folder. Jadi
    yang dialihkan hanya `Settings` yang masih memakai akar repo asli dan tidak punya
    env sendiri. Test yang menguji jalur bawaan repo memakai `jalur_data_repo_asli`.
    """

    def ambil(self: config_palmgrade.Settings) -> Path:
        if self.repo_root == AKAR_REPO and not os.getenv(env, "").strip():
            return DATA_SESI / nama
        return asli.fget(self)

    return property(ambil, doc=asli.__doc__)


# Dipasang saat conftest di-import, sebelum modul test mana pun di-import.
config_palmgrade.Settings.state_dir = _dialihkan(_STATE_DIR_ASLI, "STATE_DIR", "state")
config_palmgrade.Settings.artifacts_dir = _dialihkan(_ARTIFACTS_DIR_ASLI, "ARTIFACTS_DIR", "artifacts")


@pytest.fixture
def jalur_data_repo_asli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Untuk test yang justru menguji bawaan `<repo>/state` dan `<repo>/artifacts`."""
    monkeypatch.setattr(config_palmgrade.Settings, "state_dir", _STATE_DIR_ASLI)
    monkeypatch.setattr(config_palmgrade.Settings, "artifacts_dir", _ARTIFACTS_DIR_ASLI)


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


#: Logger selain root yang diubah `configure_logging` (uvicorn diambil alih, klien
#: HTTP dibatasi WARNING).
_LOGGER_DIPASANG = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore")


@pytest.fixture(autouse=True)
def logging_dilepas_sesudah_test():
    """Setiap test berakhir tanpa pemasangan `configure_logging` yang masih aktif.

    Lifespan konsol yang GAGAL start sengaja tidak melepas logging-nya: di produksi
    itulah yang membawa traceback "Application startup failed" uvicorn ke tab Log.
    Di test, pemasangan yang tertinggal baru dilepas `configure_logging` BERIKUTNYA,
    di test lain, dan pelepasan itu memulihkan root dan uvicorn ke potret milik test
    yang sudah lewat: test sesudahnya merah atau hijau tergantung urutan.

    Handler root tidak dipulihkan dari potret: pytest memasang handler tangkapannya
    sendiri per tahap (setup/call/teardown), dan potret dari tahap setup akan
    meninggalkan handler tahap itu selamanya. `lepas()` mencabut handler yang
    dipasangnya sendiri.
    """
    root = logging.getLogger()
    level_root = root.level
    semula = {
        nama: (list(lg.handlers), list(lg.filters), lg.propagate, lg.level)
        for nama, lg in ((n, logging.getLogger(n)) for n in _LOGGER_DIPASANG)
    }
    yield
    # `_aktif` sengaja privat: produksi tidak punya alasan melepas pemasangan orang lain.
    aktif = logging_palmgrade._aktif
    if aktif is not None:
        aktif.lepas()
    root.setLevel(level_root)
    for nama, (handlers, filters, propagate, level) in semula.items():
        lg = logging.getLogger(nama)
        lg.handlers, lg.filters, lg.propagate = handlers, filters, propagate
        lg.setLevel(level)
