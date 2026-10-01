"""Integrasi layar Antrean line: JSON yang SUNGGUHAN keluar dari rantai line → konsol,
dibaca oleh `barisAntreanLine` yang SUNGGUHAN di console.html (lewat node).

Unit test merender data tulisan tangan. Yang dibuktikan di sini: nama field yang
dikeluarkan `AntreanLine` + `OutboxRetryWorker.status()` + `PantauAntreanLine`
sama dengan yang dibaca layar. Diganti di satu sisi saja = test ini merah, bukan
baris kosong di pabrik.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from antrean_line_rakit import (
    KabelKonsol,
    LinePerPort,
    app_ingest,
    app_konsol,
    klien_konsol_mati,
    masuk,
    rakit_line,
)
from konsol_js import kamus_asli

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SECRET = "kunci-internal-palsu"
LINES = (LineEndpoint("line-1", "Line 1", 8001, "m-1"), LineEndpoint("line-2", "Line 2", 8002, "m-2"))


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _render(lines: dict) -> dict:
    skrip = (
        'const esc = (s) => String(s ?? "").replace(/[&<>"\'`]/g, (c) =>'
        ' ({ "&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;","`":"&#96;" }[c]));\n'
        'const KOSONG = "-";\n'
        'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));\n'
        # The real KAMUS only decides which keys exist (`kunciSebabTakTerbaca`); `t` keeps
        # printing key names, so the asserts read which sentence was picked.
        + kamus_asli() + '\nconst bahasa = "id";\n'
        "const t = (k) => k;\n"
        + "\n".join(_fungsi(f) for f in (
            "kunciSebabTakTerbaca", "keadaanAntreanLine", "barisAntreanLine", "waktu", "lamaProses"))
        + f"\nconst lines = {json.dumps(lines)};\n"
        "console.log(JSON.stringify(Object.fromEntries(Object.entries(lines)"
        ".map(([k, d]) => [k, barisAntreanLine(k, d, Date.now())]))));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


def test_baris_dari_jawaban_sungguhan(tmp_path):
    line_1 = rakit_line(tmp_path / "line-1", internal_secret=SECRET, klien_konsol=klien_konsol_mati())
    line_2 = rakit_line(tmp_path / "line-2", internal_secret="kunci-lain", klien_konsol=klien_konsol_mati())
    line_1.store.add_event("e1", "m-1", {"event_id": "e1", "timestamp": "2026-09-20T03:00:00+00:00"})
    line_1.worker._flush_pending()  # konsol mati dilihat dari line-1
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8001: line_1.app, 8002: line_2.app}),
    )
    store = ConsoleStore(tmp_path / "console.db")
    client = masuk(app_konsol(store, PantauAntreanLine(klien, LINES)), store, role=ROLE_SUPPORT)

    baris = _render(client.get("/api/console/dev/antrean/line").json()["lines"])

    assert "antreanLinePutus_tak_terjangkau" in baris["line-1"]
    assert 'data-kirim-ulang-line="line-1"' in baris["line-1"]
    # The worker's raw error stays in the Log tab; the row only says when (2026-10-01).
    assert "antreanLineGalatTerakhir" in baris["line-1"] and "ConnectError" not in baris["line-1"]
    # `sebab_kode` from PantauAntreanLine is the field the screen reads.
    assert "lineSebab_kunci_ditolak" in baris["line-2"]
    assert "401" not in baris["line-2"] and "refused" not in baris["line-2"]
    assert "data-kirim-ulang-line" not in baris["line-2"]


def test_janjang_yang_ditolak_konsol_terbaca_ditolak_bukan_sedang_dikirim(tmp_path, caplog):
    """Final review konsol I1, seluruh rantai sungguhan: worker line → lane ingest konsol
    (menolak 400) → `OutboxStore` line → `/internal/outbox` → `LineClient` → rute layar →
    `barisAntreanLine`. Dulu baris itu terbaca "Sedang dikirim ke konsol" selamanya dan
    tab Log konsol tidak menyebut apa pun."""
    konsol = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), ConsoleStore(tmp_path / "ingest.db"), None)
    kabel = KabelKonsol(app_ingest(konsol))
    line_1 = rakit_line(
        tmp_path / "line-1", internal_secret=SECRET, klien_konsol=kabel.klien(),
        webhook_secret=konsol.settings.webhook_secret,
    )
    line_1.store.add_event("sah", "m-1", {"event_id": "sah", "machine_id": "m-1",
                                          "timestamp": "2026-09-20T03:00:00+00:00", "ripeness_status": "ACC"})
    line_1.store.add_event("rusak", "m-1", {"event_id": "rusak", "machine_id": "m-1",
                                            "timestamp": "bukan-jam", "ripeness_status": "ACC"})
    with caplog.at_level("WARNING", logger="palmgrade.services.console_service"):
        line_1.worker._flush_pending()
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8001: line_1.app}),
    )
    store = ConsoleStore(tmp_path / "console.db")
    client = masuk(app_konsol(store, PantauAntreanLine(klien, LINES[:1])), store, role=ROLE_SUPPORT)

    satu = client.get("/api/console/dev/antrean/line").json()["lines"]["line-1"]
    baris = _render({"line-1": satu})["line-1"]

    assert (satu["menunggu"], satu["ditolak"]) == (1, 1)
    assert satu["ditolak_alasan"].startswith("HTTP 400")
    assert "antreanLineDitolak" in baris and "antreanLineMengirim" not in baris
    assert [r for r in caplog.records if "rusak" in r.getMessage() and "DITOLAK konsol" in r.getMessage()]
