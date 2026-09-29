"""AutoERP tiruan untuk test konsol: `upsert_visit` dan `upsert_truck`.

Aturan disalin dari autoerp `erpnext/palm_mill/api.py` (dibaca 2026-09-29):

- `weighing.time_in` wajib (api.py:126-127): kosong atau `None` dijawab **417**
  `ValidationError`, seperti Frappe menjawab `frappe.throw`, bukan diam-diam diterima
  sebagai draft kosong dan bukan bikin fake ini crash;
- kunjungan yang membawa tara DAN grading difinalisasi saat itu juga (`try_finalize`);
- `_result()` selalu membawa `ticket`, `status`, `truck`. Jalur belum-final SELALU
  membawa `finalised` (`_result(ticket, truck_doc, finalised=finalised, stage=stage)`,
  api.py:158-159), walau nilainya `False`, dan `stage`; `_after_finalisation` TIDAK
  PERNAH membawa `finalised` (jawabannya `_result(ticket, truck, revised=..., note=...)`
  tanpa kwarg itu);
- `upsert_truck` (api.py:93-97) mengembalikan `name`, `supplier`, DAN `vehicle_class`;
- tiket final tidak pernah ditulis ulang (`_after_finalisation`): persen grading
  TERSIMPAN (`grading_percentages()`, dibulatkan 2 desimal, bukan `counts` mentah)
  yang beda → `revised: True` + note "grading revised"; bobot (bruto/tara) yang beda →
  note "weights revised" terpisah, dibandingkan dengan `flt(weighing.get("gross_kg"))`
  (api.py:270, jadi 0.0 kalau `gross_kg` tidak dikirim, BUKAN bruto yang tersimpan di
  tiket) dan `flt(weighing.get("tare_kg"))`; keduanya bisa digabung koma seperti
  `", ".join(notes)`; sama semua → note "ticket already finalised; visit unchanged",
  tanpa `revised`.

Dua mode rusak: `racun` (plat yang membuat handler crash, 500 dengan amplop galat
Frappe) dan `portal` (semua jawaban 200 HTML, seperti hotspot login atau `ERP_URL`
yang salah). Path atau method di luar `upsert_truck`/`upsert_visit` dijawab 404,
seperti Frappe menjawab rute yang tidak ada.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

_UPSERT_TRUCK = "erpnext.palm_mill.api.upsert_truck"
_UPSERT_VISIT = "erpnext.palm_mill.api.upsert_visit"


class AutoErpPalsu:
    def __init__(self) -> None:
        self.racun: set[str] = set()
        self.portal = False
        #: Setiap payload kunjungan yang sampai ke `upsert_visit`, urut kedatangan.
        self.diterima: list[dict[str, Any]] = []
        self._tiket: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.portal:
            return httpx.Response(200, text="<html><body>Login hotspot</body></html>")
        method = request.url.path.rsplit("/", 1)[-1]
        if request.method != "POST" or method not in (_UPSERT_TRUCK, _UPSERT_VISIT):
            return httpx.Response(404, json={"exc_type": "NotFound", "exception": "method not found"})
        body = json.loads(request.content or b"{}")
        plat = (body.get("truck") or {}).get("plate_number") or body.get("plate_number")
        if plat in self.racun:
            return httpx.Response(500, json={"exc_type": "KeyError", "exception": "KeyError: 'counts'"})
        if method == _UPSERT_VISIT:
            weighing = body.get("weighing") or {}
            if not weighing.get("time_in"):
                return httpx.Response(417, json={
                    "exc_type": "ValidationError",
                    "exception": "frappe.exceptions.ValidationError: weighing.time_in is required: "
                    "it dates the visit",
                })
            return httpx.Response(200, json={"message": self._kunjungan(body)})
        return httpx.Response(200, json={"message": {"name": plat, "supplier": None, "vehicle_class": None}})

    def _kunjungan(self, body: dict[str, Any]) -> dict[str, Any]:
        self.diterima.append(body)
        plat = (body.get("truck") or {}).get("plate_number") or body.get("plate_number")
        stage = body.get("stage")
        pct = _persen(body.get("grading") or {})
        weighing = body.get("weighing") or {}
        tiket = self._tiket.setdefault(
            body["visit_id"],
            {"name": f"WB-2026-{len(self._tiket) + 1:05d}", "final": False, "pct": None,
             "gross_kg": None, "tare_kg": None},
        )
        if tiket["final"]:
            return self._sesudah_final(tiket, plat, pct, weighing)
        if pct is not None:
            tiket["pct"] = pct
        if "gross_kg" in weighing:
            tiket["gross_kg"] = weighing["gross_kg"]
        if "tare_kg" in weighing:
            tiket["tare_kg"] = weighing["tare_kg"]
        finalised = tiket["pct"] is not None and tiket["tare_kg"] is not None
        if finalised:
            tiket["final"] = True
            status = "Finalised"
        else:
            status = "Waiting Weight" if tiket["pct"] is not None else "Waiting Grading"
        # `_result(ticket, truck_doc, finalised=finalised, stage=stage)`: SELALU dibawa
        # pada jalur ini, walau `finalised` bernilai False.
        return {"ticket": tiket["name"], "status": status, "truck": plat,
                "finalised": finalised, "stage": stage}

    def _sesudah_final(
        self, tiket: dict[str, Any], plat: str, pct: dict[str, float] | None, weighing: dict[str, Any]
    ) -> dict[str, Any]:
        """`_after_finalisation`: tiket final tidak pernah ditulis ulang, cuma dibandingkan.

        Bobot dibandingkan dengan `flt(weighing.get("gross_kg"))` /
        `flt(weighing.get("tare_kg"))` (api.py:270): field yang tidak dikirim jadi 0.0,
        bukan fallback ke bruto/tara yang tersimpan di tiket."""
        notes: list[str] = []
        if pct is not None and _bulat(pct) != _bulat(tiket["pct"] or {}):
            notes.append("grading revised")
        if weighing.get("tare_kg") is not None:
            lama = (_flt(tiket["gross_kg"]), _flt(tiket["tare_kg"]))
            baru = (_flt(weighing.get("gross_kg")), _flt(weighing.get("tare_kg")))
            if lama != baru:
                notes.append("weights revised")
        dasar = {"ticket": tiket["name"], "status": "Finalised", "truck": plat}
        if not notes:
            return {**dasar, "note": "ticket already finalised; visit unchanged"}
        return {**dasar, "revised": True, "note": "ticket already finalised; " + ", ".join(notes)}


def _persen(grading: dict[str, Any]) -> dict[str, float] | None:
    """`_grading_percentages`: `pct` kalau dikirim, kalau tidak turunan dari `counts`."""
    if not grading:
        return None
    pct = grading.get("pct") or {}
    counts = grading.get("counts") or {}
    total = counts.get("total") or 0
    kunci = ("mentah", "tangkai_panjang")

    def bagi(kunci: str) -> float:
        if kunci in pct:
            return float(pct[kunci])
        return float(counts.get(kunci) or 0) / total * 100 if total else 0.0

    return {k: bagi(k) for k in kunci}


def _bulat(pct: dict[str, float]) -> tuple[float, float]:
    """`grading_percentages()` menyimpan persen sudah dibulatkan 2 desimal
    (`round(persen, 2)` di `_apply_grading`); bandingkan dengan pembulatan yang sama."""
    return (round(pct.get("mentah", 0.0), 2), round(pct.get("tangkai_panjang", 0.0), 2))


def _flt(nilai: Any) -> float:
    """`frappe.utils.flt`: kosong/None jadi 0.0, tidak pernah fallback ke nilai lain."""
    return float(nilai) if nilai is not None else 0.0
