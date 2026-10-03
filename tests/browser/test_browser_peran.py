"""Support tabs are hidden from an operator, and the backend refuses them anyway (rule 21):
hiding is tidiness, the 403 is the lock."""

from __future__ import annotations

from langkah import OPERATOR, SUPPORT, masuk
from playwright.sync_api import expect


def test_an_operator_sees_no_support_tab_and_is_refused_by_the_server(halaman, konsol):
    masuk(halaman, OPERATOR)
    expect(halaman.locator('#tabs [data-dev="1"]')).to_have_count(0)
    r = halaman.request.get(konsol.url + "/api/console/dev/log")
    assert r.status == 403
    assert r.json()["detail"]["code"] == "bukan_support"


def test_support_sees_the_support_tabs(halaman):
    masuk(halaman, SUPPORT)
    for tab in ("log", "status", "akun", "line", "setelan"):
        expect(halaman.locator(f'#tabs [data-tab="{tab}"]')).to_be_visible()
