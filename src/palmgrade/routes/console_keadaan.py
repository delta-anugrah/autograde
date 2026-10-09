"""`GET /api/console/state`, the screen's 2 s poll. Included by `routes/console.py`.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). Included where the route stood, so `console.router`
keeps its order (`tests/unit/test_console_router_peta.py`).
"""
from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from .console_deps import DemoMode, Dev, Operator, Pembaruan, Service, Slip

keadaan_router = APIRouter(tags=["console"])


@keadaan_router.get("/api/console/state")
async def console_state(
    service: Service, dev: Dev, pembaruan: Pembaruan, slip: Slip, operator: Operator,
    demo_mode: DemoMode,
) -> dict:
    """Ringkasan hari kerja, plus keadaan langganan untuk banner operator.

    Menumpang di sini, bukan endpoint sendiri: layar sudah memanggil ini tiap 2
    detik, jadi banner ikut hidup tanpa satu pun request tambahan.

    Sengaja **bukan** lewat `/api/console/dev/*`: banner ini untuk operator
    biasa, yang justru orang yang akan melihat kamera berhenti. Yang dikirim di
    sini cuma tanggal, tingkat keparahan, dan nama perusahaan — nomor token tetap
    support-only. `versi` ikut untuk baris di bawah tulisan AUTOGRADE (2026-09-28):
    dibaca tiap polling, jadi sesudah `autograde pull` layar yang terbuka ikut
    menampilkan versi baru tanpa dimuat ulang.

    `service.state()` jalan di thread pool (batch 2.5): polling 2 detik ini membaca
    beberapa query SQLite, dan di event loop query itu menahan layar lain dan kiriman
    janjang dari tiga line.
    """
    return {
        **(await run_in_threadpool(service.state)),
        "lisensi": await dev.license_state(),
        "versi": dev.app_version(),
        # Badge "versi X siap dipasang" (batch 4.6) rides this 2 s poll, as the licence
        # banner does: zero extra requests. Two small file reads, off the event loop.
        "pembaruan": (await run_in_threadpool(pembaruan.keadaan)).as_dict(),
        # Batch 5.9: whether the Rekap tab offers Print (support switch, one small read).
        "slip_cetak": slip.aktif(),
        # demo-autograde.smagri.id only: the screen simulates live lines and a scale.
        "demo_mode": demo_mode,
    }
