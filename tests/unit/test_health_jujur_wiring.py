"""Perakitan health jujur (batch 3.6 + 3.7) di tempat yang menarik torch, dijaga
sebagai TEKS/AST (pola `test_ai_mati_wiring.py`): `main.py` dan
`internal_controller.line_status` tidak bisa dinyalakan di CI.

Yang gagal senyap kalau salah: pemantau disk tidak pernah dipasang (Diagnostik
dan alert disk kosong selamanya), atau `/internal/status` tidak membawa `disk`.

Fix round 1 (review): parsing `main.py` sebagai teks lewat `LIFESPAN.index(...)`
lolos walau `from .services.pemantau_disk import PemantauDisk` dihapus (kwarg
konstruktor berganti nama juga lolos) — 3 stream mengubah blok import `main.py`
yang sama, dan merge bisa membuang satu baris impor tanpa CI menangkapnya
(`main.py` di luar ruff CI, semua test yang mengimpornya di-skip tanpa torch).
Di sini dipakai `ast`: assert ada `ImportFrom` level-1 bernama `PemantauDisk`
dari `services.pemantau_disk`, DAN ada pemanggilan `PemantauDisk(...)` di dalam
`lifespan` yang argumen keyword-nya benar-benar cocok dengan tanda tangan kelas
itu (`inspect.signature(...).bind`), bukan cuma potongan teks di antara dua
tanda kurung.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from palmgrade.schemas.internal_schema import LineStatusResponse
from palmgrade.services.pemantau_disk import PemantauDisk

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN_TEXT = (SRC / "main.py").read_text(encoding="utf-8")
MAIN_AST = ast.parse(MAIN_TEXT, filename="main.py")
LIFESPAN = MAIN_TEXT.split("async def lifespan(app: FastAPI):", 1)[1]


def _lifespan_func_node() -> ast.AsyncFunctionDef:
    for node in ast.walk(MAIN_AST):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node
    raise AssertionError("async def lifespan(...) not found in main.py")


def _pemantau_disk_calls(func_node: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PemantauDisk"
    ]


def test_pemantau_disk_diimpor_dari_modulnya_bukan_dihapus():
    """Deleting the import must fail this test even though the call site text
    (`PemantauDisk(...)`) is untouched — a lost import crashes every line at
    boot with CI green, since main.py imports are outside ruff's CI scope and
    every test importing main.py is skipped in CI (no torch)."""
    hits = [
        node
        for node in ast.walk(MAIN_AST)
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "services.pemantau_disk"
        and any(alias.name == "PemantauDisk" for alias in node.names)
    ]
    assert hits, "expected `from .services.pemantau_disk import PemantauDisk` in main.py"


def test_pemantau_disk_dirakit_di_lifespan_untuk_foto_dan_db():
    lifespan_node = _lifespan_func_node()
    calls = _pemantau_disk_calls(lifespan_node)
    assert calls, "expected a PemantauDisk(...) call inside lifespan()"
    call = calls[0]

    assert not call.args, "PemantauDisk is keyword-only; no positional args expected"
    # Kwarg names must actually match the constructor's signature: a renamed
    # kwarg (or a typo introduced by a merge) fails `bind`, not just "text found".
    kwargs = {kw.arg: None for kw in call.keywords if kw.arg is not None}
    inspect.signature(PemantauDisk).bind(**kwargs)
    assert {"settings", "jalur"} <= kwargs.keys()

    assert LIFESPAN.index("state = get_runtime_state()") < MAIN_TEXT.index(
        "PemantauDisk(", MAIN_TEXT.index("async def lifespan(app: FastAPI):")
    )


def test_status_line_membawa_blok_disk():
    kontrol = (SRC / "controllers" / "internal_controller.py").read_text(encoding="utf-8")
    fungsi = kontrol.split("async def line_status(", 1)[1]
    assert "disk=ringkas_disk_dari_state(state)" in fungsi


def test_skema_status_line_menerima_disk_dan_bawaannya_none():
    assert LineStatusResponse(machine_id="m", truck_id=None, ffb_source=None, piston=None).disk is None
