"""Jawaban AutoERP yang butuh orang (batch 2.3).

Kalimatnya milik AutoERP (`erpnext/palm_mill/api.py`: `upsert_visit` dan
`_after_finalisation`, dibaca 2026-09-28), jadi dipatok di sini persis seperti yang
dikirimnya.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.jawaban_kunjungan import (
    TIKET_DIBATALKAN,
    TIKET_FINAL_BERBEDA,
    KonteksKunjungan,
    golongkan,
    jam_masuk,
    kabar_baru,
    pesan_log,
)


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


def test_jam_masuk_ditulis_jam_pabrik_tanpa_detik():
    assert jam_masuk("2026-09-28T07:41:09+07:00") == "2026-09-28 07:41"
    assert jam_masuk(None) == "-"


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
