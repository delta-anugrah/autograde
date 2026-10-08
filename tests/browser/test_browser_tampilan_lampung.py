"""Console polish after the Lampung v1.26.0 test (owner 2026-10-08), measured in a real browser:
the scan popup is opaque and coloured per step, the Rekap filter is two tidy rows, buttons carry
icons at one height, the header controls share one height, and the log level is coloured."""

from __future__ import annotations

import pytest
from langkah import OPERATOR, SUPPORT, buka_tab, masuk
from playwright.sync_api import expect

_ISI = ('{hasil:"tersimpan", langkah:"%s", plate_number:"B 1995 SME", supplier:null, kg:null,'
        ' dummy:false, dipasang:[]}')


def _warna(halaman, js: str) -> str:
    return halaman.evaluate(f"() => {{ const el = {js}; return getComputedStyle(el).borderTopColor; }}")


def test_popup_scan_padat_dan_berwarna_per_langkah(halaman):
    masuk(halaman, OPERATOR)
    warna = {}
    for langkah in ("datang", "timbang_isi", "timbang_kosong", "keluar"):
        halaman.evaluate(f"() => tampilkanPopupScan({{ ...teksPopupScan({_ISI % langkah}), durasiMs: 0 }})")
        popup = halaman.locator("#scan-popup")
        expect(popup).to_be_visible()
        expect(popup).to_have_attribute("data-langkah", langkah)
        gaya = halaman.evaluate("""() => { const g = getComputedStyle($("scan-popup"));
            return { warna: g.backgroundColor, gambar: g.backgroundImage }; }""")
        # Opaque: a solid card colour under the step tint (the see-through one vanished over video).
        assert gaya["warna"].startswith("rgb(") or gaya["warna"].endswith(", 1)"), gaya
        assert "gradient" in gaya["gambar"], gaya
        warna[langkah] = _warna(halaman, '$("scan-popup")')
        # The same colour as the step's column on the Timbangan board.
        kolom = {"datang": "datang", "timbang_isi": "bongkar", "timbang_kosong": "kosong", "keluar": "selesai"}[langkah]
        papan = halaman.evaluate(f"""() => getComputedStyle(document.querySelector(
            '.papan-kolom[data-kolom="{kolom}"]')).getPropertyValue("--warna-tahap").trim()""")
        sendiri = halaman.evaluate("""() => getComputedStyle($("scan-popup")).getPropertyValue("--warna-tahap").trim()""")
        assert papan == sendiri, (langkah, papan, sendiri)
    assert len(set(warna.values())) == 4, warna


def test_rekap_dua_baris_tombol_satu_baris_di_kanan(halaman):
    halaman.set_viewport_size({"width": 1366, "height": 768})
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "rekap")
    tombol = halaman.locator(".riwayat-aksi button:visible")
    expect(tombol).to_have_count(3)
    kotak = [tombol.nth(i).bounding_box() for i in range(3)]
    assert len({round(k["y"]) for k in kotak}) == 1, kotak
    assert len({round(k["height"]) for k in kotak}) == 1 and kotak[0]["height"] >= 43.5, kotak
    # Same row as the Line picker, and right of it.
    line = halaman.locator("#riwayat-line .pilih-tombol").bounding_box()
    assert abs((line["y"] + line["height"]) - (kotak[0]["y"] + kotak[0]["height"])) < 1.5, (line, kotak[0])
    assert kotak[0]["x"] > line["x"] + line["width"]
    # Every action button shows its icon.
    for i in range(3):
        isi = tombol.nth(i).evaluate("(b) => getComputedStyle(b, '::before').content")
        assert isi not in ("none", "normal"), i


@pytest.mark.parametrize("lebar", [1680, 1920])
def test_reject_dan_piston_satu_baris_sama_lebar(halaman, lebar):
    halaman.set_viewport_size({"width": lebar, "height": 1050})
    masuk(halaman, OPERATOR)
    reject = halaman.locator(".card .aksi-line button.reject").first
    piston = halaman.locator(".card .aksi-line .slot-piston button").first
    expect(reject).to_be_visible()
    r, p = reject.bounding_box(), piston.bounding_box()
    assert abs(r["width"] - p["width"]) <= 1, (r, p)
    # One line of text: 52 px tall, not grown by a wrapped label.
    assert r["height"] < 60 and p["height"] < 60, (r, p)


def test_kepala_satu_tinggi_tanpa_tanggal(halaman):
    halaman.set_viewport_size({"width": 1680, "height": 1050})
    masuk(halaman, OPERATOR)
    tinggi = halaman.evaluate("""() => ["#sinkron-erp", "#sinkron-cloud", ".jam.pil", "#segarkan", "#bahasa", "#tema",
        "#menu-samping"].map((p) => Math.round(document.querySelector(p).getBoundingClientRect().height))""")
    assert len(set(tinggi)) == 1, tinggi
    assert halaman.locator("#hari-kerja").count() == 0


def test_level_log_berwarna(halaman):
    masuk(halaman, SUPPORT)
    buka_tab(halaman, "log")
    chip = halaman.locator(".log-tingkat").first
    expect(chip).to_be_visible()
    level = chip.get_attribute("data-level")
    warna = chip.evaluate("(c) => getComputedStyle(c).color")
    token = {"ERROR": "--rej", "WARNING": "--warn"}.get(level)
    if token:
        harap = halaman.evaluate(f"""() => {{ const d = document.createElement("span"); d.style.color = "var({token})";
            document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; }}""")
        assert warna == harap, (level, warna, harap)


def test_lihat_sandi_tidak_menutupi_isian(halaman):
    # Review 2026-10-08: a minimum width once made the in-field Lihat button cover the password.
    halaman.goto(halaman.url)
    tombol = halaman.locator("#gerbang-lihat")
    expect(tombol).to_be_visible()
    assert tombol.bounding_box()["width"] <= 5 * 16 + 1
