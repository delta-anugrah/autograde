"""Pemeriksa seluruh `<script>` konsol (batch 4.3): menangkap yang tidak ditangkap test ekstraksi.

Test konsol lain menyalin satu fungsi lalu menjalankannya; syntax error di luar fungsi itu
membuat browser menolak SELURUH skrip (layar kosong) sementara semua test tetap hijau.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from cek_skrip_konsol import (
    LOLOS,
    RUSAK,
    TIDAK_BISA_DIPERIKSA,
    BlokSkrip,
    blok_js,
    main,
)

AKAR = Path(__file__).resolve().parents[2]
KONSOL = AKAR / "src" / "palmgrade" / "static" / "console.html"
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (langkah CI node --check tetap wajib)")


def _tulis(tmp_path: Path, html: str) -> Path:
    berkas = tmp_path / "halaman.html"
    berkas.write_text(html, encoding="utf-8")
    return berkas


def _baris_tag_skrip(teks: str) -> int:
    return next(i for i, baris in enumerate(teks.splitlines(), start=1) if baris.strip() == "<script>")


# ── ekstraksi, tanpa node ───────────────────────────────────────────────────


def test_blok_json_dan_src_dilewati_tapi_nomornya_tetap_dihitung():
    html = (
        "<html><head>\n"
        '<script type="application/json">{bukan: js,,}</script>\n'
        '<script src="luar.js"></script>\n'
        "</head><body>\n"
        "<script>\nconst a = 1;\n</script>\n"
        "</body></html>\n"
    )
    blok = blok_js(html)
    assert [(b.nomor, b.baris_tag, b.modul) for b in blok] == [(3, 5, False)]
    assert blok[0].isi == "\nconst a = 1;\n"


def test_tipe_javascript_eksplisit_dan_modul_ikut_diperiksa():
    html = (
        '<script type="text/javascript">var a;</script>\n'
        '<script type="Application/JavaScript">var b;</script>\n'
        '<script type="module">export const c = 1;</script>\n'
        '<script type="text/template"><div>{{x}}</div></script>\n'
    )
    assert [(b.nomor, b.modul) for b in blok_js(html)] == [(1, False), (2, False), (3, True)]


def test_baris_html_dihitung_dari_penutup_tag_yang_terbelah_beberapa_baris():
    html = '<p>satu</p>\n<script\n  data-x="1"\n>\nconst a = ;\n</script>\n'
    (blok,) = blok_js(html)
    assert (blok.baris_tag, blok.baris_isi) == (2, 4)
    assert blok.baris_html(2) == 5


def test_baris_html_blok_satu_baris():
    blok = BlokSkrip(nomor=1, baris_tag=10, baris_isi=10, modul=False, isi="x")
    assert blok.baris_html(1) == 10
    assert blok.baris_html(7) == 16


def test_console_html_asli_punya_blok_js():
    """Kontrol negatif: pemeriksa yang tidak menemukan satu blok pun memeriksa nol baris."""
    blok = blok_js(KONSOL.read_text(encoding="utf-8"))
    assert blok, "console.html tanpa blok <script>: pemeriksa tidak memeriksa apa pun"
    assert sum(len(b.isi.splitlines()) for b in blok) > 1000


# ── kegagalan pemeriksa = gagal, bukan lolos ────────────────────────────────


def test_tanpa_node_gagal_bukan_lolos(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "kosong"))
    assert main([str(_tulis(tmp_path, "<script>var a;</script>"))]) == TIDAK_BISA_DIPERIKSA
    assert "node tidak ada" in capsys.readouterr().err


def test_berkas_tanpa_blok_js_gagal_bukan_lolos(tmp_path, capsys):
    berkas = _tulis(tmp_path, '<p>tanpa skrip</p><script type="application/json">{}</script>')
    assert main([str(berkas)]) == TIDAK_BISA_DIPERIKSA
    assert "nol blok" in capsys.readouterr().err


def test_berkas_tidak_ada_gagal(tmp_path, capsys):
    assert main([str(tmp_path / "tidak-ada.html")]) == TIDAK_BISA_DIPERIKSA
    assert "tidak ada" in capsys.readouterr().err


def test_tanpa_argumen_gagal(capsys):
    assert main([]) == TIDAK_BISA_DIPERIKSA
    assert "pemakaian" in capsys.readouterr().err


# ── parse sungguhan lewat node ──────────────────────────────────────────────


@butuh_node
def test_console_html_asli_lolos(capsys):
    assert main([str(KONSOL)]) == LOLOS
    assert "OK: " in capsys.readouterr().out


@butuh_node
def test_syntax_error_di_luar_fungsi_ketahuan_padahal_fungsinya_sehat(tmp_path, capsys):
    """Inti batch 4.3: satu baris rusak di tingkat atas `console.html` asli.

    Fungsi pertama yang diekstrak dari salinan rusak itu tetap lolos node, persis yang
    membuat semua test ekstraksi hijau; pemeriksa seluruh blok menangkapnya di baris
    HTML yang benar."""
    asli = KONSOL.read_text(encoding="utf-8")
    baris = asli.splitlines(keepends=True)
    tag = _baris_tag_skrip(asli)
    rusak = "".join(baris[:tag] + ["let rusak = ;\n"] + baris[tag:])
    berkas = _tulis(tmp_path, rusak)

    awal = rusak.index("\nfunction ", rusak.index("<script>")) + 1
    fungsi = tmp_path / "fungsi.js"
    fungsi.write_text(rusak[awal : rusak.index("\n}", awal) + 2], encoding="utf-8")
    assert subprocess.run([NODE, "--check", str(fungsi)], capture_output=True).returncode == 0

    assert main([str(berkas)]) == RUSAK
    err = capsys.readouterr().err
    assert f"blok <script> #1 (tag di baris {tag})" in err
    assert f"di baris HTML {tag + 1}" in err
    assert "SyntaxError" in err


@butuh_node
def test_blok_kedua_yang_rusak_dilaporkan_nomor_dan_barisnya(tmp_path, capsys):
    html = (
        "<html><body>\n"
        "<script>\nfunction sehat() { return 1; }\n</script>\n"
        '<script type="application/json">{"bukan": "js"}</script>\n'
        "<script>\nconst a = 1;\nif (a) {\n</script>\n"
        "</body></html>\n"
    )
    assert main([str(_tulis(tmp_path, html))]) == RUSAK
    err = capsys.readouterr().err
    assert "blok <script> #3 (tag di baris 6)" in err
    assert "#1" not in err


@butuh_node
def test_return_tingkat_atas_ditolak_seperti_browser(tmp_path, capsys):
    """`node --check` membaca berkas sebagai CommonJS dan MELOLOSKAN `return` di tingkat
    atas; browser menolaknya dan seluruh skrip mati. Karena itu skrip klasik diparse
    lewat `vm.Script`."""
    isi = tmp_path / "return.js"
    isi.write_text("function a() {}\nreturn 5;\n", encoding="utf-8")
    assert subprocess.run([NODE, "--check", str(isi)], capture_output=True).returncode == 0

    html = "<script>\nfunction a() {}\nreturn 5;\n</script>\n"
    assert main([str(_tulis(tmp_path, html))]) == RUSAK
    err = capsys.readouterr().err
    assert "Illegal return statement" in err
    assert "di baris HTML 3" in err


@butuh_node
def test_modul_diparse_sebagai_modul(tmp_path, capsys):
    sehat = '<script type="module">\nimport { a } from "./a.js";\nexport const b = a;\n</script>\n'
    assert main([str(_tulis(tmp_path, sehat))]) == LOLOS
    capsys.readouterr()

    rusak = '<script type="module">\nimport { a } from "./a.js";\nexport const = a;\n</script>\n'
    assert main([str(_tulis(tmp_path, rusak))]) == RUSAK
    assert "di baris HTML 3" in capsys.readouterr().err


@butuh_node
def test_import_di_skrip_klasik_ditolak(tmp_path, capsys):
    """Browser menolak `import` di `<script>` tanpa `type="module"`."""
    html = '<script>\nimport { a } from "./a.js";\n</script>\n'
    assert main([str(_tulis(tmp_path, html))]) == RUSAK
    assert "di baris HTML 2" in capsys.readouterr().err
