"""Timbangan dummy (user 2026-10-07): a support switch that stands in for the PLC scale.

While on, scan timbang isi saves BERAT_DUMMY_ISI and scan timbang kosong BERAT_DUMMY_KOSONG,
as a connected and steady scale would. The visit still goes to AutoERP: the user wants to see
it arrive, and AutoERP is reset before real use. The orange band on every screen says it is on.
"""
from __future__ import annotations

KUNCI_TIMBANGAN_DUMMY = "setelan_timbangan_dummy"
BERAT_DUMMY_ISI = 30000.0
BERAT_DUMMY_KOSONG = 10000.0
