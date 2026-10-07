"""The camera box takes the picture's own shape, so nothing is cut or stretched (2026-10-07).

The fake lines send a 12x10 picture, the 6:5 shape of the Lampung camera since the line keeps
its ratio. Before this the box was a fixed 16:9 with `object-fit: cover`.
"""
from __future__ import annotations

from langkah import OPERATOR, masuk
from playwright.sync_api import expect


def test_kotak_kamera_mengikuti_bentuk_gambar(halaman):
    masuk(halaman, OPERATOR)
    feed = halaman.locator('#lines .card[data-line="line-1"] .feed')
    expect(feed.locator("img")).to_be_visible()
    halaman.wait_for_function(
        """() => {
            const f = document.querySelector('#lines .card[data-line="line-1"] .feed');
            const r = f && f.getBoundingClientRect();
            return r && r.height > 0 && Math.abs(r.width / r.height - 1.2) < 0.012;
        }"""
    )
    kotak = feed.bounding_box()
    gambar = feed.locator("img").bounding_box()
    assert abs(kotak["width"] / kotak["height"] - 1.2) < 0.012, kotak
    # Within one pixel: layout rounds sub-pixel positions differently for the two boxes (CI).
    assert all(abs(gambar[k] - kotak[k]) <= 1 for k in ("x", "y", "width", "height")), (gambar, kotak)


def test_bentuk_kotak_bertahan_saat_kartu_digambar_ulang(halaman):
    """The polls redraw the cards; the remembered ratio must come back with the new card."""
    masuk(halaman, OPERATOR)
    halaman.wait_for_function("() => rasioFeed.get('line-1') === '12 / 10'")
    halaman.evaluate("document.querySelector('#lines .card[data-line=\"line-1\"] .feed').dataset.lama = '1'")
    halaman.click("#bahasa")  # a language switch redraws every card from kartuLine
    halaman.wait_for_function(
        "() => { const f = document.querySelector('#lines .card[data-line=\"line-1\"] .feed');"
        " return f && !f.dataset.lama; }"
    )
    gaya = halaman.locator('#lines .card[data-line="line-1"] .feed').evaluate("el => el.style.aspectRatio")
    halaman.click("#bahasa")
    assert gaya.replace(" ", "") in ("12/10", "6/5"), gaya
