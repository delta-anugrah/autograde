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


# A 1x1 PNG: a strip photo whose shape is nothing like the camera's.
_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _strip(halaman, thumb: str) -> None:
    baris = {"timestamp": "2026-10-08T08:00:00+07:00", "line_code": "line-1", "plate_number": "BE 1 AA",
             "source_label": "Internal", "ripeness_status": "ACC", "grade_class": "Ripe",
             "image_url": _PNG + "#penuh", "thumb_url": thumb}
    def jawab(route):
        isi = [baris] if "line_code=line-2" not in route.request.url and "line_code=line-3" not in route.request.url else []
        route.fulfill(json={"work_date": "2026-10-08", "items": isi, "total": len(isi)})

    halaman.route("**/api/console/history*", jawab)


def test_a_strip_photo_never_sets_the_camera_shape(halaman):
    """The load listener on #lines took every picture in a card, the photo strip too (review of
    PR #257 CI): a square thumbnail replaced the camera's 6:5 and the box jumped."""
    _strip(halaman, _PNG + "#kecil")
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    expect(kartu.locator(".strip-item img")).to_have_count(1)
    halaman.wait_for_function("() => rasioFeed.get('line-1') === '12 / 10'")
    halaman.wait_for_function(
        "() => { const i = document.querySelector('#lines .card[data-line=\"line-1\"] .strip-item img');"
        " return i && i.complete && i.naturalWidth === 1; }"
    )
    halaman.evaluate("() => refresh()")
    assert halaman.evaluate("() => rasioFeed.get('line-1')") == "12 / 10"
    assert kartu.locator(".strip-item").first.evaluate("el => el.style.aspectRatio") == ""


def test_a_missing_strip_photo_does_not_say_the_camera_is_cut(halaman):
    """An error on a strip photo marked the whole card `putus` ("Kamera tidak tersambung")."""
    _strip(halaman, "/captures/line-1/tidak-ada/thumb/x.webp")
    masuk(halaman, OPERATOR)
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    halaman.wait_for_function("() => rasioFeed.get('line-1') === '12 / 10'")
    expect(kartu.locator(".strip-item img")).to_have_count(1)
    halaman.wait_for_timeout(1500)
    expect(kartu).not_to_have_class(__import__("re").compile(r"\bputus\b"))
