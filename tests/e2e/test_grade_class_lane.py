"""End-to-end: satu janjang 4-kelas lewat lane konsol yang sungguhan.

App konsol sungguhan lewat HTTP (TestClient), DB SQLite sungguhan, kontrak §5
yang sama dengan yang dipakai line. Tanpa AutoERP: yang diuji di sini justru
BATAS-nya — apa yang naik ke ERP dan apa yang berhenti di edge — dan itu bisa
dibuktikan dari bentuk payload tanpa Frappe hidup.

Yang dijaga berkas ini, dan kenapa tiap satunya penting:

- JK masuk sebagai JK tapi dihitung REJ. Kalau verdict-nya ikut jadi "JK", PLC
  tidak akan mengenalinya (`_coil_for` cuma tahu acc/rej) dan janjang kosong
  lewat begitu saja ke pabrik.
- `jk` TIDAK PERNAH ada di pesan AutoERP. Tidak ada kriterianya di sana; yang
  bocor akan ditolak Frappe (417) atau, lebih buruk, diam-diam menggeser angka
  yang dibayar ke petani.
- Baris tanpa kelas (capture manual, line versi lama) tetap tercatat utuh.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.erp_messages import visit_message
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.services.console_service import ConsoleService

SECRET = "e2e-secret"
ASSIGNMENT = "a-e2e-1"


class _LineDiam:
    """Line tidak dipanggil di alur ini; ada supaya service bisa dirakit."""

    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


@pytest.fixture()
def klien(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    settings = Settings()
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(settings, store, _LineDiam())

    app = FastAPI()
    app.include_router(console_routes.router)
    # Lane mesin punya router sendiri dan prefix versi, persis seperti
    # console_main.py merakitnya. Tanpa prefix ini ingest-nya 404.
    app.include_router(console_routes.ingest_router, prefix=settings.backend_api_ver)
    # App dirakit sendiri, BUKAN create_console_app(): yang itu menyentuh
    # state/console.db milik developer (CLAUDE.md § Tests).
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    with TestClient(app) as c:
        yield c, service, settings


def _kirim(klien, *, grade_class, verdict, menit_lalu=1, tp=None):
    c, service, settings = klien
    ts = datetime.now(UTC) - timedelta(minutes=menit_lalu)
    body = {
        "event_id": str(uuid.uuid4()),
        "machine_id": service.lines[0].machine_id,
        "timestamp": ts.isoformat(),
        "prediction": "Acc" if verdict == "ACC" else "Rej",
        "ripeness_status": verdict,
        "ripeness_confidence": 0.9,
        "capture_type": "auto",
        "assignment_id": ASSIGNMENT,
        "image_path": f"captures/results/{ts:%Y-%m-%d}/x.webp",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
    }
    if grade_class is not None:
        body["grade_class"] = grade_class
    if tp is not None:
        body["tp_status"], body["tp_confidence"] = "PASS", tp
    r = c.post(
        f"{settings.backend_api_ver}/internal/vision/events",
        json=body,
        headers={"x-webhook-secret": SECRET},
    )
    assert r.status_code in (200, 201), r.text
    return body["event_id"], r.json()["work_date"]


def test_janjang_jk_masuk_sebagai_jk_tapi_dihitung_rej(klien):
    """Kelas dan verdict dua hal berbeda, dan keduanya harus selamat sampai DB."""
    _, service, _ = klien
    _kirim(klien, grade_class="JK", verdict="REJ")

    counts = service.store.grading_counts(ASSIGNMENT)
    assert counts["jk"] == 1
    assert counts["rej"] == 1, "JK harus ikut terhitung REJ — itu yang dibuang piston"
    assert counts["acc"] == 0


def test_empat_kelas_menjumlah_persis_total(klien):
    _, service, _ = klien
    for kelas, verdict in (
        ("Ripe", "ACC"), ("Ripe", "ACC"), ("Unripe", "REJ"), ("JK", "REJ"),
    ):
        _kirim(klien, grade_class=kelas, verdict=verdict)

    c = service.store.grading_counts(ASSIGNMENT)
    assert (c["ripe"], c["unripe"], c["jk"]) == (2, 1, 1)
    assert c["ripe"] + c["unripe"] + c["jk"] == c["total"] == 4
    assert (c["acc"], c["rej"]) == (2, 2)


def test_pesan_autoerp_tidak_pernah_membawa_jk(klien):
    """Batas yang paling mahal kalau jebol: `jk` bukan kriteria AutoERP."""
    _, service, _ = klien
    _kirim(klien, grade_class="Unripe", verdict="REJ")
    _kirim(klien, grade_class="JK", verdict="REJ")
    _kirim(klien, grade_class="Ripe", verdict="ACC")

    counts = service.store.grading_counts(ASSIGNMENT)
    _, payload = visit_message(
        {
            "id": "v-e2e",
            "plate_number": "BE 8821 KL",
            "truck_id": "t-1",
            "entered_at": datetime.now(UTC).isoformat(),
        },
        counts,
        site="PKS-E2E",
        emitted_at=datetime.now(UTC).isoformat(),
    )
    dikirim = payload["grading"]["counts"]
    assert "jk" not in dikirim
    assert "ripe" not in dikirim and "unripe" not in dikirim
    # Mentah = seluruh REJ, JK termasuk di dalamnya.
    assert dikirim["mentah"] == dikirim["rej"] == 2


def test_tp_terhitung_dengan_ambang_yang_sama_dengan_erp(klien):
    """Layar dan buku besar harus memakai satu ambang (> 0.8); kalau beda,
    operator melapor 'selisih' yang sebenarnya dua aturan."""
    _, service, _ = klien
    _, hari = _kirim(klien, grade_class="Ripe", verdict="ACC", tp=0.95)
    _kirim(klien, grade_class="Ripe", verdict="ACC", tp=0.5)

    counts = service.store.grading_counts(ASSIGNMENT)
    # Hari kerja JANJANGNYA, bukan `service.today()`: janjang distempel semenit
    # lalu, jadi tes yang jalan tepat sesudah tengah malam membandingkan dua hari
    # yang berbeda dan gagal tanpa ada yang rusak. Persis jebakan tanggal keras
    # yang sudah kena sekali di `test_scan_qr_lane.py` (PR #95).
    layar = service.store.summary(hari)
    assert counts["tangkai_panjang"] == 1
    assert sum(r["tp"] or 0 for r in layar) == counts["tangkai_panjang"]


def test_baris_tanpa_kelas_tetap_tercatat(klien):
    """Capture manual tidak pernah lewat model, dan line versi lama belum
    mengirim kolom ini. Dua-duanya janjang sungguhan yang harus tetap dihitung."""
    _, service, _ = klien
    _kirim(klien, grade_class=None, verdict="ACC")

    counts = service.store.grading_counts(ASSIGNMENT)
    assert counts["total"] == 1
    assert counts["acc"] == 1
    assert counts["ripe"] == 0, "tidak ditebak dari verdict — kelasnya memang tidak diketahui"


def test_kelas_asing_tidak_menjatuhkan_janjang(klien):
    """Model yang dilatih ulang boleh memunculkan nama baru. Menolak event-nya
    berarti kehilangan tonase sungguhan demi sebuah label."""
    _, service, _ = klien
    _kirim(klien, grade_class="Overripe", verdict="REJ")

    counts = service.store.grading_counts(ASSIGNMENT)
    assert counts["total"] == 1 and counts["rej"] == 1


def test_verdict_asing_tetap_ditolak_400(klien):
    """Kebalikan dari kelas: ini angka yang dibayar, jadi harus berhenti di pintu."""
    c, service, settings = klien
    ts = datetime.now(UTC)
    r = c.post(
        f"{settings.backend_api_ver}/internal/vision/events",
        json={
            "event_id": str(uuid.uuid4()),
            "machine_id": service.lines[0].machine_id,
            "timestamp": ts.isoformat(),
            "ripeness_status": "JK",  # kelas, bukan verdict — tidak boleh lolos
            "prediction": "Rej",
            "capture_type": "auto",
            "image_path": "captures/results/x.webp",
        },
        headers={"x-webhook-secret": SECRET},
    )
    assert r.status_code == 400
