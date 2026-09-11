"""Timbangan jembatan + truk daftar manual (§3.5c rencana PalmOS).

Yang dikunci di sini adalah jalur uang: neto tidak pernah datang mentah dari
luar, dua kiriman untuk satu tiket bergabung bukan saling menimpa, dan plat
yang sama ditulis dengan cara berbeda tetap satu truk.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.plat import normalisasi_plat, truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), None)


def _kiriman(**over):
    payload = {
        "plate_number": "B 1234 XY",
        "waktu_masuk": "2026-09-09T18:30:00+00:00",  # = 2026-09-10 01:30 WIB
        "bruto_kg": 12500,
        "tara_kg": 5000,
    }
    payload.update(over)
    return payload


# ── plat ────────────────────────────────────────────────────────────────


def test_plat_beda_tulisan_tetap_satu_truk():
    assert normalisasi_plat("B 1234 xy") == normalisasi_plat("b-1234-XY") == "B1234XY"
    assert truck_id_for("B 1234 xy") == truck_id_for("b-1234-XY")


def test_plat_kosong_ditolak():
    with pytest.raises(ValueError):
        normalisasi_plat("   -  ")


def test_truk_manual_diketik_ulang_tidak_jadi_baris_kembar(service):
    a = service.daftar_truk_manual("B 1234 XY")
    b = service.daftar_truk_manual("b1234xy")
    assert a["id"] == b["id"]
    assert [t["id"] for t in service.trucks()] == [a["id"]]


# ── timbangan ───────────────────────────────────────────────────────────


def test_neto_dihitung_dan_masuk_hari_kerja_wib(service):
    row = service.catat_timbangan(_kiriman())
    assert row["neto_kg"] == 7500
    # Timbang jam 01:30 WIB masih shift kemarin? Bukan — tanggal kerja diambil
    # dari timestamp kirimannya sendiri di zona pabrik, bukan tanggal terima.
    assert row["tanggal_kerja"] == "2026-09-10"
    assert [r["id"] for r in service.weighings("2026-09-10")] == [row["id"]]


def test_neto_kiriman_yang_tidak_cocok_ditolak(service):
    service.catat_timbangan(_kiriman(neto_kg=7500.4))  # dalam toleransi, lolos
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(neto_kg=9000))


def test_tara_lebih_besar_dari_bruto_ditolak(service):
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(bruto_kg=5000, tara_kg=12500))


def test_timbang_keluar_menggabung_bukan_menimpa(service):
    # Timbang-masuk cuma punya bruto; timbang-keluar cuma punya tara. Tanpa
    # COALESCE, kiriman kedua menghapus bruto dan neto ikut hilang.
    masuk = service.catat_timbangan(_kiriman(tara_kg=None))
    assert masuk["bruto_kg"] == 12500 and masuk["neto_kg"] is None
    keluar = service.catat_timbangan(
        _kiriman(bruto_kg=None, tara_kg=5000, waktu_keluar="2026-09-09T21:00:00+00:00")
    )
    assert keluar["id"] == masuk["id"]
    assert (keluar["bruto_kg"], keluar["tara_kg"], keluar["neto_kg"]) == (12500, 5000, 7500)
    assert len(service.weighings("2026-09-10")) == 1


def test_kiriman_sama_dua_kali_tidak_jadi_dua_tiket(service):
    service.catat_timbangan(_kiriman())
    service.catat_timbangan(_kiriman())
    assert len(service.weighings("2026-09-10")) == 1


def test_ref_jadi_kunci_kalau_ada(service):
    a = service.catat_timbangan(_kiriman(ref="TKT-9"))
    b = service.catat_timbangan(_kiriman(ref="TKT-9", waktu_masuk="2026-09-09T19:00:00+00:00"))
    assert a["id"] == b["id"]


def test_tanpa_ref_dan_tanpa_waktu_masuk_ditolak(service):
    # Kalau boleh lewat, timbang-keluar tidak punya cara menemukan barisnya
    # dan satu tiket pecah jadi dua.
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(waktu_masuk=None, waktu_keluar="2026-09-09T21:00:00+00:00"))


def test_berat_ngawur_ditolak(service):
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(bruto_kg="dua belas ton"))
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(bruto_kg=-1))


def test_ref_kosong_dari_layar_tidak_bikin_tiket_kembar(service):
    # Layar operator SELALU mengirim `ref`; isinya kosong kalau tiketnya lahir di
    # konsol, bukan dari program timbangan. Kalau "" tidak dianggap "tidak ada",
    # kuncinya berubah dan timbang-keluar melahirkan baris kedua.
    masuk = service.catat_timbangan(_kiriman(tara_kg=None))
    keluar = service.catat_timbangan(_kiriman(ref="", bruto_kg=None, tara_kg=5000))
    assert keluar["id"] == masuk["id"]
    assert keluar["neto_kg"] == 7500
    assert len(service.weighings("2026-09-10")) == 1
