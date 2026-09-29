"""Satu urutan tutup untuk semua jalan keluar line, dijaga sebagai teks (batch 2.2).

`create_app()` dan `routes/internal.py` menarik torch, jadi tidak bisa dinyalakan
di CI. Yang dijaga di sini hal-hal yang kalau salah GAGAL SENYAP: jalan keluar
yang melewati urutan tutup (coil tertinggal ON, antrean simpan hilang), urutan
tutup yang ditulis dua kali lalu menyimpang, dan watchdog yang menghidupkan
lagi worker yang sengaja dihentikan.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text(encoding="utf-8")
LIFESPAN = MAIN.split("async def lifespan(app: FastAPI):", 1)[1].split("\n    app = FastAPI(", 1)[0]
SESUDAH_YIELD = LIFESPAN.split("\n        yield\n", 1)[1]
WATCHDOG = LIFESPAN.split("async def _watchdog()", 1)[1].split("asyncio.create_task(_watchdog())", 1)[0]
INTERNAL = (SRC / "routes" / "internal.py").read_text(encoding="utf-8")

_JALAN_KELUAR = {
    ("os", "_exit"), ("os", "kill"), ("os", "killpg"), ("os", "abort"),
    ("sys", "exit"), ("signal", "raise_signal"),
}
_BAWAAN_KELUAR = {"SystemExit", "exit", "quit"}


def _jalan_keluar_teks(teks: str) -> list[int]:
    """Baris yang bisa mengakhiri proses tanpa lewat urutan tutup.

    Mengenali `os._exit(...)` juga lewat alias (`import os as o`), lewat
    `from os import _exit`, dan `SystemExit`/`exit`/`quit` bawaan (parkiran Task 4:
    penjaga lama cuma mengenal bentuk `os._exit` harfiah).
    """
    pohon = ast.parse(teks)
    alias: dict[str, str] = {}
    temuan: list[int] = []
    for n in ast.walk(pohon):
        if isinstance(n, ast.Import):
            for nama in n.names:
                alias[nama.asname or nama.name] = nama.name
        elif isinstance(n, ast.ImportFrom) and n.module:
            temuan += [n.lineno for nama in n.names if (n.module, nama.name) in _JALAN_KELUAR]
    for n in ast.walk(pohon):
        if (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and (alias.get(n.value.id, n.value.id), n.attr) in _JALAN_KELUAR
        ) or (isinstance(n, ast.Name) and n.id in _BAWAAN_KELUAR):
            temuan.append(n.lineno)
    return sorted(set(temuan))


def _jalan_keluar(berkas: Path) -> list[int]:
    return _jalan_keluar_teks(berkas.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "teks",
    [
        "import os\nos._exit(0)",
        "import os as o\no._exit(0)",
        "from os import _exit\n_exit(0)",
        "from os import killpg\nkillpg(0, 15)",
        "import os\nos.killpg(0, 15)",
        "import sys\nsys.exit(1)",
        "raise SystemExit(0)",
        "exit(0)",
        "import signal\nsignal.raise_signal(15)",
    ],
)
def test_penjaga_mengenali_semua_bentuk_jalan_keluar(teks):
    assert _jalan_keluar_teks(teks), teks


def test_penjaga_tidak_salah_tuduh():
    assert _jalan_keluar_teks("import os\nos.path.exists('x')\nkeluar_nanti(1)") == []


def test_satu_satunya_os_exit_ada_di_penutup_line():
    """Jalan keluar baru yang memanggil `os._exit` sendiri melewati urutan tutup."""
    temuan = {
        str(berkas.relative_to(SRC)): baris
        for berkas in sorted(SRC.rglob("*.py"))
        if (baris := _jalan_keluar(berkas))
    }
    assert set(temuan) == {"services/penutup_line.py"}, temuan


def test_jadwalkan_keluar_lewat_penutup_line():
    fungsi = INTERNAL.split("def _jadwalkan_keluar(", 1)[1].split("\n@router", 1)[0]
    assert "get_penutup_line().keluar_nanti(jeda)" in fungsi


def test_lifespan_memasang_urutan_sebelum_yield_dan_menutup_sesudahnya():
    assert LIFESPAN.index("penutup.pasang(") < LIFESPAN.index("\n        yield\n")
    assert "penutup.tutup(" in SESUDAH_YIELD


def test_urutan_tutup_tidak_ditulis_dua_kali_di_lifespan():
    """Reuse, bukan salinan: langkahnya hidup di services/langkah_tutup_line.py."""
    for langkah in ("shutdown_plc_worker(", "tunggu_kosong(", ".disconnect()", "upload_scheduler.stop("):
        assert langkah not in SESUDAH_YIELD, langkah


def test_watchdog_berhenti_saat_line_menutup():
    """Perilakunya diuji di `test_pengawas_worker.py`; di sini cuma kabelnya: satu
    putaran = `awasi_sekali` dengan tanda tutup milik `PenutupLine` yang sama."""
    assert "awasi_sekali(" in WATCHDOG
    assert "sedang_menutup=lambda: penutup.sedang_menutup" in WATCHDOG
    assert "mulai=_start_worker" in WATCHDOG
