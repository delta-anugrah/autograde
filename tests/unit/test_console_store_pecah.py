"""`console_repository.py` dipecah tanpa mengubah cara memanggilnya (batch 2, 2026-09-28).

Berkas itu 1.356 baris dan batch 2 menambah query di dalamnya. Skema + migrasi pindah
ke `console_skema.py`, akun + sesi ke mixin `AkunStore`. Semua pemanggil tetap memakai
`ConsoleStore` saja.
"""
from __future__ import annotations

import sqlite3

from palmgrade.repositories.console_akun_repository import AkunStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.console_skema import siapkan_skema

METODE_AKUN = (
    "upsert_operator_manual", "upsert_operator_erp", "_upsert_operator", "operator",
    "operator_by_email", "operators", "akun_untuk_support", "has_support_account",
    "set_operator_status", "set_role", "record_login_failure", "clear_login_failures",
    "create_session", "session", "delete_session", "purge_sessions",
)
TABEL = {
    "inspections", "suppliers", "trucks", "assignments", "auto_releases", "weighings",
    "sync_state", "operators", "sesi", "grading_imports",
}


def _db(path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    return db


def _skema(path) -> list[tuple]:
    db = sqlite3.connect(str(path))
    try:
        return sorted(
            db.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
    finally:
        db.close()


def test_metode_akun_tinggal_di_mixin_dan_tetap_dipanggil_lewat_store():
    assert issubclass(ConsoleStore, AkunStore)
    for nama in METODE_AKUN:
        assert nama in vars(AkunStore), nama
        assert nama not in vars(ConsoleStore), nama
        assert callable(getattr(ConsoleStore, nama)), nama


def test_mixin_tidak_punya_konstruktor_sendiri():
    assert "__init__" not in vars(AkunStore)


def test_migrasi_tidak_lagi_method_console_store():
    for nama in ("_migrate", "_rename_indonesian_columns", "_rename_operator_role",
                 "_drop_pin_era_operators", "_RENAMED_COLUMNS"):
        assert not hasattr(ConsoleStore, nama), nama


def test_siapkan_skema_membuat_semua_tabel_dan_aman_diulang(tmp_path):
    db = _db(tmp_path / "console.db")

    siapkan_skema(db)
    siapkan_skema(db)

    tabel = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABEL <= tabel


def test_skema_sama_persis_dengan_yang_dibuat_console_store(tmp_path):
    """Pemindahan tidak boleh mengubah satu kolom atau indeks pun."""
    ConsoleStore(tmp_path / "lewat_store.db")
    siapkan_skema(_db(tmp_path / "langsung.db"))

    assert _skema(tmp_path / "lewat_store.db") == _skema(tmp_path / "langsung.db")
