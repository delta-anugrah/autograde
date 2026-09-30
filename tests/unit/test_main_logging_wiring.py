"""`create_app()` memasang logging line dengan konteks, zona, dan level, dijaga sebagai teks.

`main.py` menarik torch, jadi `create_app()` tidak bisa dinyalakan di CI. Yang salah
di sini gagal senyap atau mematikan boot: tanpa argumen `configure_logging` melempar
TypeError dan ketiga line mati; tanpa `settings` lebih dulu, konteksnya tidak ada.
"""
from __future__ import annotations

import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "main.py"


def _badan_create_app() -> list[ast.stmt]:
    pohon = ast.parse(MAIN.read_text(encoding="utf-8"))
    [fungsi] = [n for n in pohon.body if isinstance(n, ast.FunctionDef) and n.name == "create_app"]
    return fungsi.body


def test_settings_dibaca_lalu_logging_dipasang_paling_awal():
    pertama, kedua = _badan_create_app()[:2]
    assert ast.unparse(pertama) == "settings = get_settings()"
    assert isinstance(kedua, ast.Expr) and isinstance(kedua.value, ast.Call)
    assert ast.unparse(kedua.value.func) == "configure_logging"


def test_logging_line_membawa_kode_line_zona_dan_level():
    kedua = _badan_create_app()[1]
    panggilan = kedua.value
    assert panggilan.args == []
    argumen = {k.arg: ast.unparse(k.value) for k in panggilan.keywords}
    assert argumen == {
        "konteks": "settings.line_code",
        "zona": "settings.factory_tz",
        "level": "settings.log_level",
    }
