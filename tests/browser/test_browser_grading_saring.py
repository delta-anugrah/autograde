"""Grading tab (batch 5.10, 5.12): filter by line and truck, small photos in the table,
the full one in the dialog.

`/api/console/history` is answered by the test (`page.route`), so the rows do not depend on
the hour the suite runs at; the requests the screen sends are what is checked.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from langkah import OPERATOR, kamus, masuk
from playwright.sync_api import expect

# A 1x1 PNG: a real picture the browser decodes, from no server at all.
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _baris(nomor: int, line: str, *, thumb: str | None) -> dict:
    return {"timestamp": f"2026-10-05T08:0{nomor}:00+07:00", "line_code": line, "plate_number": "BE 1 AA",
            "source_label": "Internal", "ripeness_status": "ACC", "grade_class": "Ripe",
            "image_url": PNG + f"#penuh{nomor}", "thumb_url": thumb}


def _jawab_history(halaman, items, *, total: int | None = None) -> list[dict]:
    """`total` larger than the rows makes a pager with more than one page."""
    diminta: list[dict] = []

    def jawab(route):
        q = parse_qs(urlsplit(route.request.url).query)
        diminta.append({k: v[0] for k, v in q.items()})
        isi = [r for r in items if not q.get("line_code") or r["line_code"] == q["line_code"][0]]
        route.fulfill(json={"work_date": "2026-10-05", "items": isi, "total": total or len(isi)})

    halaman.route("**/api/console/history*", jawab)
    return diminta


def test_the_line_filter_asks_the_server_and_page_one_follows(halaman):
    diminta = _jawab_history(
        halaman, [_baris(1, "line-1", thumb=PNG + "#kecil1"), _baris(2, "line-2", thumb=PNG + "#kecil2")], total=60
    )
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#recent tr")).to_have_count(2)
    halaman.click("#grading-next")
    expect(halaman.locator("#grading-rentang")).to_contain_text("26")

    pilih = halaman.locator("#grading-line")
    pilih.locator(".pilih-tombol").click()
    expect(pilih.locator('[role="option"]').first).to_have_text(kamus(halaman, "saringSemuaLine"))
    pilih.locator('[role="option"][data-nilai="line-2"]').click()

    expect(halaman.locator("#recent tr")).to_have_count(1)
    expect(halaman.locator("#recent td.kode-line")).to_have_text("line-2")
    # The photo strips ask four rows per line on their own (2026-10-07): read the table's.
    tabel = [d for d in diminta if d["limit"] != "4"]
    terakhir = tabel[-1]
    assert terakhir["line_code"] == "line-2" and terakhir["offset"] == "0" and "truck_id" not in terakhir
    # The 2 s poll keeps the filter.
    sebelum = len(diminta)
    halaman.evaluate("() => refresh()")
    assert any(d.get("line_code") == "line-2" and d["limit"] != "4" for d in diminta[sebelum:])


def test_the_truck_filter_lists_the_trucks_and_says_when_nothing_matches(halaman):
    diminta = _jawab_history(halaman, [])
    masuk(halaman, OPERATOR)
    pilih = halaman.locator("#grading-truk")
    pilih.locator(".pilih-tombol").click()
    pertama = pilih.locator('[role="option"]:not([data-nilai=""])').first
    truck_id = pertama.get_attribute("data-nilai")
    pertama.click()

    expect(halaman.locator("#recent td.kosong")).to_have_text(kamus(halaman, "kosongGradingSaring"))
    assert [d for d in diminta if d["limit"] != "4"][-1]["truck_id"] == truck_id


def test_the_table_loads_the_small_photo_and_the_dialog_the_full_one(halaman):
    _jawab_history(halaman, [_baris(1, "line-1", thumb=PNG + "#kecil1")])
    masuk(halaman, OPERATOR)
    gambar = halaman.locator("#recent button.foto img")

    expect(gambar).to_have_attribute("src", PNG + "#kecil1")
    halaman.locator("#recent button.foto").click()

    expect(halaman.locator("#foto-modal")).to_be_visible()
    expect(halaman.locator("#foto-besar")).to_have_attribute("src", PNG + "#penuh1")


def test_a_missing_small_photo_falls_back_to_the_full_one(halaman):
    _jawab_history(halaman, [_baris(1, "line-1", thumb="/captures/line-1/tidak-ada/thumb/x.webp")])
    masuk(halaman, OPERATOR)
    gambar = halaman.locator("#recent button.foto img")

    expect(gambar).to_have_attribute("src", PNG + "#penuh1")
    expect(gambar).not_to_have_attribute("data-penuh", PNG + "#penuh1")
    assert gambar.evaluate("(img) => img.naturalWidth") == 1


def test_the_photo_strips_stay_full_while_the_table_is_filtered(halaman):
    """Spec 2026-10-07 §5.2: each line card shows that line's newest photos; filtering the
    table to one line must not empty the other cards' strips."""
    diminta = _jawab_history(halaman, [_baris(1, "line-1", thumb=PNG + "#kecil1"), _baris(2, "line-2", thumb=PNG + "#kecil2")])
    masuk(halaman, OPERATOR)
    strip_2 = halaman.locator('#lines .card[data-line="line-2"] .strip-item')
    expect(strip_2).to_have_count(1)
    pilih = halaman.locator("#grading-line")
    pilih.locator(".pilih-tombol").click()
    pilih.locator('[role="option"][data-nilai="line-1"]').click()
    expect(halaman.locator("#recent tr")).to_have_count(1)
    sebelum = len(diminta)
    halaman.evaluate("() => refresh()")
    expect(strip_2).to_have_count(1)
    assert any(d.get("line_code") == "line-2" and d["limit"] == "4" for d in diminta[sebelum:]), diminta[sebelum:]


def test_a_strip_photo_opens_the_full_photo(halaman):
    _jawab_history(halaman, [_baris(1, "line-1", thumb=PNG + "#kecil1")])
    masuk(halaman, OPERATOR)
    foto = halaman.locator('#lines .card[data-line="line-1"] .strip-item')
    expect(foto.locator("img")).to_have_attribute("src", PNG + "#kecil1")
    foto.click()
    expect(halaman.locator("#foto-modal")).to_be_visible()
    expect(halaman.locator("#foto-besar")).to_have_attribute("src", PNG + "#penuh1")
