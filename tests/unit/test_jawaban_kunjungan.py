"""Jawaban AutoERP yang butuh orang (batch 2.3).

Kalimatnya milik AutoERP (`erpnext/palm_mill/api.py`: `upsert_visit` dan
`_after_finalisation`, dibaca 2026-09-28), jadi dipatok di sini persis seperti yang
dikirimnya.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.jawaban_kunjungan import (
    TANPA_NOMOR,
    TIKET_DIBATALKAN,
    TIKET_FINAL_BERBEDA,
    KonteksKunjungan,
    golongkan,
    jam_masuk,
    kabar_baru,
    pesan_log,
)

WIB = ZoneInfo("Asia/Jakarta")


@pytest.mark.parametrize(
    "note, revised, kode",
    [
        ("ticket already finalised; grading revised", True, TIKET_FINAL_BERBEDA),
        ("ticket already finalised; weights revised", True, TIKET_FINAL_BERBEDA),
        ("ticket already finalised; grading revised, weights revised", True, TIKET_FINAL_BERBEDA),
        # Yang tersimpan di `weighings.erp_note` cuma note-nya, tanpa `revised`.
        ("ticket already finalised; grading revised", False, TIKET_FINAL_BERBEDA),
        ("ticket cancelled; visit ignored", False, TIKET_DIBATALKAN),
        ("ticket already finalised; visit unchanged", False, None),
        (None, False, None),
        ("", False, None),
        (None, True, TIKET_FINAL_BERBEDA),
    ],
)
def test_golongkan(note, revised, kode):
    assert golongkan(note, revised=revised) == kode


def test_pesan_log_memuat_kode_truk_line_jam_tiket_dan_tindakan():
    pesan = pesan_log(
        TIKET_FINAL_BERBEDA,
        KonteksKunjungan(plat="BE 1 AA", line="line-2", masuk="2026-09-28 07:41",
                         tiket="WB-2026-00007", catatan="ticket already finalised; grading revised"),
    )

    assert pesan.startswith("[TIKET_FINAL_BERBEDA] Truk BE 1 AA, line-2, timbang masuk 2026-09-28 07:41: ")
    assert "WB-2026-00007" in pesan and "Tindakan: " in pesan
    assert pesan.endswith("Jawaban AutoERP: ticket already finalised; grading revised")


@pytest.mark.parametrize("kode", [TIKET_FINAL_BERBEDA, TIKET_DIBATALKAN])
def test_pesan_log_tanpa_em_dash_dan_tanpa_strip_jeda(kode):
    pesan = pesan_log(kode, KonteksKunjungan("BE 1 AA", "line-1", "2026-09-28 07:41", "WB-1", "x"))

    assert "—" not in pesan and " - " not in pesan


@pytest.mark.parametrize(
    "entered_at, tertulis",
    [
        ("2026-09-28T07:41:09+07:00", "2026-09-28 07:41"),
        # Tombol Timbang masuk mengirim `new Date().toISOString()`: UTC dengan `Z`.
        ("2026-09-28T00:41:09.123Z", "2026-09-28 07:41"),
        # Shift malam: jam UTC masih kemarin, jam pabrik sudah besok.
        ("2026-09-28T18:30:00+00:00", "2026-09-29 01:30"),
        # Tanpa zona = sudah jam pabrik (program timbangan menulis begitu).
        ("2026-09-28T07:41:09", "2026-09-28 07:41"),
        ("bukan jam", "bukan jam"),
        (None, "-"),
        ("", "-"),
    ],
)
def test_jam_masuk_ditulis_jam_pabrik_tanpa_detik(entered_at, tertulis):
    assert jam_masuk(entered_at, WIB) == tertulis


@pytest.mark.parametrize(
    "catatan, berbeda",
    [
        ("ticket already finalised; grading revised", "Yang berbeda: grading berubah. "),
        ("ticket already finalised; weights revised", "Yang berbeda: berat berubah. "),
        ("ticket already finalised; grading revised, weights revised",
         "Yang berbeda: grading berubah, berat berubah. "),
    ],
)
def test_pesan_log_menyebut_yang_berbeda_dalam_bahasa_indonesia(catatan, berbeda):
    pesan = pesan_log(TIKET_FINAL_BERBEDA, KonteksKunjungan("BE 1 AA", "line-1", "2026-09-28 07:41", "WB-1", catatan))

    assert berbeda in pesan
    assert pesan.endswith(f"Jawaban AutoERP: {catatan}")


def test_pesan_log_membawa_rekap_pabrik_sekarang():
    pesan = pesan_log(TIKET_FINAL_BERBEDA, KonteksKunjungan(
        "BE 1 AA", "line-1", "2026-09-28 07:41", "WB-1", "ticket already finalised; grading revised",
        janjang=3, mentah=1,
    ))

    assert "Rekap pabrik sekarang: 3 janjang, mentah 33,3%. " in pesan


def test_pesan_log_tanpa_rekap_kalau_belum_ada_janjang():
    pesan = pesan_log(TIKET_DIBATALKAN, KonteksKunjungan("BE 1 AA", "-", "-", "WB-1", "ticket cancelled; visit ignored"))

    assert "Rekap pabrik" not in pesan and "Yang berbeda" not in pesan


def test_tiket_tanpa_nomor_ditulis_netral_bukan_strip():
    pesan = pesan_log(TIKET_DIBATALKAN, KonteksKunjungan("BE 1 AA", "line-1", "2026-09-28 07:41", TANPA_NOMOR, "x"))

    assert "tiket AutoERP (tanpa nomor) sudah dibatalkan" in pesan and " - " not in pesan


@pytest.mark.parametrize(
    "note, revised, sebelumnya, kode",
    [
        # Pertama kali AutoERP menolak mengubah tiket final: satu WARNING.
        ("ticket already finalised; grading revised", True, None, TIKET_FINAL_BERBEDA),
        ("ticket already finalised; grading revised", True, "ticket already finalised; visit unchanged",
         TIKET_FINAL_BERBEDA),
        # Kirim ulang harian dengan rekap yang sama: kalimatnya sama, bukan kejadian baru.
        ("ticket already finalised; grading revised", True, "ticket already finalised; grading revised", None),
        ("ticket cancelled; visit ignored", False, "ticket cancelled; visit ignored", None),
        # Bobot ikut berubah sesudahnya: kalimat baru, berita baru.
        ("ticket already finalised; grading revised, weights revised", True,
         "ticket already finalised; grading revised", TIKET_FINAL_BERBEDA),
        ("ticket already finalised; visit unchanged", False, None, None),
        (None, True, None, TIKET_FINAL_BERBEDA),
    ],
)
def test_kabar_baru_sekali_per_perubahan_bukan_per_kiriman(note, revised, sebelumnya, kode):
    assert kabar_baru(note, revised=revised, sebelumnya=sebelumnya) == kode
