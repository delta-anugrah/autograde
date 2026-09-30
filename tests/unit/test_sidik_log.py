"""Sidik penggabungan tab Log (batch 3.3): id yang berganti tidak memecah satu galat,
galat yang BERBEDA tidak pernah tergabung.

Dua arah salahnya sama mahal: tidak tergabung = banjir satu galat mendorong galat
lain keluar dari layar; tergabung keliru = HTTP 404 dan 500, atau line-1 dan line-2,
terbaca satu masalah dan yang kedua tidak pernah dicari.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.sidik_log import normalkan_pesan
from palmgrade.repositories.log_repository import LogStore, _fingerprint


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Penugasan 3f2a9c1e-5b7d-4e1a-9c3f-2b6d4c8e7b01 gagal diteruskan",
            "Penugasan a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02 gagal diteruskan",
        ),
        ("Folder truk 3f2a9c1e tidak bisa dibuat", "Folder truk 9d2b6a1e tidak bisa dibuat"),
        ("Tulis foto lambat: 1.52 s", "Tulis foto lambat: 0.97 s"),
        ("Event 1727680000.123 ditolak", "Event 1727680003.456 ditolak"),
        ("Baris outbox 1234567 gagal", "Baris outbox 7654321 gagal"),
    ],
)
def test_id_yang_berganti_menghasilkan_sidik_yang_sama(a, b):
    assert normalkan_pesan(a) == normalkan_pesan(b)
    assert _fingerprint("ERROR", "x", a) == _fingerprint("ERROR", "x", b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("AutoERP menjawab HTTP 404", "AutoERP menjawab HTTP 500"),
        ("line http://localhost:8001 tidak menjawab", "line http://localhost:8002 tidak menjawab"),
        ("PLC 192.168.3.39:1025 terputus", "PLC 192.168.3.40:1025 terputus"),
        ("[Errno 111] Connection refused", "[Errno 113] No route to host"),
        ("Versi v1.19.0 terpasang", "Versi v1.20.0 terpasang"),
        ("Truk BE 1234 AB tidak dikenal", "Truk BG 1234 AB tidak dikenal"),
        ("coil 1000 gagal ditulis", "coil 1001 gagal ditulis"),
        ("antrean 12345 baris", "antrean 12346 baris"),
    ],
)
def test_galat_yang_berbeda_tidak_pernah_tergabung(a, b):
    assert _fingerprint("ERROR", "x", a) != _fingerprint("ERROR", "x", b)


def test_kata_biasa_berhuruf_hex_tidak_disentuh():
    assert normalkan_pesan("deadbeef facade decade") == "deadbeef facade decade"


def test_pesan_tanpa_id_sidiknya_tidak_berubah_dari_versi_lama():
    """Baris yang ditulis versi lama dan baris baru untuk pesan yang sama tetap satu
    sidik: pesan tanpa id tidak diubah normalisasi sama sekali."""
    pesan = "AutoERP terputus: [Errno 111] Connection refused"
    assert normalkan_pesan(pesan) == pesan


def test_logstore_menggabungkan_galat_yang_cuma_beda_id(tmp_path):
    store = LogStore(tmp_path / "log.db")
    for i, assign in enumerate(("3f2a9c1e", "9d2b6a1e", "a7e2f4c9")):
        store.write("ERROR", "palmgrade.x", f"Folder truk {assign} tidak bisa dibuat", None, now=1000.0 + i)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    # Pesan yang disimpan tetap milik kejadian pertama, bukan versi yang dinormalkan.
    assert hasil["items"][0]["message"] == "Folder truk 3f2a9c1e tidak bisa dibuat"
    assert hasil["items"][0]["count"] == 3


def test_logstore_tidak_menggabungkan_kode_http_yang_berbeda(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "palmgrade.x", "AutoERP menjawab HTTP 404", None, now=1000.0)
    store.write("ERROR", "palmgrade.x", "AutoERP menjawab HTTP 500", None, now=1001.0)
    assert store.read(level=None, search=None, limit=10, offset=0)["total"] == 2
