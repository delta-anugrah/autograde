"""AutoERP tiruan untuk test konsol: `upsert_visit` dan `upsert_truck`.

Aturan finalisasi disalin dari autoerp `erpnext/palm_mill/api.py` (dibaca 2026-09-28):

- kunjungan yang membawa tara DAN grading difinalisasi saat itu juga (`try_finalize`);
- tiket final tidak pernah ditulis ulang (`_after_finalisation`): grading berbeda →
  `revised: True` + note "ticket already finalised; grading revised", sama → note
  "ticket already finalised; visit unchanged".

Dua mode rusak: `racun` (plat yang membuat handler crash, 500 dengan amplop galat
Frappe) dan `portal` (semua jawaban 200 HTML, seperti hotspot login atau `ERP_URL`
yang salah).
"""
from __future__ import annotations

import json
from typing import Any

import httpx


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
        body = json.loads(request.content or b"{}")
        plat = (body.get("truck") or {}).get("plate_number") or body.get("plate_number")
        if plat in self.racun:
            return httpx.Response(500, json={"exc_type": "KeyError", "exception": "KeyError: 'counts'"})
        if request.url.path.endswith(".upsert_visit"):
            return httpx.Response(200, json={"message": self._kunjungan(body)})
        return httpx.Response(200, json={"message": {"name": plat, "supplier": None}})

    def _kunjungan(self, body: dict[str, Any]) -> dict[str, Any]:
        self.diterima.append(body)
        counts = (body.get("grading") or {}).get("counts")
        tiket = self._tiket.setdefault(
            body["visit_id"],
            {"name": f"WB-2026-{len(self._tiket) + 1:05d}", "final": False, "counts": None},
        )
        if tiket["final"]:
            if counts != tiket["counts"]:
                return {"ticket": tiket["name"], "status": "Finalised", "revised": True,
                        "note": "ticket already finalised; grading revised"}
            return {"ticket": tiket["name"], "status": "Finalised",
                    "note": "ticket already finalised; visit unchanged"}
        tiket["counts"] = counts
        if counts and "tare_kg" in body.get("weighing", {}):
            tiket["final"] = True
            return {"ticket": tiket["name"], "status": "Finalised", "finalised": True}
        return {"ticket": tiket["name"], "status": "Waiting Weight" if counts else "Waiting Grading"}
