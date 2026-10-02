"""Scan 1 dan 4 (keputusan user 2026-09-30): keputusan murni, tanpa database.

Timbang isi mengklaim kedatangan truknya yang masih menunggu; scan 4 menutup tiket
yang sudah timbang kosong. Dua-duanya dicari dengan jendela waktu, bukan hari kerja:
antrean pabrik bisa lewat tengah malam.
"""
from __future__ import annotations

import ast
import inspect
from datetime import timedelta

import pytest

from palmgrade.domain import gerbang
from palmgrade.domain.gerbang import (
    BELUM_TIMBANG_KOSONG,
    JENDELA_KEDATANGAN,
    JENDELA_KELUAR,
    SUDAH_KELUAR,
    TERCATAT,
    TIDAK_ADA_TIKET,
    baca_waktu,
    durasi_kunjungan,
    menit_antara,
    pilih_kedatangan,
    putuskan_keluar,
)
from palmgrade.domain.working_day import JENDELA_KUNJUNGAN_DETIK


def _datang(id_: str, jam: str) -> dict:
    return {"id": id_, "arrived_at": jam}


def _tiket(id_: str, *, masuk: str, keluar: str | None = None, tara: float | None = None,
           pergi: str | None = None) -> dict:
    return {"id": id_, "entered_at": masuk, "exited_at": keluar, "tare_kg": tara,
            "left_at": pergi, "plate_number": "BE 1 AA"}


# ── waktu dan durasi ─────────────────────────────────────────────────────────


def test_waktu_tanpa_zona_dibaca_utc():
    assert baca_waktu("2026-09-30T01:00:00") == baca_waktu("2026-09-30T01:00:00+00:00")


def test_waktu_z_dan_offset_sama():
    assert baca_waktu("2026-09-30T01:00:00Z") == baca_waktu("2026-09-30T08:00:00+07:00")


def test_waktu_ngawur_ditolak():
    with pytest.raises(ValueError):
        baca_waktu("kemarin sore")


def test_menit_antara_dibulatkan_dan_jam_mundur_bukan_durasi():
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T01:25:20Z") == 25
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T00:59:00Z") is None
    assert menit_antara(None, "2026-09-30T01:00:00Z") is None
    assert menit_antara("bukan jam", "2026-09-30T01:00:00Z") is None


def test_durasi_dengan_scan_1():
    d = durasi_kunjungan({"arrived_at": "2026-09-30T00:30:00Z", "entered_at": "2026-09-30T01:00:00Z",
                          "left_at": "2026-09-30T02:30:00Z"})
    assert d == {"antre_menit": 30, "total_menit": 120, "tanpa_scan_1": False}


def test_tanpa_scan_1_antre_tidak_diketahui_total_dari_timbang_isi():
    d = durasi_kunjungan({"arrived_at": None, "entered_at": "2026-09-30T01:00:00Z",
                          "left_at": "2026-09-30T02:30:00Z"})
    assert d == {"antre_menit": None, "total_menit": 90, "tanpa_scan_1": True}


def test_belum_keluar_total_kosong():
    d = durasi_kunjungan({"arrived_at": "2026-09-30T00:30:00Z", "entered_at": "2026-09-30T01:00:00Z",
                          "left_at": None})
    assert d["total_menit"] is None


# ── pilih_kedatangan ─────────────────────────────────────────────────────────


def test_kedatangan_terbaru_sebelum_timbang_isi_yang_dipilih():
    calon = [_datang("a1", "2026-09-30T00:10:00Z"), _datang("a2", "2026-09-30T00:40:00Z")]
    assert pilih_kedatangan(calon, "2026-09-30T01:00:00Z")["id"] == "a2"


def test_kedatangan_sesudah_timbang_isi_tidak_dipilih():
    assert pilih_kedatangan([_datang("a1", "2026-09-30T01:05:00Z")], "2026-09-30T01:00:00Z") is None


def test_kedatangan_lebih_tua_dari_jendela_diabaikan():
    assert pilih_kedatangan([_datang("a1", "2026-09-29T04:00:00Z")], "2026-09-30T01:00:00Z") is None


def test_antrean_lewat_tengah_malam_tetap_terpasang():
    calon = [_datang("a1", "2026-09-30T23:50:00+07:00")]
    assert pilih_kedatangan(calon, "2026-10-01T00:10:00+07:00")["id"] == "a1"


def test_offset_berbeda_dibandingkan_sebagai_waktu_bukan_teks():
    calon = [_datang("a1", "2026-09-30T07:30:00+07:00")]
    assert pilih_kedatangan(calon, "2026-09-30T01:00:00Z")["id"] == "a1"


def test_jam_kedatangan_rusak_dilewati():
    calon = [_datang("rusak", "bukan jam"), _datang("a1", "2026-09-30T00:30:00Z")]
    assert pilih_kedatangan(calon, "2026-09-30T01:00:00Z")["id"] == "a1"


def test_tanpa_calon_berarti_scan_1_terlewat():
    assert pilih_kedatangan([], "2026-09-30T01:00:00Z") is None


# ── putuskan_keluar ──────────────────────────────────────────────────────────


def test_tiket_selesai_tanpa_jam_keluar_ditutup():
    tiket = [_tiket("w1", masuk="2026-09-30T01:00:00Z", keluar="2026-09-30T02:00:00Z", tara=5000.0)]
    k = putuskan_keluar(tiket, "2026-09-30T02:10:00Z")
    assert (k.hasil, k.weighing["id"]) == (TERCATAT, "w1")


def test_scan_4_lewat_tengah_malam_menutup_tiket_2350():
    """Timbang isi 23:50, timbang kosong 00:10, keluar 00:20 hari kalender berikutnya."""
    tiket = [_tiket("w1", masuk="2026-09-30T23:50:00+07:00", keluar="2026-10-01T00:10:00+07:00", tara=6000.0)]
    k = putuskan_keluar(tiket, "2026-10-01T00:20:00+07:00")
    assert (k.hasil, k.weighing["id"]) == (TERCATAT, "w1")
    # Belum timbang kosong pukul 00:20: peringatan scan 4, bukan "tidak ada tiket".
    tiket = [_tiket("w2", masuk="2026-09-30T23:50:00+07:00")]
    assert putuskan_keluar(tiket, "2026-10-01T00:20:00+07:00").hasil == BELUM_TIMBANG_KOSONG


def test_tiket_terbuka_menang_atas_tiket_selesai():
    tiket = [
        _tiket("lama", masuk="2026-09-30T00:00:00Z", keluar="2026-09-30T00:50:00Z", tara=5000.0),
        _tiket("baru", masuk="2026-09-30T02:00:00Z"),
    ]
    k = putuskan_keluar(tiket, "2026-09-30T02:30:00Z")
    assert (k.hasil, k.weighing["id"]) == (BELUM_TIMBANG_KOSONG, "baru")


def test_tiket_selesai_terbaru_yang_ditutup():
    tiket = [
        _tiket("w1", masuk="2026-09-30T00:00:00Z", keluar="2026-09-30T00:50:00Z", tara=5000.0),
        _tiket("w2", masuk="2026-09-30T01:00:00Z", keluar="2026-09-30T01:50:00Z", tara=5000.0),
    ]
    assert putuskan_keluar(tiket, "2026-09-30T02:00:00Z").weighing["id"] == "w2"


def test_sudah_keluar_dijawab_sudah_keluar():
    tiket = [_tiket("w1", masuk="2026-09-30T01:00:00Z", keluar="2026-09-30T02:00:00Z",
                    tara=5000.0, pergi="2026-09-30T02:05:00Z")]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z").hasil == SUDAH_KELUAR


def test_tanpa_tiket_dijawab_tidak_ada_tiket():
    assert putuskan_keluar([], "2026-09-30T02:10:00Z").hasil == TIDAK_ADA_TIKET


def test_tiket_di_luar_jendela_tidak_ikut():
    tiket = [_tiket("w1", masuk="2026-09-28T01:00:00Z", keluar="2026-09-28T02:00:00Z", tara=5000.0)]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z").hasil == TIDAK_ADA_TIKET


def test_tanpa_jendela_tiket_lama_tetap_ditutup():
    tiket = [_tiket("w1", masuk="2026-09-28T01:00:00Z", keluar="2026-09-28T02:00:00Z", tara=5000.0)]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z", jendela=None).hasil == TERCATAT


def test_tara_tanpa_jam_keluar_memakai_jam_masuk():
    tiket = [_tiket("w1", masuk="2026-09-30T01:00:00Z", tara=5000.0)]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z").hasil == TERCATAT


def test_jendela_dua_belas_jam():
    assert JENDELA_KEDATANGAN == JENDELA_KELUAR == timedelta(hours=12)


def test_jendela_gerbang_satu_angka_dengan_lama_kunjungan():
    """Satu angka untuk "berapa lama satu kunjungan" (ketetapan Task 3): kedua jendela
    gerbang dibangun dari `JENDELA_KUNJUNGAN_DETIK`, bukan 12 jam yang ditulis lagi."""
    pohon = ast.parse(inspect.getsource(gerbang))
    nilai = {
        t.id: n.value
        for n in pohon.body if isinstance(n, ast.Assign | ast.AnnAssign)
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)
    }
    for nama in ("JENDELA_KEDATANGAN", "JENDELA_KELUAR"):
        dipakai = {x.id for x in ast.walk(nilai[nama]) if isinstance(x, ast.Name)}
        assert dipakai & {"JENDELA_KUNJUNGAN_DETIK", "JENDELA_KEDATANGAN"}, nama
    assert JENDELA_KEDATANGAN == timedelta(seconds=JENDELA_KUNJUNGAN_DETIK)


# ── review fixes (Task 11) ───────────────────────────────────────────────────


def test_menit_antara_membulat_ke_atas_seperti_kolom_lama():
    """JS `Math.round` memberi 30 detik → 1 dan 90 detik → 2; `round` Python memberi 0 dan 2."""
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T01:00:30Z") == 1
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T01:01:30Z") == 2
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T01:00:29Z") == 0
    assert menit_antara("2026-09-30T01:00:00Z", "2026-09-30T01:02:30Z") == 3


def test_tara_dengan_jam_keluar_rusak_jatuh_ke_jam_masuk():
    tiket = [_tiket("w1", masuk="2026-09-30T01:00:00Z", keluar="bukan jam", tara=5000.0)]
    k = putuskan_keluar(tiket, "2026-09-30T02:10:00Z")
    assert (k.hasil, k.weighing["id"]) == (TERCATAT, "w1")


def test_tiket_yang_ditunjuk_tanpa_jam_sama_sekali_tetap_ditutup():
    """Tombol baris menunjuk tiketnya; jam yang kosong tidak boleh membuatnya hilang."""
    tiket = [_tiket("w1", masuk=None, keluar=None, tara=5000.0)]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z", jendela=None).hasil == TERCATAT
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z").hasil == TIDAK_ADA_TIKET


def test_jam_tersimpan_di_luar_jangkauan_dilewati_bukan_meledak():
    tiket = [_tiket("w1", masuk="0001-01-01T00:00:00+05:00", keluar=None, tara=5000.0)]
    assert putuskan_keluar(tiket, "2026-09-30T02:10:00Z").hasil == TIDAK_ADA_TIKET
