"""Halaman konsol selalu diambil ulang dari server, tidak dari salinan browser.

Kejadian Lampung 2026-10-05: sesudah v1.22.0 lalu v1.23.0 terpasang, kiosk Firefox masih
menampilkan halaman versi sebelumnya. Angka versi di layar benar (datang dari API), tapi
bagian Pembaruan dan fitur baru tidak ada, sampai seseorang menekan Ctrl+Shift+R. Tanpa
Cache-Control, browser menebak sendiri berapa lama halaman boleh disimpan dari
Last-Modified. Operator yang menekan Pasang sekarang tidak tahu harus memuat ulang paksa.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.routes import console as console_routes


def test_halaman_konsol_wajib_dicek_ulang_ke_server():
    app = FastAPI()
    app.include_router(console_routes.router)
    with TestClient(app) as c:
        r = c.get("/console")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # no-cache: browser boleh menyimpan, tapi wajib bertanya ke server sebelum memakainya.
    assert "no-cache" in r.headers.get("cache-control", "")
