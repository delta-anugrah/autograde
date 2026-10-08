"""Update now (batch 4.6): releases the trucks itself, curtain while it installs, result toast.

The host watcher is faked by writing result.json, exactly as `_update-now` would.
"""

from __future__ import annotations

import json
import shutil

import pytest
from langkah import OPERATOR, buka_menu_line, buka_tab, kamus, masuk, plat
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


def _watcher_menjawab(folder, minta, state: str, installed: str) -> None:
    """The fake watcher answers as `_update-now` does: `tulis_hasil`, then `tulis_status`."""
    (folder / "result.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": minta["id"],
                "state": state,
                "target": "v1.22.1",
                "installed": installed,
                "at": minta["at"],
            }
        )
    )
    baru = {**STATUS, "installed": installed, "staged": None if state == "ok" else STATUS["staged"]}
    (folder / "status.json").write_text(json.dumps(baru))


def _versi_konsol(halaman, versi: str) -> None:
    """What the new console reports from /state once the launcher has swapped the image."""

    def jawab(route):
        asli = route.fetch()
        isi = asli.json()
        isi["versi"] = versi
        route.fulfill(response=asli, body=json.dumps(isi))

    halaman.route("**/api/console/state", jawab)


def _tekan_pasang(halaman):
    badge = halaman.locator("#pita-pembaruan")
    expect(badge).to_contain_text(kamus(halaman, "pembaruanSiap").replace("{versi}", "v1.22.1"))
    badge.locator("[data-buka-pembaruan]").click()
    halaman.locator("#info-sistem-modal .pembaruan-pasang").click()


def test_update_now_releases_the_truck_then_shows_the_curtain_and_the_result(
    halaman, lines, konsol, folder_update, browser_name
):
    nomor = plat(browser_name, 1046)
    masuk(halaman, OPERATOR)
    buka_tab(halaman, "truk")
    halaman.fill("#plat", nomor)
    halaman.click("#daftar")
    expect(halaman.locator("#trucks")).to_contain_text(nomor)
    buka_tab(halaman, "grading")
    kartu = halaman.locator('#lines .card[data-line="line-1"]')
    buka_menu_line(kartu)
    kartu.locator(".pilih-tombol").click()
    kartu.locator('[role="option"]', has_text=nomor).click()
    kartu.locator('[data-aksi="tugaskan"]').click()
    expect(kartu.locator(".truk")).to_contain_text(nomor)
    nama_line = kartu.locator(".nama").inner_text().strip()
    halaman.evaluate("() => { window.__halamanLama = true; }")

    try:
        _tekan_pasang(halaman)
        # The question names the truck and its line, then says what happens to the truck.
        pesan = halaman.locator("#konfirmasi-pesan")
        expect(pesan).to_contain_text(f"{nomor} di {nama_line}")
        expect(pesan).to_contain_text(kamus(halaman, "konfirmasiPasangRestart"))
        halaman.click("#konfirmasi-ya")

        expect(halaman.locator("#tirai-pembaruan")).to_be_visible()
        expect(halaman.locator("#tirai-pembaruan")).to_contain_text(
            kamus(halaman, "tiraiPasang").replace("{versi}", "v1.22.1")
        )
        expect(kartu.locator(".truk")).not_to_contain_text(nomor)
        minta = json.loads((folder_update / "request.json").read_text())
        assert minta["target"] == "v1.22.1"
        assert minta["by"] == OPERATOR[0]

        # The new console is up: the watcher has answered and the state reports the new version.
        _watcher_menjawab(folder_update, minta, "ok", "v1.22.1")
        _versi_konsol(halaman, "v1.22.1")
        halaman.wait_for_function("() => window.__halamanLama === undefined")
        toast = kamus(halaman, "pembaruanBerhasil").replace("{versi}", "v1.22.1")
        expect(halaman.locator("#toasts")).to_contain_text(toast)
        expect(halaman.locator("#tirai-pembaruan")).to_be_hidden()
    finally:
        halaman.unroute("**/api/console/state")
        halaman.request.post(f"{konsol.url}/api/console/lines/line-1/release-truck")


def test_update_now_rolled_back_drops_the_curtain_with_a_failure_toast(halaman, konsol, folder_update):
    masuk(halaman, OPERATOR)
    _tekan_pasang(halaman)
    expect(halaman.locator("#konfirmasi-pesan")).to_have_text(kamus(halaman, "konfirmasiPasangRestart"))
    halaman.click("#konfirmasi-ya")
    expect(halaman.locator("#tirai-pembaruan")).to_be_visible()
    minta = json.loads((folder_update / "request.json").read_text())

    _watcher_menjawab(folder_update, minta, "rolled_back", "v1.22.0")
    gagal = kamus(halaman, "pembaruanHasilBalik").replace("{versi}", "v1.22.1").replace("{lama}", "v1.22.0")
    expect(halaman.locator("#toasts")).to_contain_text(gagal)
    expect(halaman.locator("#tirai-pembaruan")).to_be_hidden()


def test_curtain_gives_way_to_the_login_gate_and_returns_after_login(halaman, konsol, folder_update):
    """The gate sits above the curtain: its fields must take keys, and the marker must survive."""
    masuk(halaman, OPERATOR)
    _tekan_pasang(halaman)
    halaman.click("#konfirmasi-ya")
    expect(halaman.locator("#tirai-pembaruan")).to_be_visible()

    assert halaman.request.post(f"{konsol.url}/api/console/logout").ok
    expect(halaman.locator("#gerbang")).to_be_visible()
    expect(halaman.locator("#tirai-pembaruan")).to_be_hidden()
    halaman.fill("#gerbang-sandi", "abc")
    assert halaman.input_value("#gerbang-sandi") == "abc"

    halaman.fill("#gerbang-email", OPERATOR[0])
    halaman.fill("#gerbang-sandi", OPERATOR[1])
    halaman.click("#gerbang-masuk")
    expect(halaman.locator("#gerbang")).to_be_hidden()
    expect(halaman.locator("#tirai-pembaruan")).to_be_visible()


def test_update_now_cancel_sends_nothing(halaman, konsol, folder_update):
    masuk(halaman, OPERATOR)
    _tekan_pasang(halaman)
    halaman.click("#konfirmasi-tidak")
    expect(halaman.locator("#tirai-pembaruan")).to_be_hidden()
    assert not (folder_update / "request.json").exists()


def test_update_banner_closes_until_the_next_version(halaman, konsol, folder_update):
    """User 2026-10-04: the banner opens the box when tapped and can be closed; closed stays
    closed for that version, and a newer staged version brings it back."""
    masuk(halaman, OPERATOR)
    halaman.evaluate("localStorage.removeItem('pembaruanDitutup')")
    pita = halaman.locator("#pita-pembaruan")
    expect(pita).to_contain_text("v1.22.1")
    pita.locator("[data-buka-pembaruan]").click()
    expect(halaman.locator("#info-sistem-modal")).to_be_visible()
    halaman.click("#info-sistem-tutup")
    pita.locator("[data-tutup-pembaruan]").click()
    expect(pita).to_be_hidden()
    halaman.reload()
    # The session survives a reload; wait for the first poll to draw the header.
    expect(halaman.locator("#info-sistem")).to_be_visible()
    expect(pita).to_be_hidden()
    (folder_update / "status.json").write_text(json.dumps({**STATUS, "staged": "v1.22.2"}))
    expect(pita).to_contain_text("v1.22.2")
    halaman.evaluate("localStorage.removeItem('pembaruanDitutup')")
