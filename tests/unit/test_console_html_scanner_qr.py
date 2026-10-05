"""Scanner QR switch on the screen (2026-10-05): the four QR fields ship `hidden`, the
2 s poll shows them when support turned the switch on."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text(
    encoding="utf-8"
)
EMPAT = ("scan-datang", "scan-plat", "scan-keluar", "scan-pergi")


def _fungsi(nama: str) -> str:
    mulai = re.search(rf"(async )?function {nama}\(", HTML).start()
    return HTML[mulai : HTML.index("\n}\n", mulai)]


def test_daftar_kolom_scan_berisi_keempatnya():
    daftar = re.search(r"const KOLOM_SCAN = \[([^\]]*)\]", HTML)
    assert daftar, "KOLOM_SCAN hilang"
    assert re.findall(r'"([^"]+)"', daftar.group(1)) == list(EMPAT)


def test_polling_menampilkan_kolom_dan_server_lama_berarti_mati():
    # `=== true`: a server older than the screen has no field, and that must read as off.
    assert "tampilkanKolomScan(s.scanner_qr === true)" in _fungsi("refresh")


def test_hidden_cuma_ditulis_kalau_berubah():
    # F9: writing the same value every 2 s is noise, and a re-hide mid-scan loses the input.
    assert "if (el.hidden !== !aktif)" in _fungsi("tampilkanKolomScan")


def test_setelan_punya_saklar_dan_tombol_simpan_sendiri():
    assert '<input id="set-scanner" type="checkbox">' in HTML
    assert 'id="set-scanner-simpan"' in HTML
    assert '"/api/console/dev/scanner-qr"' in _fungsi("muatScanner")
    assert "await muatScanner();" in HTML
    # Its own Settings sub-tab and form, so it is hidden with the other parts.
    assert 'scanner: "setform-scanner"' in HTML


def test_simpan_scanner_lewat_denganSibuk_dan_toast():
    mulai = HTML.index('$("set-scanner-simpan").addEventListener')
    blok = HTML[mulai : HTML.index("}));", mulai)]
    assert "denganSibuk(" in blok and 'toastSukses(t("scannerTersimpan"))' in blok


def test_kata_layar_ada_di_dua_bahasa():
    for kunci in ("grupScanner", "labelScanner", "bantuScanner", "btnSimpanScanner", "scannerTersimpan"):
        assert len(re.findall(rf"\b{kunci}:", HTML)) == 2, kunci
