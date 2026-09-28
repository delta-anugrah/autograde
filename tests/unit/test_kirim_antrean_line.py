"""Aturan murni antrean line ke konsol (batch 2.4): jeda, arti jawaban, umur janjang."""
from __future__ import annotations

import json
import time

import pytest

from palmgrade.domain.kirim_antrean_line import (
    JEDA_BARIS_DASAR_S,
    JEDA_BARIS_MAKS_S,
    JEDA_SAMBUNGAN_DASAR_S,
    JEDA_SAMBUNGAN_MAKS_S,
    SEBAB_ALAMAT_SALAH,
    SEBAB_KONSOL_GALAT,
    SEBAB_KUNCI_DITOLAK,
    SEBAB_TAK_TERJANGKAU,
    Nasib,
    SambunganKonsol,
    jeda_mundur,
    nilai_jawaban,
    waktu_janjang,
)

#: 2026-09-20T03:00:00Z
EPOCH_TS = 1789873200.0


# ── jeda ────────────────────────────────────────────────────────────────


def test_jeda_baris_berlipat_dari_5_detik_sampai_10_menit():
    jeda = [jeda_mundur(k, dasar=JEDA_BARIS_DASAR_S, maks=JEDA_BARIS_MAKS_S) for k in range(1, 10)]
    assert jeda == [5, 10, 20, 40, 80, 160, 320, 600, 600]


def test_percobaan_ke_semiliar_tetap_maks_dan_cepat():
    """Tanpa batas nyerah `ke` terus naik; 2**(ke-1) tanpa batas pangkat adalah
    bilangan raksasa yang dihitung ulang tiap gagal."""
    mulai = time.perf_counter()
    assert jeda_mundur(10**9, dasar=JEDA_BARIS_DASAR_S, maks=JEDA_BARIS_MAKS_S) == JEDA_BARIS_MAKS_S
    assert time.perf_counter() - mulai < 0.01


def test_ke_nol_atau_negatif_memakai_dasar():
    assert jeda_mundur(0, dasar=5, maks=600) == 5
    assert jeda_mundur(-3, dasar=5, maks=600) == 5


# ── arti jawaban konsol ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,teks", [(200, "{}"), (201, '{"status":"ok"}'), (204, ""), (409, "already_processed")]
)
def test_jawaban_terkirim(status, teks):
    assert nilai_jawaban(status, teks).nasib is Nasib.TERKIRIM


@pytest.mark.parametrize("status", [400, 413, 422])
def test_baris_ditolak_tanpa_sebab_sambungan(status):
    putusan = nilai_jawaban(status, "timestamp rusak")
    assert putusan.nasib is Nasib.DITOLAK
    assert putusan.sebab is None


@pytest.mark.parametrize(
    "status,sebab",
    [
        (401, SEBAB_KUNCI_DITOLAK),
        (403, SEBAB_KUNCI_DITOLAK),
        (404, SEBAB_ALAMAT_SALAH),
        (405, SEBAB_ALAMAT_SALAH),
        (307, SEBAB_ALAMAT_SALAH),
        (408, SEBAB_KONSOL_GALAT),
        (429, SEBAB_KONSOL_GALAT),
        (500, SEBAB_KONSOL_GALAT),
        (503, SEBAB_KONSOL_GALAT),
    ],
)
def test_konsol_bermasalah_menyebut_sebabnya(status, sebab):
    putusan = nilai_jawaban(status, "apa pun")
    assert putusan.nasib is Nasib.KONSOL_BERMASALAH
    assert putusan.sebab == sebab


# ── umur janjang dari payload ───────────────────────────────────────────


@pytest.mark.parametrize(
    "ts",
    ["2026-09-20T03:00:00+00:00", "2026-09-20T03:00:00Z", "2026-09-20T03:00:00", "2026-09-20T10:00:00+07:00"],
)
def test_waktu_janjang_dari_timestamp_payload(ts):
    assert waktu_janjang(json.dumps({"timestamp": ts}), cadangan=1.0) == EPOCH_TS


@pytest.mark.parametrize(
    "payload", ["bukan json", "[]", "null", '{"a": 1}', '{"timestamp": "kemarin"}', '{"timestamp": null}']
)
def test_payload_tak_terbaca_memakai_cadangan(payload):
    assert waktu_janjang(payload, cadangan=42.0) == 42.0


# ── sambungan ke konsol ─────────────────────────────────────────────────


def test_sambungan_awal_tidak_diketahui_dan_boleh_mencoba():
    s = SambunganKonsol()
    assert s.tersambung is None
    assert s.boleh_coba(0.0)


def test_putus_pertama_kabar_baru_lalu_jeda_berlipat_sampai_30_detik():
    s = SambunganKonsol()
    assert s.gagal(100.0, sebab=SEBAB_TAK_TERJANGKAU) is True
    assert (s.tersambung, s.putus_sejak, s.coba_lagi_at) == (False, 100.0, 100.0 + JEDA_SAMBUNGAN_DASAR_S)
    assert not s.boleh_coba(104.9)
    assert s.gagal(105.0, sebab=SEBAB_TAK_TERJANGKAU) is False
    assert s.coba_lagi_at == 115.0
    for _ in range(20):
        s.gagal(200.0, sebab=SEBAB_TAK_TERJANGKAU)
    assert s.coba_lagi_at == 200.0 + JEDA_SAMBUNGAN_MAKS_S
    assert s.putus_sejak == 100.0


def test_sebab_berganti_adalah_kabar_baru():
    s = SambunganKonsol()
    s.gagal(0.0, sebab=SEBAB_TAK_TERJANGKAU)
    assert s.gagal(5.0, sebab=SEBAB_KUNCI_DITOLAK) is True
    assert s.sebab == SEBAB_KUNCI_DITOLAK
    assert s.putus_sejak == 0.0


def test_berhasil_sesudah_boot_atau_putus_adalah_transisi():
    s = SambunganKonsol()
    assert s.berhasil() is True  # kontak pertama sesudah boot
    assert s.berhasil() is False  # sudah tersambung
    s.gagal(10.0, sebab=SEBAB_KONSOL_GALAT)
    assert s.berhasil() is True
    assert (s.tersambung, s.putus_sejak, s.sebab, s.gagal_beruntun) == (True, None, None, 0)
    assert s.boleh_coba(0.0)


def test_bangunkan_membatalkan_jeda_tanpa_melupakan_putus():
    s = SambunganKonsol()
    s.gagal(50.0, sebab=SEBAB_TAK_TERJANGKAU)
    s.bangunkan()
    assert s.boleh_coba(50.0)
    assert (s.tersambung, s.putus_sejak) == (False, 50.0)
