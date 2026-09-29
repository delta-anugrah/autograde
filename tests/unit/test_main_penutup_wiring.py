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

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text(encoding="utf-8")
LIFESPAN = MAIN.split("async def lifespan(app: FastAPI):", 1)[1].split("\n    app = FastAPI(", 1)[0]
SESUDAH_YIELD = LIFESPAN.split("\n        yield\n", 1)[1]
WATCHDOG = LIFESPAN.split("async def _watchdog()", 1)[1].split("asyncio.create_task(_watchdog())", 1)[0]
INTERNAL = (SRC / "routes" / "internal.py").read_text(encoding="utf-8")

_JALAN_KELUAR = {("os", "_exit"), ("sys", "exit"), ("os", "kill"), ("os", "abort")}


def _jalan_keluar(berkas: Path) -> list[int]:
    pohon = ast.parse(berkas.read_text(encoding="utf-8"))
    return [
        n.lineno
        for n in ast.walk(pohon)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and (n.value.id, n.attr) in _JALAN_KELUAR
    ]


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
    """Diperiksa SESUDAH thread terlihat mati dan SEBELUM dihidupkan lagi.

    Urutan itu yang menutup celahnya: thread yang sudah mati saat tanda tutup
    masih padam memang mati sendiri (crash), bukan dihentikan urutan tutup, jadi
    boleh dihidupkan lagi. Diperiksa sekali di awal putaran saja masih
    menyisakan celah: urutan tutup bisa mulai dan menghentikan penulis di antara
    pemeriksaan itu dan `_start_worker`.
    """
    assert "penutup.sedang_menutup" in WATCHDOG
    assert (
        WATCHDOG.index("thread.is_alive()")
        < WATCHDOG.index("penutup.sedang_menutup")
        < WATCHDOG.index("_start_worker(")
    )
