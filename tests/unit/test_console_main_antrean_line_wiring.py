"""`console_main.py` memasang router Antrean line; `console_deps` memberinya klien line konsol.

`create_console_app()` tidak boleh dinyalakan di test (menyentuh `state/console.db`
milik developer), jadi dijaga sebagai teks, seperti `test_main_bahaya_wiring.py`.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


def test_router_antrean_line_dipasang():
    teks = (SRC / "console_main.py").read_text()
    assert "from .routes.console_antrean_line import router as antrean_line_router" in teks
    assert "app.include_router(antrean_line_router)" in teks


def test_pantau_memakai_klien_dan_line_konsol_yang_sama():
    deps = (SRC / "routes" / "console_deps.py").read_text()
    blok = deps.split("def get_pantau_antrean_line()", 1)[1].split("\ndef ", 1)[0]
    assert "PantauAntreanLine(service.line_client, service.lines)" in blok
