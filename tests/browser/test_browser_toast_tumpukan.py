"""Toasts stack like Sonner (user 2026-10-03, "richColors"), rebuilt by hand in the one file.

Newest in front, older ones folded behind it (at most three visible), the stack opens into a
list under the pointer and holds every countdown while it is open, a close button, a swipe to
the right, and every toast still closes by itself. With reduced motion nothing animates.
"""

from __future__ import annotations

from langkah import JEDA_HALAMAN_MS, OPERATOR, masuk
from playwright.sync_api import expect

_PENANDA = "Uji tumpukan"
# Boxes of this test's toasts, newest first, with the stack state.
_KOTAK = """(penanda) => {
  const kartu = [...document.querySelectorAll('#toasts .toast:not([data-keluar])')]
    .filter((el) => el.querySelector('.pesan').textContent.startsWith(penanda)).reverse();
  return {terbuka: document.querySelector('#toasts').hasAttribute('data-terbuka'),
    kartu: kartu.map((el) => { const r = el.getBoundingClientRect();
      return {teks: el.querySelector('.pesan').textContent, top: r.top, bottom: r.bottom,
              z: Number(el.style.zIndex), belakang: el.hasAttribute('data-belakang'),
              sembunyi: el.hasAttribute('data-sembunyi')}; })};
}"""
# Folded: every older card sits just above the front one, overlapping it, and nothing moves
# any more (a box read mid-transition is somewhere in between).
_TERLIPAT = """(penanda) => { const k = [...document.querySelectorAll('#toasts .toast:not([data-keluar])')]
  .filter((el) => el.querySelector('.pesan').textContent.startsWith(penanda)).reverse()
  .map((el) => el.getBoundingClientRect());
  return k.length >= 2 && k.slice(1).every((r) => r.bottom > k[0].top + 1 && r.top < k[0].top)
    && document.querySelector('#toasts').getAnimations({subtree: true}).length === 0; }"""
# Open: a list, each older card wholly above the newer one.
_TERBUKA = """(penanda) => { const k = [...document.querySelectorAll('#toasts .toast:not([data-keluar])')]
  .filter((el) => el.querySelector('.pesan').textContent.startsWith(penanda)).reverse()
  .map((el) => el.getBoundingClientRect());
  return k.length >= 2 && k.slice(1).every((r, i) => r.bottom <= k[i].top + 1)
    && document.querySelector('#toasts').getAnimations({subtree: true}).length === 0; }"""


def _siap(halaman) -> None:
    """Signed in (the gate sits above the toasts), the corner empty, the pointer away from it."""
    masuk(halaman, OPERATOR)
    halaman.evaluate("async () => { await refresh();"
                     " document.querySelectorAll('#toasts .toast').forEach((el) => el.remove()); susunToast(); }")
    halaman.mouse.move(5, 5)


def _tiga(halaman, durasi: int = 10000) -> None:
    for i in (1, 2, 3):
        halaman.evaluate("([t, d]) => toast('sukses', t, d)", [f"{_PENANDA} {i}", durasi])


def _depan(halaman):
    return halaman.locator("#toasts .toast:not([data-belakang]):not([data-keluar])")


def test_three_toasts_fold_behind_the_newest(halaman):
    _siap(halaman)
    _tiga(halaman)
    halaman.wait_for_function(_TERLIPAT, arg=_PENANDA)
    keadaan = halaman.evaluate(_KOTAK, _PENANDA)
    assert not keadaan["terbuka"], keadaan
    teks = [k["teks"] for k in keadaan["kartu"]]
    assert teks == [f"{_PENANDA} 3", f"{_PENANDA} 2", f"{_PENANDA} 1"], teks
    depan, *lama = keadaan["kartu"]
    assert not depan["belakang"] and all(k["belakang"] for k in lama), keadaan
    assert depan["z"] > lama[0]["z"] > lama[1]["z"], keadaan
    # The older ones peek out a little above the front card, not a whole card height.
    assert 0 < depan["top"] - lama[0]["top"] < 20, keadaan
    # A fourth one pushes the oldest out of sight (three visible), a fifth out of the page.
    halaman.evaluate("(t) => toast('peringatan', t)", f"{_PENANDA} 4")
    expect(halaman.locator("#toasts .toast[data-sembunyi]", has_text=f"{_PENANDA} 1")).to_have_count(1)
    halaman.evaluate("(t) => toast('gagal', t)", f"{_PENANDA} 5")
    expect(halaman.locator("#toasts .toast", has_text=f"{_PENANDA} 1")).to_have_count(0)
    for jenis in ("sukses", "peringatan", "gagal"):
        expect(halaman.locator(f"#toasts .toast.{jenis} svg.ikon-toast").first).to_be_attached()


def test_hover_opens_the_stack_and_holds_the_countdown(halaman):
    _siap(halaman)
    _tiga(halaman, durasi=1200)
    halaman.wait_for_function(_TERLIPAT, arg=_PENANDA)
    _depan(halaman).hover()
    expect(halaman.locator("#toasts")).to_have_attribute("data-terbuka", "")
    halaman.wait_for_function(_TERBUKA, arg=_PENANDA)
    # Well past 1.2 s on the page's own clock: still there while the pointer rests on them.
    halaman.evaluate("(ms) => new Promise((r) => setTimeout(r, ms))", 2000)
    expect(halaman.locator("#toasts .toast", has_text=_PENANDA)).to_have_count(3)
    halaman.mouse.move(5, 5)
    expect(halaman.locator("#toasts")).not_to_have_attribute("data-terbuka", "")
    # The countdown runs on from what was left, so they close by themselves.
    expect(halaman.locator("#toasts .toast", has_text=_PENANDA)).to_have_count(0)


def test_close_button_and_auto_close(halaman):
    _siap(halaman)
    halaman.evaluate("(t) => toast('sukses', t, 600)", f"{_PENANDA} pendek")
    halaman.evaluate("(t) => toastGagal(t)", f"{_PENANDA} tutup")
    tutup = halaman.locator("#toasts .toast", has_text=f"{_PENANDA} tutup")
    tutup.locator(".tutup").click()
    expect(tutup).to_have_count(0)
    # The pointer that clicked still rests on the stack and holds it; away, the rest runs on.
    halaman.mouse.move(5, 5)
    expect(halaman.locator("#toasts .toast", has_text=f"{_PENANDA} pendek")).to_have_count(0)


def test_swipe_right_dismisses_a_short_drag_snaps_back(halaman):
    _siap(halaman)
    halaman.evaluate("(t) => toastSukses(t)", f"{_PENANDA} geser")
    kartu = halaman.locator("#toasts .toast", has_text=f"{_PENANDA} geser")
    expect(kartu).not_to_have_attribute("data-masuk", "")
    halaman.evaluate("(ms) => new Promise((r) => setTimeout(r, ms))", JEDA_HALAMAN_MS * 2)
    kotak = kartu.locator(".pesan").bounding_box()
    x, y = kotak["x"] + 10, kotak["y"] + kotak["height"] / 2

    halaman.mouse.move(x, y)
    halaman.mouse.down()
    halaman.mouse.move(x + 30, y, steps=5)
    halaman.mouse.up()
    expect(kartu).to_have_count(1)
    expect(kartu).not_to_have_attribute("data-keluar", "")
    assert kartu.evaluate("(el) => el.style.getPropertyValue('--geser')") == "0px"

    halaman.mouse.move(x, y)
    halaman.mouse.down()
    halaman.mouse.move(x + 160, y, steps=8)
    halaman.mouse.up()
    expect(kartu).to_have_count(0)


def test_reduced_motion_shows_and_removes_at_once(halaman):
    halaman.emulate_media(reduced_motion="reduce")
    _siap(halaman)
    halaman.evaluate("(t) => toastSukses(t)", f"{_PENANDA} tenang")
    kartu = halaman.locator("#toasts .toast", has_text=f"{_PENANDA} tenang")
    expect(kartu).to_be_visible()
    gaya = kartu.evaluate("(el) => [getComputedStyle(el).opacity, getComputedStyle(el).transitionDuration]")
    assert float(gaya[0]) > 0.9 and set(gaya[1].replace(" ", "").split(",")) == {"0s"}, gaya
    # Gone in the same task the close button runs in: no fade waits on a timer.
    sisa = kartu.locator(".tutup").evaluate(
        "(b) => { b.click(); return document.querySelectorAll('#toasts .toast').length; }")
    assert sisa == 0
