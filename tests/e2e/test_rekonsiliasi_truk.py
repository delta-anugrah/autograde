"""End-to-end OPS-2: `make rekonsiliasi-truk` against a real database file.

The unit tests call `rekonsiliasi_truk()` directly. What they cannot cover is the
part the person installing a mill PC actually touches: the Makefile target, the
`TULIS` flag, the exit codes, and the fact that look-only really writes nothing to
a file on disk. That is what runs here — a real subprocess, a real SQLite file, no
fakes and no in-process shortcuts.

Not skipped and needs no services: the script's only dependency is a database path,
which the fixture builds. It is the one E2E in this suite that can run anywhere,
and it is kept out of `tests/unit` deliberately — it spawns processes and touches
the filesystem, which the unit suite must not do.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore

REPO = Path(__file__).resolve().parents[2]
SKRIP = REPO / "scripts" / "rekonsiliasi-truk.py"

# The shape palmgrade-api leaves behind: uuid4, unrelated to the plate.
ID_LAMA = "7f3a9b21-0000-4000-8000-00000000000{}"


def _jalankan(db: Path, *argumen: str) -> subprocess.CompletedProcess:
    """The script as the installer runs it: its own process, its own interpreter."""
    return subprocess.run(
        [sys.executable, str(SKRIP), "--db", str(db), *argumen],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        cwd=str(REPO),
    )


@pytest.fixture
def db_pabrik(tmp_path) -> Path:
    """A database shaped like a mill PC that has been running on palmgrade-api.

    Four trucks with random ids, one of them already twinned by an ERP pull, plus
    one row whose plate is unreadable — the case that must not abort the rest.
    """
    path = tmp_path / "console.db"
    store = ConsoleStore(path)
    plat = ["BE 4412 OFL", "be-9012-tt", "BG 1234 AB", "BE 7788 QQ"]

    for i, p in enumerate(plat, 1):
        tid = ID_LAMA.format(i)
        store.upsert_truck({"id": tid, "plate_number": p, "status": "active"})
        store.upsert_weighing(
            {
                "id": f"w-{i}",
                "ref": None,
                "plate_number": p,
                "plate_norm": p.replace(" ", "").replace("-", "").upper(),
                "truck_id": tid,
                "tanggal_kerja": "2026-09-15",
                "bruto_kg": 13000.0,
                "tara_kg": 5000.0,
                "neto_kg": 8000.0,
                "waktu_masuk": "2026-09-15T08:00:00+07:00",
                "waktu_keluar": "2026-09-15T09:00:00+07:00",
            }
        )

    # One truck already pulled from AutoERP: this is the twin.
    store.upsert_truck(
        {
            "id": truck_id_for("BE 4412 OFL"),
            "plate_number": "BE 4412 OFL",
            "status": "active",
            "erp_name": "TRK-0001",
        }
    )
    store.upsert_truck({"id": "rusak-1", "plate_number": None, "status": "active"})
    return path


def _neto(db: Path) -> float:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COALESCE(SUM(neto_kg), 0) FROM weighings").fetchone()[0]
    finally:
        con.close()


def _menggantung(db: Path) -> dict[str, int]:
    """Rows pointing at a truck id that no longer exists — the failure that empties
    the recap without any error anywhere."""
    con = sqlite3.connect(db)
    try:
        return {
            t: con.execute(
                f"SELECT COUNT(*) FROM {t} WHERE truck_id IS NOT NULL"
                "  AND truck_id NOT IN (SELECT id FROM trucks)"
            ).fetchone()[0]
            for t in ("weighings", "inspections", "assignments")
        }
    finally:
        con.close()


def _plat_kembar(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(
            """SELECT COUNT(*) FROM (
                   SELECT 1 FROM trucks WHERE plate_number IS NOT NULL
                   GROUP BY UPPER(REPLACE(REPLACE(plate_number, ' ', ''), '-', ''))
                   HAVING COUNT(*) > 1)"""
        ).fetchone()[0]
    finally:
        con.close()


def test_mode_lihat_tidak_menyentuh_berkas(db_pabrik):
    """Dijalankan dulu untuk dibaca sebelum diputuskan. Kalau mode ini ikut menulis,
    tidak ada cara aman memeriksa hasilnya sebelum mengubah data pabrik."""
    sebelum = db_pabrik.read_bytes()

    hasil = _jalankan(db_pabrik)

    assert hasil.returncode == 0, hasil.stderr
    assert "lihat saja" in hasil.stdout
    assert db_pabrik.read_bytes() == sebelum, "berkas berubah padahal mode lihat"


def test_laporannya_menyebut_plat_supaya_bisa_dicocokkan_orang(db_pabrik):
    """Dibaca di terminal PC pabrik sambil memegang catatan truk."""
    hasil = _jalankan(db_pabrik)

    assert "BE 4412 OFL" in hasil.stdout
    assert "PERLU DIPERIKSA ORANG" in hasil.stdout
    assert "rusak-1" in hasil.stdout


def test_tonase_tidak_berubah_sedikit_pun(db_pabrik):
    """Ini seluruh taruhannya: neto adalah angka yang dibayar ke petani. Truk boleh
    digabung, tonase tidak boleh bergeser satu kilo pun."""
    sebelum = _neto(db_pabrik)

    _jalankan(db_pabrik, "--tulis")

    assert _neto(db_pabrik) == sebelum == 32000.0


def test_tidak_ada_baris_yang_menggantung_sesudahnya(db_pabrik):
    """`truck_id` ada di tiga tabel. Kelewat satu = barisnya hilang dari rekap tanpa
    error di mana pun — kegagalan yang paling sulit terlihat."""
    _jalankan(db_pabrik, "--tulis")

    assert _menggantung(db_pabrik) == {"weighings": 0, "inspections": 0, "assignments": 0}


def test_truk_kembar_hilang_dan_erp_name_selamat(db_pabrik):
    assert _plat_kembar(db_pabrik) == 1

    _jalankan(db_pabrik, "--tulis")

    assert _plat_kembar(db_pabrik) == 0
    con = sqlite3.connect(db_pabrik)
    try:
        assert con.execute("SELECT COUNT(*) FROM trucks WHERE erp_name='TRK-0001'").fetchone()[0] == 1
    finally:
        con.close()


def test_dijalankan_dua_kali_aman(db_pabrik):
    """Yang menjalankannya sedang mengerjakan sepuluh hal lain dan sering ragu apakah
    tadi sudah jalan."""
    _jalankan(db_pabrik, "--tulis")
    setelah_pertama = _neto(db_pabrik)

    kedua = _jalankan(db_pabrik, "--tulis")

    assert "digabung : 0" in kedua.stdout
    assert "dipindah : 0" in kedua.stdout
    assert _neto(db_pabrik) == setelah_pertama


def test_kode_keluar_menandai_yang_butuh_orang(db_pabrik):
    """Bukan kegagalan — sisanya sudah dibetulkan. Tapi harus tidak-nol, kalau tidak
    daftar pengecualiannya lewat begitu saja di skrip pemasangan."""
    assert _jalankan(db_pabrik, "--tulis").returncode == 2


def test_database_yang_tidak_ada_ditolak_bukan_dibuat(tmp_path):
    """Salah ketik path tidak boleh menghasilkan database kosong yang terbaca seperti
    pabrik tanpa truk."""
    hilang = tmp_path / "tidak-ada.db"

    hasil = _jalankan(hilang)

    assert hasil.returncode == 1
    assert not hilang.exists(), "skrip membuat database baru dari path yang salah ketik"


def test_pc_baru_tanpa_truk_tidak_melaporkan_apa_pun(tmp_path):
    """Pabrik baru menjalankan ini juga (checklist pasang tidak bercabang), dan hasilnya
    harus mengatakan dengan jelas bahwa tidak ada yang perlu dikerjakan."""
    kosong = tmp_path / "console.db"
    ConsoleStore(kosong)

    hasil = _jalankan(kosong)

    assert hasil.returncode == 0
    assert "Tidak ada yang perlu dibetulkan" in hasil.stdout
