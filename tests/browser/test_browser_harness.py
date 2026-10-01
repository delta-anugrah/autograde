"""The harness itself: isolated from the developer's machine, loud when it breaks.

These hold the promises every other browser test leans on (plan Review Focus 1-5).
"""

from __future__ import annotations

import socket
from pathlib import Path

import httpx
import langkah  # noqa: F401  (skips this module where Playwright is missing, fails in CI)
import pytest
from harness import PORT_DEVELOPER, KonsolUji, port_bebas
from line_palsu import LinePalsu


def test_ports_never_touch_the_developers_console():
    assert {port_bebas() for _ in range(50)}.isdisjoint(PORT_DEVELOPER)


def test_the_console_copy_has_no_dotenv_above_it(konsol):
    # `load_dotenv()` climbs from the code's own folder; the copy must find nothing.
    code = konsol.src / "palmgrade"
    assert not [p for p in (code, *code.parents) if (p / ".env").is_file()]


def test_a_console_that_cannot_start_says_why(tmp_path):
    k = KonsolUji(tmp_path, port_line=(port_bebas(), port_bebas(), port_bebas()))
    (k.src / "palmgrade" / "console_main.py").write_text("raise SystemExit('broken on purpose')\n")
    with pytest.raises(RuntimeError, match="broken on purpose"):
        k.mulai()


def test_stopping_frees_the_port(tmp_path):
    k = KonsolUji(tmp_path, port_line=(port_bebas(), port_bebas(), port_bebas()))
    k.mulai()
    k.berhenti()
    with socket.socket() as s:
        s.bind(("127.0.0.1", k.port))  # raises OSError if the console still holds it


def test_a_fake_line_records_what_it_is_sent():
    line = LinePalsu.mulai("line-1")
    try:
        r = httpx.post(f"http://127.0.0.1:{line.port}/internal/setelan", json={"a": 1})
        assert r.status_code == 200
        assert line.diterima == [("/internal/setelan", {"a": 1})]
        assert httpx.get(f"http://127.0.0.1:{line.port}/internal/plc").status_code == 404
    finally:
        line.berhenti()


def test_the_guard_ignores_a_refused_resource_but_not_a_script_error(halaman):
    # A refused image load is what Chromium logs for the offline line's feed.
    halaman.evaluate("() => { const i = new Image(); i.src = 'http://127.0.0.1:9/nope.png'; }")
    halaman.evaluate("() => { setTimeout(() => { throw new Error('boom from the test'); }, 0); }")
    # Let the page's own clock run the timer and the image attempt (no Python sleep).
    halaman.evaluate("() => new Promise((r) => setTimeout(r, 300))")
    galat = halaman.context.galat_uji  # the fixture's list, read back here
    assert any("boom from the test" in g for g in galat)
    assert not any("Failed to load resource" in g for g in galat)
    galat.clear()  # the fixture's teardown would otherwise fail this test on purpose


def test_the_seeded_accounts_can_sign_in(konsol):
    r = httpx.post(
        konsol.url + "/api/console/login",
        json={"email": "operator@demo.autoerp.test", "sandi": "sawit2026"},
    )
    assert r.status_code == 200, r.text


def test_the_harness_folder_is_outside_the_repo(konsol):
    repo = Path(__file__).resolve().parents[2]
    assert repo not in konsol.src.parents
