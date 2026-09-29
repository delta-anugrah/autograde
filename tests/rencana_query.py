"""Rencana query yang BENAR-BENAR dijalankan sebuah method store (batch 2.5).

SQL direkam lewat `set_trace_callback` (Python 3.11 memberinya dengan parameter sudah
terisi), lalu tiap SELECT/UPDATE/DELETE diminta `EXPLAIN QUERY PLAN`-nya. Test membaca
query dari method itu sendiri, bukan salinan SQL yang bisa melenceng dari kode.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable

_DIPERIKSA = ("SELECT", "UPDATE", "DELETE")


def rencana(db: sqlite3.Connection, panggil: Callable[[], object]) -> list[str]:
    """Satu string per statement yang dijalankan `panggil`, baris plan digabung ' / '."""
    tercatat: list[str] = []
    db.set_trace_callback(tercatat.append)
    try:
        panggil()
    finally:
        db.set_trace_callback(None)
    hasil = []
    for sql in tercatat:
        kata = sql.lstrip().split(None, 1)
        if kata and kata[0].upper() in _DIPERIKSA:
            baris = db.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
            hasil.append(" / ".join(str(b[3]) for b in baris))
    return hasil
