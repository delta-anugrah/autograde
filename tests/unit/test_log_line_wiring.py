"""Perakitan log line (batch 3.2) di `main.py`, dijaga sebagai TEKS dan AST (pola
`test_ai_mati_wiring.py`): `main.py` menarik torch dan tidak bisa dinyalakan di CI.

Yang gagal senyap kalau salah: handler dipasang sesudah lifespan (galat boot hilang),
router memakai store lain dari handler (tab Log kosong walau line menulis),
`/internal/log` ikut ditutup gerbang lisensi tepat saat line berhenti, atau antrean
log tidak dikuras sebelum `os._exit` restart dan hapus data dari konsol (pesan
terakhir line sebelum keluar hilang).
"""
from __future__ import annotations

import ast
from pathlib import Path

from palmgrade.license.guard import _ALWAYS_ALLOWED

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text(encoding="utf-8")
CREATE_APP = MAIN.split("def create_app() -> FastAPI:", 1)[1]
SEBELUM_LIFESPAN = CREATE_APP.split("async def lifespan(app: FastAPI):", 1)[0]


def _impor_tingkat_modul() -> set[tuple[str, str, str]]:
    """(modul, nama, alias) tiap `from .x import y as z` di badan modul, bukan di fungsi."""
    return {
        (n.module or "", nama.name, nama.asname or nama.name)
        for n in ast.parse(MAIN).body
        if isinstance(n, ast.ImportFrom) and n.level == 1
        for nama in n.names
    }


def _panggilan_di_create_app(nama: str) -> list[ast.Call]:
    fungsi = next(
        n for n in ast.parse(MAIN).body if isinstance(n, ast.FunctionDef) and n.name == "create_app"
    )
    return [
        n for n in ast.walk(fungsi)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == nama
    ]


def test_impor_perakitan_log_line_di_tingkat_modul():
    impor = _impor_tingkat_modul()
    assert ("services.antrean_log_line", "pasang_penulis_log_line", "pasang_penulis_log_line") in impor
    assert ("routes.internal_log", "buat_router", "buat_router_log") in impor


def test_log_line_dipasang_di_create_app_sebelum_lifespan():
    assert "penulis_log = pasang_penulis_log_line(get_folder_db_line())" in SEBELUM_LIFESPAN
    assert "log_line = penulis_log.store if penulis_log is not None else None" in SEBELUM_LIFESPAN
    assert SEBELUM_LIFESPAN.index("configure_logging(") < SEBELUM_LIFESPAN.index("pasang_penulis_log_line(")
    (panggilan,) = _panggilan_di_create_app("pasang_penulis_log_line")
    assert [ast.unparse(a) for a in panggilan.args] == ["get_folder_db_line()"]
    assert not panggilan.keywords


def test_antrean_log_dikuras_sebelum_os_exit_restart_dan_hapus_data():
    """`penutup_line.keluar_nanti` memanggil `os._exit`, yang melewati `atexit`."""
    assert "if penulis_log is not None:\n        penutup.sebelum_keluar(penulis_log.hentikan)" in SEBELUM_LIFESPAN
    assert SEBELUM_LIFESPAN.index("penutup = get_penutup_line()") < SEBELUM_LIFESPAN.index(
        "penutup.sebelum_keluar("
    )


def test_router_log_memakai_store_yang_sama_dengan_handler():
    assert "app.include_router(buat_router_log(settings=get_settings, store=lambda: log_line))" in CREATE_APP
    (panggilan,) = _panggilan_di_create_app("buat_router_log")
    kata_kunci = {k.arg: ast.unparse(k.value) for k in panggilan.keywords}
    assert kata_kunci == {"settings": "get_settings", "store": "lambda: log_line"}


def test_rute_log_tetap_terbuka_saat_lisensi_habis():
    assert "/internal/log" in _ALWAYS_ALLOWED
