"""Batas hari kerja pabrik (§6.1 rencana PalmOS).

Pabrik jalan ~20 jam/hari dan LEWAT tengah malam WIB. Jam 00:30 WIB masih shift
yang sama dengan jam 23:00 sebelumnya, tapi dalam UTC dia sudah pindah tanggal —
itulah jebakannya. Test ini yang gagal duluan kalau ada yang menghitung tanggal
dari UTC atau dari `now()` lagi.
"""
from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.working_day import tanggal_kerja_for

WIB = ZoneInfo("Asia/Jakarta")  # UTC+7


def test_lewat_tengah_malam_wib_masuk_tanggal_wib_bukan_utc():
    # 2026-09-09 18:30 UTC = 2026-09-10 01:30 WIB — shift malam, sudah hari baru
    # di pabrik walau UTC masih 09.
    assert tanggal_kerja_for("2026-09-09T18:30:00+00:00", WIB) == "2026-09-10"


def test_sore_wib_belum_ganti_hari_walau_utc_masih_kemarin():
    # 2026-09-09 16:00 UTC = 2026-09-09 23:00 WIB — masih hari yang sama.
    assert tanggal_kerja_for("2026-09-09T16:00:00Z", WIB) == "2026-09-09"


def test_pagi_wib_masih_hari_kemarin_menurut_utc():
    # 2026-09-08 22:00 UTC = 2026-09-09 05:00 WIB. Pakai UTC → salah satu hari.
    ts = "2026-09-08T22:00:00+00:00"
    assert tanggal_kerja_for(ts, WIB) == "2026-09-09"
    assert tanggal_kerja_for(ts, UTC) == "2026-09-08"


def test_timestamp_naif_dianggap_utc():
    assert tanggal_kerja_for("2026-09-09T18:30:00", WIB) == "2026-09-10"


def test_offset_selain_utc_dihormati():
    # Line yang mengirim +07:00 langsung tidak boleh digeser dua kali.
    assert tanggal_kerja_for("2026-09-10T01:30:00+07:00", WIB) == "2026-09-10"


def test_timestamp_cacat_melempar_bukan_jatuh_ke_hari_ini():
    # Diam-diam memakai now() = tonase mendarat di tanggal yang salah dan tidak
    # ada yang tahu. Melempar → ingest balas 400 → outbox line menandai gagal.
    with pytest.raises(ValueError):
        tanggal_kerja_for("kemarin sore", WIB)
    with pytest.raises(ValueError):
        tanggal_kerja_for("", WIB)
