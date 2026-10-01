"""The harness itself: isolated from the developer's machine, loud when it breaks.

These hold the promises every other browser test leans on: a developer's console, lines
and `.env` stay untouched, a console that cannot start says why within its time limit,
teardown frees what it started, and the page guard catches script and server errors in its
own call while ignoring a refused camera feed.
"""

from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path

import harness
import httpx
import psutil
import pytest
from harness import PORT_DEVELOPER, KonsolUji, jalankan_terbatas, port_bebas
from langkah import JEDA_HALAMAN_MS  # skips this module where Playwright is missing, fails in CI
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


def test_the_console_runs_from_its_own_folder(konsol):
    # python-dotenv falls back to the working directory under a debugger or coverage, and
    # the working directory of pytest is the checkout, under the developer's `.env`.
    assert Path(psutil.Process(konsol.pid).cwd()).resolve() == konsol.root.resolve()


_MACET = """
import subprocess, sys, time
print("sudah mulai", flush=True)
anak = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(str(anak.pid))
time.sleep(60)
"""
_TUNGGU_MATI_S = 5


def test_a_command_that_hangs_is_stopped_with_its_children_and_says_what_it_printed(tmp_path):
    # A probe or seeder that hangs must not leave its console or browser driver behind.
    berkas_pid = tmp_path / "anak.pid"
    with pytest.raises(RuntimeError, match="sudah mulai"):
        jalankan_terbatas([sys.executable, "-c", _MACET, str(berkas_pid)], batas_s=2)
    try:
        # Raises psutil.TimeoutExpired, failing the test, while the child is still alive.
        psutil.Process(int(berkas_pid.read_text())).wait(timeout=_TUNGGU_MATI_S)
    except psutil.NoSuchProcess:
        pass  # already gone, which is the point


def test_a_seeder_that_hangs_says_what_it_printed(tmp_path, monkeypatch):
    k = KonsolUji(tmp_path, port_line=(port_bebas(), port_bebas(), port_bebas()))
    (k.root / "scripts" / "seed-console-demo.py").write_text(
        "import time\nprint('seeder macet di sini', flush=True)\ntime.sleep(60)\n"
    )
    monkeypatch.setattr(harness, "SEED_MAKS_S", 2)
    with pytest.raises(RuntimeError, match="seeder macet di sini"):
        k.seed(hari=1)


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
    halaman.evaluate("(ms) => new Promise((r) => setTimeout(r, ms))", JEDA_HALAMAN_MS)
    galat = halaman.context.galat_uji  # the fixture's list, read back here
    assert any("boom from the test" in g for g in galat)
    assert not any("Failed to load resource" in g for g in galat)
    galat.clear()  # the guard would otherwise fail this test on purpose


def test_a_server_error_from_the_console_fails_the_guard(halaman, konsol):
    # Firefox logs nothing for a 500 and Chromium words it like a refused feed, so the
    # guard reads the status itself. The 500 is staged by Playwright, not by the console.
    halaman.route(konsol.url + "/api/console/galat-uji", lambda route: route.fulfill(status=500))
    halaman.evaluate("() => fetch('/api/console/galat-uji')")
    galat = halaman.context.galat_uji
    assert any("500" in g and "/api/console/galat-uji" in g for g in galat), galat
    galat.clear()


_PROBE = Path(__file__).with_name("probe_penjaga.py")
_PROBE_MAKS_S = 180


def test_a_guard_trip_fails_the_test_itself_not_its_teardown(tmp_path, browser_name):
    # pytest-playwright empties its output folder when a session starts; the probe's own
    # session must not empty the outer run's, where CI keeps the traces of earlier failures.
    jejak_luar = Path.cwd() / "test-results" / "probe-penjaga-penanda" / "trace.zip"
    jejak_luar.parent.mkdir(parents=True, exist_ok=True)
    jejak_luar.write_bytes(b"")
    # Through `jalankan_terbatas`: a hung probe must not leave its own console running.
    hasil = jalankan_terbatas(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_PROBE),
            "-o",
            "addopts=",  # the repo's own `-q` would make this `-qq`, which drops the summary
            "-q",
            "-rN",
            "--color=no",
            "-p",
            "no:cacheprovider",
            "--browser",
            browser_name,
            "--basetemp",
            str(tmp_path / "probe"),
            "--output",
            str(tmp_path / "probe-hasil"),
        ],
        batas_s=_PROBE_MAKS_S,
    )
    ringkasan = hasil.stdout.strip().splitlines()[-1]
    assert "1 failed" in ringkasan and "error" not in ringkasan, hasil.stdout[-2000:]
    assert jejak_luar.is_file(), "the probe emptied the outer run's test-results"
    shutil.rmtree(jejak_luar.parent)


def test_the_seeded_accounts_can_sign_in(konsol):
    r = httpx.post(
        konsol.url + "/api/console/login",
        json={"email": "operator@demo.autoerp.test", "sandi": "sawit2026"},
    )
    assert r.status_code == 200, r.text


def test_the_harness_folder_is_outside_the_repo(konsol):
    repo = Path(__file__).resolve().parents[2]
    assert repo not in konsol.src.parents
