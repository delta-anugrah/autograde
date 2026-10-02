"""Rekap tab over the ten seeded days: rows show, and the CSV downloads with its BOM
(Excel on the office PC needs it to read Indonesian names correctly)."""

from __future__ import annotations

from pathlib import Path

from langkah import OPERATOR, buka_tab, masuk
from playwright.sync_api import expect

_BOM = b"\xef\xbb\xbf"


def test_seeded_history_shows_rows(halaman):
    """"7 hari", not the default "Hari ini": the seeder keeps every visit in the past, so a
    session started between 00:00 and about 01:21 WIB has no visit on today's date at all
    (each day's visits slide to the day before). The last seven days always hold six seeded
    days, whatever the hour."""
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "rekap")
    halaman.click('.riwayat-cepat button[data-cepat="7hari"]')
    # A data row, not just any row: the empty table is a `<tr>` too (`barisKosong`, td.kosong).
    expect(halaman.locator("#riwayat-baris td.key").first).to_be_visible()


def test_the_csv_downloads_with_a_bom(halaman):
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "rekap")
    with halaman.expect_download() as unduhan:
        halaman.click("#riwayat-csv")
    berkas = unduhan.value
    assert berkas.suggested_filename.endswith(".csv")
    assert Path(berkas.path()).read_bytes().startswith(_BOM)
