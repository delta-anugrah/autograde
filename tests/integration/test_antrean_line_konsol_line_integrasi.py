"""Konsol dan line untuk tab Status → Antrean line: rute konsol, `LineClient`, dan router
`/internal/outbox*` line yang SUNGGUHAN, disambung transport ASGI in-process (satu app
per port). Kunci `INTERNAL_SECRET` yang beda dibuktikan terbaca "menolak", bukan mati.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from antrean_line_rakit import LinePerPort, app_konsol, klien_konsol_mati, masuk, rakit_line
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

SECRET = "kunci-internal-palsu"
LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")
LINE_3 = LineEndpoint("line-3", "Line 3", 8003, "m-3")  # tidak punya app: mati
TS = "2026-09-20T03:00:00+00:00"


@pytest.fixture
def rakit(tmp_path):
    def _rakit(*, secret_line_2: str = SECRET):
        line_1 = rakit_line(tmp_path / "line-1", internal_secret=SECRET, klien_konsol=klien_konsol_mati())
        line_2 = rakit_line(tmp_path / "line-2", internal_secret=secret_line_2, klien_konsol=klien_konsol_mati())
        klien = LineClient(
            replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
            transport=LinePerPort({8001: line_1.app, 8002: line_2.app}),
        )
        store = ConsoleStore(tmp_path / "console.db")
        app = app_konsol(store, PantauAntreanLine(klien, (LINE_1, LINE_2, LINE_3)))
        return masuk(app, store, role=ROLE_SUPPORT), line_1, line_2

    return _rakit


def _mundur(line) -> None:
    line.store.add_event("e1", "m", {"event_id": "e1", "timestamp": TS})
    for row in line.store.get_pending():
        line.store.mark_failed_attempt(row["id"], "putus")


def test_support_melihat_antrean_tiap_line(rakit):
    client, line_1, _ = rakit()
    line_1.store.add_event("e1", "m-1", {"event_id": "e1", "timestamp": TS})
    line_1.worker._flush_pending()  # konsol mati dilihat dari line-1

    isi = client.get("/api/console/dev/antrean/line").json()["lines"]

    satu = isi["line-1"]
    assert (satu["terjangkau"], satu["menunggu"], satu["tertua_at"]) == (True, 1, 1789873200.0)
    assert (satu["tersambung"], satu["sebab_putus"]) == (False, "tak_terjangkau")
    assert "ConnectError" in satu["galat"]
    assert (isi["line-2"]["terjangkau"], isi["line-2"]["menunggu"]) == (True, 0)


def test_kunci_internal_beda_terbaca_line_menolak_bukan_offline(rakit):
    """Review focus 5: line hidup dan mungkin masih mengirim janjang lewat
    WEBHOOK_SECRET; yang beda cuma kunci perintah konsol ke line."""
    client, *_ = rakit(secret_line_2="kunci-lain")

    isi = client.get("/api/console/dev/antrean/line").json()["lines"]

    assert (isi["line-2"]["terjangkau"], isi["line-2"]["kode"], isi["line-2"]["status"]) == (False, "line_menolak", 401)
    assert isi["line-1"]["terjangkau"] is True


def test_line_versi_lama_tanpa_lane_antrean_terbaca_dengan_status_http(tmp_path):
    """Line image lama (belum punya `/internal/outbox`) menjawab 404: baris membawa
    statusnya supaya layar bisa bilang "line menjawab HTTP 404", bukan sekadar mati."""
    line_1 = rakit_line(tmp_path / "line-1", internal_secret=SECRET, klien_konsol=klien_konsol_mati())
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8001: line_1.app, 8002: FastAPI()}),
    )
    store = ConsoleStore(tmp_path / "console.db")
    client = masuk(app_konsol(store, PantauAntreanLine(klien, (LINE_1, LINE_2))), store, role=ROLE_SUPPORT)

    isi = client.get("/api/console/dev/antrean/line").json()["lines"]

    assert (isi["line-2"]["terjangkau"], isi["line-2"]["kode"], isi["line-2"]["status"]) == (
        False, "line_tidak_menjawab", 404,
    )
    assert isi["line-1"]["terjangkau"] is True


def test_line_mati_terbaca_tidak_menjawab(rakit):
    client, *_ = rakit()

    isi = client.get("/api/console/dev/antrean/line").json()["lines"]

    assert (isi["line-3"]["terjangkau"], isi["line-3"]["kode"]) == (False, "line_tidak_menjawab")


def test_kirim_ulang_menjadwalkan_antrean_line_itu_saja(rakit):
    client, line_1, line_2 = rakit()
    _mundur(line_1)
    _mundur(line_2)

    jawab = client.post("/api/console/dev/antrean/line/line-1/kirim-ulang")

    assert (jawab.status_code, jawab.json()) == (200, {"line_code": "line-1", "dijadwalkan": 1})
    assert [r["event_id"] for r in line_1.store.get_pending()] == ["e1"]
    assert line_2.store.get_pending() == []


def test_kirim_ulang_ke_line_yang_menolak_kunci_502_line_menolak(rakit):
    client, _, line_2 = rakit(secret_line_2="kunci-lain")
    _mundur(line_2)

    jawab = client.post("/api/console/dev/antrean/line/line-2/kirim-ulang")

    assert jawab.status_code == 502
    detail = jawab.json()["detail"]
    assert (detail["code"], detail["params"]["status"]) == ("line_menolak", 401)
    assert line_2.store.get_pending() == []
