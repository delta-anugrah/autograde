"""Setiap lane operator konsol butuh sesi, kecuali lima yang memang terbuka.

Penjaga umum, bukan per rute: `/piston` lolos tanpa sesi berbulan-bulan karena
satu-satunya rute yang lupa `Operator` (audit 2026-09-28).
"""
from __future__ import annotations

from palmgrade.routes.console import require_operator, router

TERBUKA = {
    ("GET", "/console"),
    ("GET", "/api/console/operators"),
    ("POST", "/api/console/login"),
    ("POST", "/api/console/logout"),
    # Bundled stock photos for DEMO_MODE only: 404 on every factory console, never data.
    ("GET", "/demo/{nama}"),
}


def _butuh_sesi(dependant) -> bool:
    return any(d.call is require_operator or _butuh_sesi(d) for d in dependant.dependencies)


def test_setiap_lane_operator_butuh_sesi():
    bolong = [
        (sorted(r.methods)[0], r.path)
        for r in router.routes
        if (sorted(r.methods)[0], r.path) not in TERBUKA and not _butuh_sesi(r.dependant)
    ]
    assert bolong == []
