"""End-to-end: garis capture disetel dari konsol, sampai ke line, lalu memicu.

Unit test membuktikan aturannya benar dan render test membuktikan garisnya
tergambar. Yang belum terbukti di keduanya adalah rantai yang menghubungkannya,
dan rantai itu punya tiga sambungan yang masing-masing pernah jadi sumber bug di
repo ini:

1. **Layar → konsol**: field baru yang tidak ikut divalidasi akan tersimpan
   mentah dan mengirim nilai cacat ke tiga line sekaligus.
2. **Konsol → line**: `kirim_setelan` yang lupa membawa field baru membuat
   layar bilang "tersimpan" sementara line tetap memakai nilai lama — salah yang
   paling mahal, karena tidak terlihat di mana pun.
3. **Line → deteksi**: override yang tersimpan tapi tidak dibaca per frame
   membuat setelan cuma berlaku sesudah restart, padahal janjinya tanpa restart.

Konsol dirakit sendiri di sini lewat `TestClient` dengan store SQLite sungguhan,
sama seperti `test_console_autoerp.py` — bukan `create_console_app()`, yang akan
menyentuh `state/console.db` milik developer.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.garis_capture import menyentuh_garis, skala_garis_ke_frame
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.services.console_service import ConsoleService

SECRET = "e2e-secret"


class _LineMerekam:
    """Berdiri sebagai tiga line: mencatat apa yang benar-benar dikirim konsol."""

    def __init__(self) -> None:
        self.setelan: list[dict] = []

    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...

    async def kirim_setelan(self, line, **kw) -> dict:
        self.setelan.append({"line_code": line.line_code, **kw})
        return kw


@pytest.fixture()
def konsol(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    settings = Settings()
    store = ConsoleStore(tmp_path / "console.db")
    line = _LineMerekam()
    service = ConsoleService(settings, store, line)

    app = FastAPI()
    app.include_router(console_routes.router)
    app.include_router(console_routes.ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    # Layar setelan cuma untuk `support`; yang diuji di sini rantai datanya,
    # bukan penjaganya (itu punya test sendiri).
    app.dependency_overrides[console_routes.require_support] = lambda: {
        "email": "support@test", "role": "support"
    }
    with TestClient(app) as c:
        yield c, service, line


def test_the_line_setting_reaches_every_line(konsol):
    """Sambungan yang paling mahal kalau putus: layar bilang tersimpan, line diam."""
    c, _service, line = konsol

    res = c.post(
        "/api/console/dev/setelan",
        json={"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": 900},
    )

    assert res.status_code == 200, res.text
    assert res.json()["garis_capture"] == 900
    assert line.setelan, "tidak satu pun line dikirimi setelan"
    assert all(s["garis_capture"] == 900 for s in line.setelan), line.setelan


def test_the_setting_survives_a_line_restart(konsol):
    """Line yang dibuat ulang menanyakan setelan lewat `/internal/setelan`.

    Tanpa ini, satu `docker compose up` di tengah shift diam-diam mengembalikan
    garis ke nilai `.env` dan tidak ada yang tahu sampai tonase terlihat aneh.
    """
    c, _service, _line = konsol
    c.post(
        "/api/console/dev/setelan",
        json={"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": 900},
    )

    res = c.get("/api/v1/internal/setelan", headers={"x-webhook-secret": SECRET})

    assert res.status_code == 200, res.text
    assert res.json()["garis_capture"] == 900
    assert res.json()["sumber"] == "konsol"


def test_a_console_that_never_set_it_answers_a_number(konsol):
    """PKS yang belum menyetel harus dapat ANGKA, bukan `null` atau field hilang.

    `bersihkan_setelan` di sisi line akan menolak `null`, dan line yang menolak
    setelan berhenti menerima dua setelan lain yang sudah lama jalan.

    Angkanya sendiri datang dari `Settings.garis_capture` — dulu 0, sekarang
    200 (lihat `tests/unit/test_garis_capture_default.py`). Yang dijaga di sini
    bentuk jawabannya, bukan nilainya: mengunci angka tertentu membuat test ini
    merah tiap kali bawaan digeser, tanpa ada yang benar-benar rusak.
    """
    c, service, _line = konsol

    res = c.get("/api/v1/internal/setelan", headers={"x-webhook-secret": SECRET})

    nilai = res.json()["garis_capture"]
    assert isinstance(nilai, int), nilai
    assert nilai == service.settings.garis_capture


def test_an_out_of_range_line_is_refused_before_it_reaches_the_lines(konsol):
    """Garis di x=99999 tidak akan pernah disentuh janjang mana pun."""
    c, _service, line = konsol

    res = c.post(
        "/api/console/dev/setelan",
        json={"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": 99999},
    )

    assert res.status_code == 400, res.text
    assert line.setelan == [], "nilai cacat sempat dikirim ke line"


def test_an_older_console_payload_is_still_accepted(konsol):
    """Konsol yang belum di-update tidak boleh membuat line berhenti disetel."""
    c, _service, line = konsol

    res = c.post(
        "/api/console/dev/setelan",
        json={"conf_threshold": 0.5, "minimum_size": 3000},
    )

    assert res.status_code == 200, res.text
    assert res.json()["garis_capture"] == 0
    assert all(s["garis_capture"] == 0 for s in line.setelan)


# ------------------------------------------------- sisi line: pemicunya


def test_the_bunch_is_only_photographed_once_it_touches_the_line():
    """Perjalanan satu janjang melintasi garis, frame demi frame.

    Ini yang membedakan aturan baru dari yang lama: dengan titik tengah, janjang
    pada frame ke-2 di bawah sudah difoto — separuh panjang janjang lebih awal.
    """
    garis = 800
    # Janjang lebar 200 px bergerak kanan → kiri, 100 px per frame.
    perjalanan = [(1000, 1200), (900, 1100), (800, 1000), (700, 900), (500, 700)]
    dipicu = [menyentuh_garis(x1=x1, x2=x2, garis_x=garis) for x1, x2 in perjalanan]

    assert dipicu == [False, False, True, True, False], dipicu

    # Frame ke-3 (indeks 2) adalah saat tepi KIRI — ujung depan janjang —
    # menyentuh garis di 800. Itu momen yang diminta operator.
    assert dipicu.index(True) == 2
    assert perjalanan[2][0] == garis, "pemicunya tepi kiri menyentuh garis"

    # Bandingkan dengan aturan LAMA (titik tengah): janjang di (900,1100) punya
    # titik tengah 1000, dan dengan ROI penuh layar dia sudah difoto sejak frame
    # pertama — dua frame lebih awal, dan pada ROI penuh layar bahkan sebelum
    # mendekati garis sama sekali.
    tengah_frame_pertama = (perjalanan[0][0] + perjalanan[0][1]) // 2
    assert tengah_frame_pertama > garis, (
        "aturan lama memfoto janjang ini jauh sebelum menyentuh garis"
    )


def test_the_line_is_scaled_from_the_screen_to_the_sensor_frame():
    """Jebakan yang sudah pernah memakan korban di ROI (commit bdcb300).

    Operator menyetel 900 dari layar 1280 px; deteksi jalan di frame 2448 px.
    Tanpa penskalaan, garis mendarat di sepertiga kiri frame dan janjang difoto
    jauh lebih lambat dari yang terlihat — tanpa satu pun pesan.
    """
    di_sensor = skala_garis_ke_frame(900, stream_width=1280, frame_width=2448)

    assert di_sensor == 1721
    # Janjang yang di layar tepat menyentuh garis, harus memicu juga di sensor.
    assert menyentuh_garis(x1=1700, x2=2000, garis_x=di_sensor) is True
