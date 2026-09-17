"""Data demo tidak boleh berstempel di masa depan.

Tab Grading dan tabel Timbangan urut waktu terbaru. Seeder dulu menyebar kunjungan
dari 07:00 sampai 17:00 tanpa memandang jam berapa sekarang, jadi demo yang
dijalankan siang hari menanam baris di jam yang belum lewat. Selama baris itu ada,
dia selalu berada DI ATAS janjang yang baru saja digrading — tab Grading terlihat
beku padahal real-time-nya jalan, dan itu memakan waktu satu sesi untuk dilacak.

Hari-hari lampau tetap terisi penuh: yang dibatasi cuma hari ini.

Jalan tanpa cv2/numpy — yang diuji cuma stempel waktunya.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from palmgrade.repositories.console_repository import ConsoleStore

AKAR = pathlib.Path(__file__).resolve().parents[2]
WIB = ZoneInfo("Asia/Jakarta")


def _muat_seeder():
    jalur = AKAR / "scripts" / "seed-console-demo.py"
    spec = importlib.util.spec_from_file_location("seed_console_demo", jalur)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def seeder():
    return _muat_seeder()


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


def _stempel(store: ConsoleStore, tabel: str, kolom: str) -> list[datetime]:
    with store._lock:  # noqa: SLF001 — dev tool; tidak ada API baca massal
        rows = store._db.execute(  # noqa: SLF001
            f"SELECT {kolom} FROM {tabel} WHERE {kolom} IS NOT NULL"
        ).fetchall()
    return [datetime.fromisoformat(r[0]) for r in rows]


def test_tidak_ada_janjang_berstempel_masa_depan(seeder, store, tmp_path):
    """Yang bikin tab Grading terlihat beku."""
    seeder.seed_visits(store, WIB, tmp_path, {}, days=1)
    sekarang = datetime.now(WIB)

    masa_depan = [t for t in _stempel(store, "inspections", "timestamp") if t > sekarang]

    assert not masa_depan, f"{len(masa_depan)} janjang demo berstempel setelah {sekarang}"


def test_tidak_ada_timbangan_berstempel_masa_depan(seeder, store, tmp_path):
    """`exited_at` = `entered_at` + 1 jam, jadi ekornya juga harus muat."""
    seeder.seed_visits(store, WIB, tmp_path, {}, days=1)
    sekarang = datetime.now(WIB)

    for kolom in ("entered_at", "exited_at"):
        masa_depan = [t for t in _stempel(store, "weighings", kolom) if t > sekarang]
        assert not masa_depan, f"{len(masa_depan)} timbangan demo {kolom} di masa depan"


def test_hari_lampau_tetap_terisi_penuh(seeder, store, tmp_path):
    """Pembatasan hanya berlaku untuk hari ini — riwayat tidak boleh ikut menyusut."""
    seeder.seed_visits(store, WIB, tmp_path, {}, days=3)
    kemarin = (datetime.now(WIB) - timedelta(days=1)).strftime("%Y-%m-%d")

    with store._lock:  # noqa: SLF001
        n = store._db.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM weighings WHERE work_date = ?", (kemarin,)
        ).fetchone()[0]

    assert n >= seeder.VISITS_PER_DAY[0], "riwayat kemarin ikut terpotong"


@pytest.mark.parametrize("jam", [0, 3, 6, 7, 8, 12, 18, 23])
def test_tidak_bocor_pada_jam_berapa_pun(seeder, store, tmp_path, monkeypatch, jam):
    """Versi pertama perbaikan ini LOLOS tes di atas hanya karena kebetulan
    dijalankan siang. Demo yang dijalankan subuh tidak punya ruang di hari kerjanya
    sendiri (07:00 belum lewat), dan baris demo tetap bocor ke masa depan.
    """
    palsu = datetime(2026, 9, 17, jam, 0, tzinfo=WIB)

    class JamPalsu(datetime):
        @classmethod
        def now(cls, tz=None):
            return palsu

    monkeypatch.setattr(seeder, "datetime", JamPalsu)
    seeder.seed_visits(store, WIB, tmp_path, {}, days=1)

    for tabel, kolom in (("inspections", "timestamp"), ("weighings", "exited_at")):
        masa_depan = [t for t in _stempel(store, tabel, kolom) if t > palsu]
        assert not masa_depan, f"jam {jam:02d}: {len(masa_depan)} baris {tabel}.{kolom} di masa depan"


def test_hari_ini_tetap_menghasilkan_sesuatu(seeder, store, tmp_path):
    """Demo yang dijalankan siang hari harus tetap punya kunjungan hari ini —
    kalau tidak, layar kosong dan demo-nya tidak menunjukkan apa-apa."""
    seeder.seed_visits(store, WIB, tmp_path, {}, days=1)

    assert _stempel(store, "inspections", "timestamp"), "hari ini nol janjang"
