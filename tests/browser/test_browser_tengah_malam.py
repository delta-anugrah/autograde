"""A truck still in the yard after midnight stays on the Timbangan table and can be finished.

The browser's clock and the console's clock are the machine's own, and the test console runs
in its own process, so neither can be set to 00:10. The ticket is written so that "now" is
just after midnight relative to it instead: its work date is YESTERDAY (the console's
yesterday, Asia/Jakarta) and its weigh-in was 20 minutes ago. That is exactly what the
table sees at 00:10 for a 23:50 weigh-in: an earlier work date, inside the visit window,
not left yet. At any hour of the day the test means the same thing.

Written straight into the console's SQLite file (WAL, so the running console sees it): the
API stamps the work date from the weigh-in time and cannot write such a row on demand.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

from palmgrade.domain.plate import normalisasi_plat, truck_id_for

WIB = ZoneInfo("Asia/Jakarta")
_NETO = 2  # number cells: gross, tare, net (`barisTimbangan`)


def _tiket_kemarin_belum_selesai(konsol, nomor: str, *, menit_lalu: int = 20) -> str:
    """One ticket weighed in `menit_lalu` ago whose work date is yesterday; returns that date."""
    ref = f"MALAM-{nomor}"
    kemarin = (datetime.now(WIB) - timedelta(days=1)).strftime("%Y-%m-%d")
    masuk_pada = (datetime.now(UTC) - timedelta(minutes=menit_lalu)).isoformat()
    with sqlite3.connect(konsol.state / "console.db") as db:
        db.execute(
            """INSERT INTO weighings (id, ref, plate_number, plate_norm, truck_id, work_date,
                                      gross_kg, entered_at, received_at)
               VALUES (?, ?, ?, ?, ?, ?, 14000, ?, ?)""",
            (str(uuid.uuid5(uuid.NAMESPACE_URL, f"timbangan:{ref}")), ref, nomor,
             normalisasi_plat(nomor), truck_id_for(nomor), kemarin, masuk_pada, time.time()),
        )
    return kemarin


def test_a_truck_from_before_midnight_is_finished_from_todays_table(halaman, konsol, browser_name):
    nomor = plat(browser_name, 1010)
    kemarin = _tiket_kemarin_belum_selesai(konsol, nomor)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "timbangan")

    baris = halaman.locator("#timbangan tr", has_text=nomor)
    expect(baris).to_have_count(1)
    expect(baris.locator(".lencana")).to_have_text(kamus(halaman, "tahapBongkar"))
    tombol = baris.locator('button[data-aksi="keluar"]')
    expect(tombol).to_have_text(kamus(halaman, "btnTimbangKosong"))

    tombol.click()
    expect(halaman.locator("#tara-plat")).to_have_text(nomor)
    halaman.fill("#tara-nilai", "6000")
    halaman.click("#tara-simpan")
    expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "sukTara"))
    # Still on today's table, one step on: weighed out, waiting to leave the gate.
    expect(baris.locator("td.num").nth(_NETO)).to_have_text(halaman.evaluate("() => kg(8000)"))
    expect(baris.locator(".lencana")).to_have_text(kamus(halaman, "tahapTimbangKosong"))

    baris.locator('button[data-aksi="pergi"]').click()
    expect(halaman.locator("#toasts")).to_contain_text(f"{kamus(halaman, 'sukPergi')} {nomor}")
    # Finished: it leaves today's table, and stays on its own day.
    expect(baris).to_have_count(0)
    hari_itu = halaman.request.get(konsol.url + "/api/console/weighings", params={"work_date": kemarin}).json()
    [tiket] = [w for w in hari_itu["items"] if w["plate_number"] == nomor]
    assert (tiket["work_date"], tiket["tahap"], tiket["net_kg"]) == (kemarin, "selesai", 8000.0)


def test_two_open_tickets_across_midnight_are_refused_not_guessed(halaman, konsol, browser_name, scanner_nyala):
    """What the night run of `test_two_open_tickets_are_refused_not_guessed` hit before 00:30,
    now at any hour: the first ticket on yesterday's work date, the second on today's. Both are
    open in the visit window, so the scan asks the operator to choose."""
    nomor = plat(browser_name, 1011)
    _tiket_kemarin_belum_selesai(konsol, nomor, menit_lalu=30)
    masuk(halaman, OPERATOR)
    r = halaman.request.post(konsol.url + "/api/console/weighings", data={
        "plate_number": nomor, "gross_kg": "14000", "entered_at": datetime.now(UTC).isoformat(),
    })
    assert r.status == 201, r.text()
    buka_tab(halaman, "timbangan")
    halaman.evaluate("() => muatTimbangan()")  # the API weigh-in came after the first load
    expect(halaman.locator("#timbangan tr", has_text=nomor)).to_have_count(2)

    expect(halaman.locator("#scan-otomatis")).to_be_focused()
    halaman.keyboard.type(nomor)
    halaman.keyboard.press("Enter")
    expect(halaman.locator("#scan-otomatis-pesan")).to_have_text(f"{kamus(halaman, 'scanGanda')} {nomor}")
    expect(halaman.locator("#tara-grup")).to_be_hidden()
