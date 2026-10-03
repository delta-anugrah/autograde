"""Update now (batch 4.6): refused while a truck is on a line, accepted once it is released.

The host watcher is faked by writing result.json, exactly as `_update-now` would.
"""

from __future__ import annotations

import json
import shutil

import pytest
from langkah import OPERATOR, buka_tab, kamus, masuk, plat
from playwright.sync_api import expect

STATUS = {
    "schema": 1,
    "installed": "v1.22.0",
    "staged": "v1.22.1",
    "checked_at": "2026-10-20T07:00:00+07:00",
    "watcher": True,
}


@pytest.fixture
def folder_update(konsol):
    # One console per session: the folder goes away with the test, or the badge would show
    # in every test after this one.
    folder = konsol.root / "update"
    folder.mkdir(exist_ok=True)
    (folder / "status.json").write_text(json.dumps(STATUS))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_update_now_refused_with_a_truck_then_accepted_without(halaman, lines, konsol, folder_update, browser_name):
    nomor = plat(browser_name, 1046)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "grading")
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    kartu.locator(".pilih-tombol").click()
    kartu.locator('[role="option"]', has_text=nomor).click()
    kartu.locator('[data-aksi="tugaskan"]').click()
    expect(kartu.locator(".truk")).to_contain_text(nomor)
    nama_line = kartu.locator(".nama").inner_text().strip()

    try:
        badge = halaman.locator("#badge-pembaruan")
        expect(badge).to_have_text(kamus(halaman, "pembaruanSiap").replace("{versi}", "v1.22.1"))
        badge.click()
        tombol = halaman.locator("#info-sistem-modal .pembaruan-pasang")
        tombol.click()
        # User decision 2026-10-02: the refusal names the line as its card does.
        ditolak = kamus(halaman, "err_pembaruan_ada_truk").replace("{line}", nama_line)
        expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "gagalPasangPembaruan"))
        expect(halaman.locator("#toasts")).to_contain_text(ditolak)
        assert not (folder_update / "request.json").exists()

        assert halaman.request.post(f"{konsol.url}/api/console/lines/line-1/release-truck").ok
        tombol.click()
        expect(halaman.locator("#toasts")).to_contain_text(kamus(halaman, "pembaruanDimulai"))
        expect(halaman.locator("#pembaruan-isi")).to_contain_text(kamus(halaman, "pembaruanBerjalan"))
        expect(badge).to_be_hidden()
        minta = json.loads((folder_update / "request.json").read_text())
        assert minta["target"] == "v1.22.1"
        assert minta["by"] == OPERATOR[0]

        # The fake watcher answers as `_update-now` does: `tulis_hasil`, then `tulis_status`.
        (folder_update / "result.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "id": minta["id"],
                    "state": "ok",
                    "target": "v1.22.1",
                    "installed": "v1.22.1",
                    "at": minta["at"],
                }
            )
        )
        (folder_update / "status.json").write_text(json.dumps({**STATUS, "installed": "v1.22.1", "staged": None}))
        expect(halaman.locator("#pembaruan-isi")).to_contain_text(
            kamus(halaman, "pembaruanHasilOk").replace("{versi}", "v1.22.1")
        )
        expect(halaman.locator("#info-sistem-modal .pembaruan-pasang")).to_have_count(0)
        expect(badge).to_be_hidden()
    finally:
        halaman.request.post(f"{konsol.url}/api/console/lines/line-1/release-truck")
