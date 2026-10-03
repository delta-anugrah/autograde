"""One truck visit on the weighbridge screen, the way the operator does it today: pick the
plate from the list, gross with a keypad comma, Timbang kosong on the ticket row, tare, the
net the server computed (rule 15) shown in the row, and then Keluar on the same row (scan 4,
the truck leaves the gate).

The plate comes from the list, not a scan: the QR field ships hidden until the mill buys a
scanner (`test_browser_scan.py` covers that path). The truck is registered on the Truk tab,
which redraws the list at once; one registered through the API would wait for the 60 s poll.
"""

from __future__ import annotations

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

# The row's number cells, in order: gross, tare, net (`barisTimbangan` in console.html).
# A whole-row `to_contain_text` would accept 8.620 inside 8.620,5.
_BRUTO, _NETO = 0, 2


def test_a_visit_from_gross_to_net(halaman, browser_name):
    nomor = plat(browser_name, 1003)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)

    buka_tab(halaman, "timbangan")
    pilih = halaman.locator("#plat-timbang")
    pilih.locator(".pilih-tombol").click()
    pilih.locator('[role="option"]', has_text=nomor).click()
    expect(pilih).to_have_attribute("data-nilai", nomor)
    halaman.fill("#bruto", "14820,5")
    halaman.click("#masuk")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukMasuk"))
    baris = halaman.locator("#timbangan tr", has_text=nomor)
    angka = baris.locator("td.num")
    expect(angka.nth(_BRUTO)).to_have_text(halaman.evaluate("() => kg(14820.5)"))

    tombol = baris.locator('button[data-aksi="keluar"]')
    expect(tombol).to_have_text(kamus(halaman, "btnTimbangKosong"))
    tombol.click()
    expect(halaman.locator("#tara-grup")).to_be_visible()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", "6200")
    halaman.click("#tara-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTara"))
    expect(angka.nth(_NETO)).to_have_text(halaman.evaluate("() => kg(8620.5)"))

    # Weighed out, the row's one button moves on to the next step: the truck leaving the gate.
    expect(baris.locator('button[data-aksi="keluar"]')).to_have_count(0)
    pergi = baris.locator('button[data-aksi="pergi"]')
    expect(pergi).to_have_text(kamus(halaman, "btnPergi"))
    pergi.click()
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukPergi')} {nomor}")
    expect(baris.locator("button[data-aksi]")).to_have_count(0)
