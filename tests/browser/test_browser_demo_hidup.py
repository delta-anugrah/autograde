"""DEMO_MODE on a real console (demo-autograde.smagri.id): the screen looks alive.

Camera boxes show the bundled frames, counters tick up, simulated rows lead the Grading table
and the scale tile rises and falls. All of it in the browser only; the pure logic is in
`tests/unit/test_console_html_demo_hidup.py`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx
import pytest
from harness import KonsolUji, port_bebas
from langkah import OPERATOR, masuk
from playwright.sync_api import expect

# A tick every 2.6 s and a 2 s state poll; generous for a slow CI runner.
DEMO_MAKS_MS = 10_000
# Two ticks apart at least, so every line has moved on once.
ANTAR_BACA_MS = 6_000
FRAME_DEMO = re.compile(r"/demo/frame-[1-5]\.webp$")


class TestDemoHidup:
    @pytest.fixture(scope="class")
    def konsol(self, tmp_path_factory: pytest.TempPathFactory) -> Iterator[KonsolUji]:
        """A console of its own with DEMO_MODE on and no line listening, as on the droplet."""
        k = KonsolUji(
            tmp_path_factory.mktemp("konsol-demo"),
            port_line=(port_bebas(), port_bebas(), port_bebas()),
            env={"DEMO_MODE": "1"},
        )
        k.seed(hari=1)
        k.mulai()
        try:
            yield k
        finally:
            k.berhenti()

    def test_frames_counters_rows_and_scale_move(self, halaman):
        masuk(halaman, OPERATOR)
        kartu = halaman.locator("#lines .card")
        expect(kartu).to_have_count(3)
        feed = halaman.locator("#lines .card .feed img")
        expect(feed.first).to_have_attribute("src", FRAME_DEMO, timeout=DEMO_MAKS_MS)
        expect(halaman.locator("#lines .card.putus")).to_have_count(0, timeout=DEMO_MAKS_MS)
        src = [feed.nth(i).get_attribute("src") for i in range(3)]
        assert all("/demo/frame-" in s for s in src), src
        assert len(set(src)) == 3, src

        total_awal = halaman.evaluate("() => document.getElementById('tot-all')._angka || 0")
        kg_awal = halaman.locator("#timbang-kg").text_content()
        halaman.wait_for_timeout(ANTAR_BACA_MS)
        halaman.wait_for_function(
            "(awal) => (document.getElementById('tot-all')._angka || 0) > awal", arg=total_awal, timeout=DEMO_MAKS_MS
        )
        # The newest row of the table is a simulated bunch with its demo photo.
        expect(halaman.locator("#recent tr").first.locator("button.foto")).to_have_attribute(
            "data-foto", FRAME_DEMO, timeout=DEMO_MAKS_MS
        )
        halaman.wait_for_function(
            "(awal) => document.getElementById('timbang-kg').textContent !== awal", arg=kg_awal, timeout=DEMO_MAKS_MS
        )


def test_without_demo_mode_nothing_is_simulated(halaman, konsol):
    """A factory console: no demo frames served, none on screen."""
    assert httpx.get(konsol.url + "/demo/frames.json").status_code == 404
    masuk(halaman, OPERATOR)
    expect(halaman.locator("#lines .card")).to_have_count(3)
    for img in halaman.locator("#lines .card .feed img").all():
        assert "/demo/" not in (img.get_attribute("src") or "")
