"""Pins `tests/autoerp_palsu.py` (batch 2.7 round 1 fix) against the real rules in
autoerp `erpnext/palm_mill/api.py` (`_after_finalisation`, `_result`, `_find_ticket`),
read 2026-09-28. Task 5 relies on this fake matching AutoERP closely, so it is tested
directly rather than only through the console tests that happen to exercise it.
"""
from __future__ import annotations

import json

import httpx
from autoerp_palsu import AutoErpPalsu

UPSERT_TRUCK = "/api/method/erpnext.palm_mill.api.upsert_truck"
UPSERT_VISIT = "/api/method/erpnext.palm_mill.api.upsert_visit"


def _post(erp: AutoErpPalsu, path: str, body: dict) -> httpx.Response:
    request = httpx.Request("POST", f"http://erp.local{path}", json=body)
    return erp(request)


def _visit(visit_id: str, *, tare_kg=None, mentah=None, tangkai=None, plate="BE 1 AA") -> dict:
    weighing = {"time_in": "2026-09-28 08:00:00"}
    if tare_kg is not None:
        weighing["tare_kg"] = tare_kg
    body = {"visit_id": visit_id, "truck": {"plate_number": plate}, "weighing": weighing}
    if mentah is not None:
        body["grading"] = {"counts": {"total": 100}, "pct": {"mentah": mentah, "tangkai_panjang": tangkai or 0}}
    return body


def test_bentuk_jawaban_sama_dengan_result_di_autoerp():
    """`_result()` selalu membawa ticket, status, truck. `finalised` cuma di jalur
    pertama kali finalisasi (`_result(ticket, truck_doc, finalised=finalised, stage=stage)`),
    tidak pernah dibawa `_after_finalisation`."""
    erp = AutoErpPalsu()

    belum = _post(erp, UPSERT_VISIT, _visit("v1")).json()["message"]
    assert set(belum) >= {"ticket", "status", "truck"}
    assert belum["status"] == "Waiting Grading"
    assert "finalised" not in belum

    final = _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=10, tangkai=5)).json()["message"]
    assert final["finalised"] is True
    assert final["truck"] == "BE 1 AA"

    lagi = _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=10, tangkai=5)).json()["message"]
    assert "finalised" not in lagi
    assert lagi["note"] == "ticket already finalised; visit unchanged"


def test_revised_dibandingkan_persen_dibulatkan_bukan_counts_mentah():
    """AutoERP membandingkan `grading_percentages()` (persen tersimpan, dibulatkan 2
    desimal), bukan `counts` mentah. Dua kiriman dengan counts total beda tapi persen
    sama (dibulatkan) harus dibaca 'visit unchanged', bukan 'revised'."""
    erp = AutoErpPalsu()
    _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=33.333, tangkai=0))

    body = _visit("v1", tare_kg=1000, mentah=33.333, tangkai=0)
    body["grading"]["counts"]["total"] = 999  # counts berbeda, persen (dibulatkan) sama
    jawab = _post(erp, UPSERT_VISIT, body).json()["message"]

    assert jawab["note"] == "ticket already finalised; visit unchanged"
    assert "revised" not in jawab


def test_grading_revised_setelah_final_ditandai():
    erp = AutoErpPalsu()
    _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=10, tangkai=0))

    jawab = _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=20, tangkai=0)).json()["message"]

    assert jawab["revised"] is True
    assert jawab["note"] == "ticket already finalised; grading revised"


def test_weights_revised_setelah_final_ditandai():
    """Bobot yang berubah sesudah final (bruto/tara) dilaporkan 'weights revised',
    berbeda pesan dari 'grading revised', persis seperti dua `notes.append` terpisah
    di `_after_finalisation`."""
    erp = AutoErpPalsu()
    _post(erp, UPSERT_VISIT, _visit("v1", tare_kg=1000, mentah=10, tangkai=0))

    body = _visit("v1", tare_kg=1500, mentah=10, tangkai=0)
    jawab = _post(erp, UPSERT_VISIT, body).json()["message"]

    assert jawab["revised"] is True
    assert "weights revised" in jawab["note"]


def test_path_yang_bukan_upsert_dijawab_404():
    erp = AutoErpPalsu()

    jawab = _post(erp, "/api/method/erpnext.palm_mill.api.set_language", {"lang": "id"})

    assert jawab.status_code == 404


def test_method_yang_bukan_post_dijawab_404():
    erp = AutoErpPalsu()

    jawab = erp(httpx.Request("GET", f"http://erp.local{UPSERT_VISIT}"))

    assert jawab.status_code == 404


def test_weighing_none_tidak_membuat_crash():
    erp = AutoErpPalsu()
    body = {"visit_id": "v1", "truck": {"plate_number": "BE 1 AA"}, "weighing": None}

    jawab = _post(erp, UPSERT_VISIT, body)

    assert jawab.status_code == 200


def test_racun_tetap_didahulukan_sebelum_bentuk_jawaban_lain():
    erp = AutoErpPalsu()
    erp.racun.add("RACUN")

    jawab = _post(erp, UPSERT_VISIT, _visit("v1", plate="RACUN"))

    assert jawab.status_code == 500
    assert json.loads(jawab.content)["exc_type"] == "KeyError"


def test_portal_tetap_didahulukan_sebelum_bentuk_jawaban_lain():
    erp = AutoErpPalsu()
    erp.portal = True

    jawab = _post(erp, UPSERT_VISIT, _visit("v1"))

    assert jawab.status_code == 200
    assert "Login hotspot" in jawab.text
