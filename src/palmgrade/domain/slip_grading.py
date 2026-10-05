"""Printable grading slip per truck (batch 5.9): what the slip says, as pure functions.

The rate follows the binary verdict, like the Rekap tab and the piston (`acc / total`), not
`ripe / total`: rows written before `grade_class` existed only carry the verdict. The net
weight is the sum of the truck's tickets that working day (a truck may hold more than one);
no ticket with a net weight = `None`, never 0, because 0 kg reads as a real weighing.
"""
from __future__ import annotations

from typing import Any

#: Where the switch lives in `sync_state` ("1" = on). Off on a new install. The `setelan_`
#: prefix keeps it through the Danger Zone wipes, like every other setting (`domain/bahaya.py`).
KUNCI_SLIP = "setelan_slip_cetak"

_KELAS = ("ripe", "unripe", "jk", "tp", "tanpa_kelas", "total")


def rasio_ripe_persen(acc: int, total: int) -> float | None:
    """Accepted share in percent, one decimal; None when nothing was graded."""
    return round(acc / total * 100, 1) if total else None


def _neto(tiket: list[dict[str, Any]]) -> float | None:
    angka = [t["net_kg"] for t in tiket if t.get("net_kg") is not None]
    return round(sum(angka), 3) if angka else None


def susun_slip(
    rekap: dict[str, Any], tiket: list[dict[str, Any]], *, work_date: str, perusahaan: str
) -> dict[str, Any]:
    """One truck's slip from its recap row and its tickets of that working day."""
    return {
        "perusahaan": perusahaan,
        "work_date": work_date,
        "truck_id": rekap.get("truck_id"),
        "plate_number": rekap.get("plate_number"),
        "supplier_name": rekap.get("supplier_name"),
        "source_label": rekap.get("source_label"),
        "mulai": rekap.get("started_at"),
        "selesai": rekap.get("ended_at"),
        "kelas": {k: int(rekap.get(k) or 0) for k in _KELAS},
        "rasio_ripe": rasio_ripe_persen(int(rekap.get("acc") or 0), int(rekap.get("total") or 0)),
        "neto_kg": _neto(tiket),
        "tiket": [
            {"bruto_kg": t.get("gross_kg"), "tara_kg": t.get("tare_kg"), "neto_kg": t.get("net_kg"),
             "masuk": t.get("entered_at"), "keluar": t.get("exited_at")}
            for t in tiket
        ],
    }
