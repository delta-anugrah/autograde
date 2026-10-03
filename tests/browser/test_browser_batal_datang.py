"""Batal datang and a visit finished "tanpa scan 4" on the Timbangan tab (user 2026-10-03).

Batal datang: a DATANG row's red button asks once more ("Yakin? Klik lagi"), the second
click takes the arrival back and the row leaves the table. Tanpa scan 4: a weighed-out
visit that never got its Keluar shows SELESAI with a yellow TANPA SCAN 4 tag and no Keluar
button, after 24 h or as soon as its truck is back at the gate.

The console lives for the whole session, so every arrival made here is cancelled and every
open visit leaves; only the 24 h one is seeded finished on purpose.
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

from palmgrade.domain.plate import normalisasi_plat, truck_id_for

WIB = ZoneInfo("Asia/Jakarta")


def _jam(menit_lalu: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=menit_lalu)).isoformat()


def _daftar_dan_datang(halaman, konsol, nomor: str) -> None:
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()
    r = halaman.request.post(konsol.url + "/api/console/arrivals", data={"qr": nomor, "at": _jam()})
    assert r.status == 200 and r.json()["hasil"] == "tercatat", r.text()


def _baris(halaman, nomor: str):
    return halaman.locator("#timbangan tr", has_text=nomor)


def _batal_dua_klik(halaman, nomor: str) -> None:
    baris = halaman.locator("#timbangan tr.baris-menunggu", has_text=nomor)
    tombol = baris.locator('button[data-aksi="batal-datang"]')
    expect(tombol).to_have_text(kamus(halaman, "btnBatalDatang"))
    expect(tombol).to_have_class(re.compile(r"\bbahaya\b"))
    tombol.click()
    # First click only asks: still there, now in the hard red variant.
    expect(tombol).to_have_text(kamus(halaman, "batalDatangYakin"))
    expect(tombol).to_have_class(re.compile(r"\bbahaya\b.*\bpekat\b"))
    expect(baris).to_have_count(1)
    tombol.click()
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukBatalDatang").replace("{plat}", nomor))
    expect(baris).to_have_count(0)


def test_cancel_arrival_asks_twice_then_removes_the_row(halaman, konsol, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1301)
    masuk(halaman, OPERATOR)
    _daftar_dan_datang(halaman, konsol, nomor)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    expect(_baris(halaman, nomor).locator(".lencana")).to_have_text(kamus(halaman, "tahapDatang"))

    _batal_dua_klik(halaman, nomor)
    menunggu = halaman.request.get(konsol.url + "/api/console/weighings").json()["waiting"]
    assert all(a["plate_number"] != nomor for a in menunggu)


def _tiket_25_jam_lalu_tanpa_keluar(konsol, nomor: str) -> None:
    """Weighed in 26 h and out 25 h ago, never left. Stamped with TODAY's work date so the
    default table shows it: the table reads the work date, the stage reads the clock."""
    ref = f"TANPA4-{nomor}"
    hari_ini = datetime.now(WIB).strftime("%Y-%m-%d")
    with sqlite3.connect(konsol.state / "console.db") as db:
        db.execute(
            """INSERT INTO weighings (id, ref, plate_number, plate_norm, truck_id, work_date,
                                      gross_kg, tare_kg, net_kg, entered_at, exited_at, received_at)
               VALUES (?, ?, ?, ?, ?, ?, 14000, 6000, 8000, ?, ?, ?)""",
            (str(uuid.uuid5(uuid.NAMESPACE_URL, f"timbangan:{ref}")), ref, nomor, normalisasi_plat(nomor),
             truck_id_for(nomor), hari_ini, _jam(26 * 60), _jam(25 * 60), time.time()),
        )


def test_a_visit_without_leave_after_24_hours_is_done_without_scan_4(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1302)
    _tiket_25_jam_lalu_tanpa_keluar(konsol, nomor)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")

    baris = _baris(halaman, nomor)
    expect(baris.locator(".lencana")).to_have_text(kamus(halaman, "tahapSelesai"))
    tag = baris.locator(".tag.peringatan", has_text=kamus(halaman, "tanpaScan4"))
    expect(tag).to_have_count(1)
    expect(baris.locator("button")).to_have_count(0)


def test_the_truck_coming_back_ends_its_old_visit_until_the_arrival_is_cancelled(
        halaman, konsol, browser_name, penugasan_bersih):
    nomor = plat(browser_name, 1303)
    masuk(halaman, OPERATOR)
    r = halaman.request.post(konsol.url + "/api/console/trucks", data={"plate_number": nomor})
    assert r.status == 201, r.text()
    masuk_pada = _jam(10)
    for data in ({"plate_number": nomor, "gross_kg": "14000", "entered_at": masuk_pada},
                 {"plate_number": nomor, "entered_at": masuk_pada, "tare_kg": "6000", "exited_at": _jam(2)}):
        r = halaman.request.post(konsol.url + "/api/console/weighings", data=data)
        assert r.status == 201, r.text()
    r = halaman.request.post(konsol.url + "/api/console/arrivals", data={"qr": nomor, "at": _jam()})
    assert r.json()["hasil"] == "tercatat", r.text()

    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")
    lama = halaman.locator("#timbangan tr[data-id]", has_text=nomor)
    expect(lama.locator(".lencana")).to_have_text(kamus(halaman, "tahapSelesai"))
    expect(lama.locator(".tag.peringatan", has_text=kamus(halaman, "tanpaScan4"))).to_have_count(1)
    expect(lama.locator('button[data-aksi="pergi"]')).to_have_count(0)

    # The arrival was a mistake: cancelling it gives the old visit its Keluar back.
    _batal_dua_klik(halaman, nomor)
    expect(lama.locator(".lencana")).to_have_text(kamus(halaman, "tahapTimbangKosong"))
    lama.locator('button[data-aksi="pergi"]').click()
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukPergi')} {nomor}")
    expect(lama.locator(".lencana")).to_have_text(kamus(halaman, "tahapSelesai"))
