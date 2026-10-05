"""Impor grading: membaca CSV Per janjang hasil Unduh CSV tab Riwayat (murni, tanpa I/O).

Yang dibaca cuma berkas buatan konsol sendiri: kepala kolomnya `KEPALA_CSV` yang
SAMA dengan yang ditulis ekspor, jadi dua sisi tidak bisa berbeda. Baris yang
salah tidak ditebak: dilaporkan per nomor baris supaya support bisa melihatnya
sebelum apa pun disimpan.
"""
from __future__ import annotations

import csv
import io
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.impor_grading import (
    KODE_SALAH_BARIS,
    JanjangImpor,
    SalahBaris,
    baca,
    hari_berjalan,
    sidik,
    timestamp_utc,
)
from palmgrade.domain.operator_error import (
    IMPOR_BUKAN_JANJANG,
    IMPOR_BUKAN_UTF8,
    IMPOR_KOSONG,
    IMPOR_RUSAK,
    InvalidInput,
)
from palmgrade.domain.riwayat import KEPALA_CSV

EVENT = "3f6c8f0e-5a4b-5c1d-9e2f-0a1b2c3d4e5f"
FOTO = "/captures/line-1/results/2026-09-24/20260924_010000_000000_auto.webp"


def _berkas(baris: list[list[str]], *, bahasa: str = "id", bom: bool = True) -> bytes:
    buffer = io.StringIO()
    penulis = csv.writer(buffer, lineterminator="\r\n")
    penulis.writerow(KEPALA_CSV["janjang"][bahasa])
    penulis.writerows(baris)
    return (("﻿" if bom else "") + buffer.getvalue()).encode()


def _baris(**ganti: str) -> list[str]:
    isi = {
        "tanggal": "2026-09-24", "waktu": "2026-09-24 08:00:00", "line": "line-1",
        "plat": "BE 1234 AB", "supplier": "CV Maju", "sumber": "Eksternal", "kelas": "Ripe",
        "hasil": "ACC", "tp": "", "jenis": "otomatis", "foto": FOTO, "event": EVENT,
    }
    isi.update(ganti)
    return [isi[k] for k in ("tanggal", "waktu", "line", "plat", "supplier", "sumber", "kelas",
                             "hasil", "tp", "jenis", "foto", "event")]


def _satu(**ganti: str) -> JanjangImpor | SalahBaris:
    hasil = list(baca(_berkas([_baris(**ganti)])))
    assert len(hasil) == 1, hasil
    return hasil[0]


def test_satu_baris_terbaca_utuh():
    j = _satu()

    assert j == JanjangImpor(
        nomor=2, event_id=EVENT, work_date="2026-09-24", waktu="2026-09-24 08:00:00",
        line_code="line-1", plat="BE 1234 AB", supplier="CV Maju", grade_class="Ripe",
        ripeness_status="ACC", tp=False, capture_type="auto",
        image_path="captures/results/2026-09-24/20260924_010000_000000_auto.webp",
    )


def test_berkas_bahasa_inggris_dan_tanpa_bom_juga_terbaca():
    isi = _berkas([_baris(tp="yes", jenis="auto")], bahasa="en", bom=False)

    (j,) = baca(isi)

    assert (j.tp, j.capture_type) == (True, "auto")


def test_tanda_kutip_pengaman_rumus_dilepas():
    """Ekspor memberi `'` di depan teks berawalan = + - @ supaya Excel tidak
    menjalankannya sebagai rumus. Impor mengembalikannya ke teks aslinya."""
    j = _satu(supplier="'=CV Maju", plat="'-BE 1234 AB")

    assert (j.supplier, j.plat) == ("=CV Maju", "-BE 1234 AB")


def test_nilai_dibersihkan_kelas_hasil_dan_event_id_dinormalkan():
    j = _satu(kelas="ripe", hasil="acc", event=EVENT.upper(), plat="  BE 1234 AB  ", tp="YA")

    assert (j.grade_class, j.ripeness_status, j.event_id, j.plat, j.tp) == (
        "Ripe", "ACC", EVENT, "BE 1234 AB", True
    )


def test_kosong_berarti_tidak_ada_bukan_salah():
    j = _satu(plat="", supplier="", kelas="", foto="")

    assert (j.plat, j.supplier, j.grade_class, j.image_path) == (None, None, None, None)


def test_foto_r2_absolut_disimpan_apa_adanya():
    url = "https://captures.example/line-1/2026-09-24/x.webp"
    assert _satu(foto=url).image_path == url


def test_line_asing_berupa_machine_id_tetap_diterima():
    """Konsol menyimpan janjang dari line yang tidak dikenalnya dengan machine_id
    sebagai kode line. Ekspornya membawa kode itu, dan impornya harus menerimanya."""
    mesin = "ad5f7bb9-c06d-4e87-8282-ce450ae331ec"
    j = _satu(line=mesin, foto=f"/captures/{mesin}/results/x.webp")

    assert (j.line_code, j.image_path) == (mesin, "captures/results/x.webp")


@pytest.mark.parametrize("waktu", ["2026-09-25 02:30:00", "2026-09-25 11:59:59", "2026-09-25 17:59:59"])
def test_a_night_shift_bunch_exported_under_a_cutoff_is_read_back(waktu):
    """Batch 5.11: with a 05:00 cutoff the console exports a bunch graded 25 Sept 02:30 under
    working day 24 Sept. Its own export must import again; the file's working day is kept."""
    j = _satu(waktu=waktu)

    assert isinstance(j, JanjangImpor), j
    assert (j.work_date, j.waktu) == ("2026-09-24", waktu)


@pytest.mark.parametrize(
    ("ganti", "kode"),
    [
        ({"event": ""}, "event_id_kosong"),
        ({"event": "bukan-uuid"}, "event_id_tidak_sah"),
        ({"tanggal": "24/09/2026"}, "tanggal_tidak_sah"),
        ({"tanggal": "2026-02-30"}, "tanggal_tidak_sah"),
        ({"waktu": "24/09/2026 08:00"}, "waktu_tidak_sah"),
        ({"waktu": "2026-09-23 23:59:59"}, "waktu_beda_tanggal"),
        # The working day or the next calendar day only (a cutoff is under 24 h, batch 5.11).
        ({"waktu": "2026-09-26 02:00:00"}, "waktu_beda_tanggal"),
        ({"line": ""}, "line_kosong"),
        ({"line": "line 1<script>"}, "line_tidak_sah"),
        ({"hasil": "OK"}, "hasil_tidak_sah"),
        ({"kelas": "Busuk"}, "kelas_tidak_sah"),
        ({"kelas": "Unripe", "hasil": "ACC"}, "kelas_bertentangan"),
        ({"kelas": "JK", "hasil": "ACC"}, "kelas_bertentangan"),
        ({"tp": "mungkin"}, "tp_tidak_sah"),
        ({"jenis": "robot"}, "jenis_tidak_sah"),
        ({"foto": "/captures/line-2/results/x.webp"}, "foto_tidak_sah"),
        ({"foto": "/captures/line-1/../../state/console.db"}, "foto_tidak_sah"),
        ({"foto": "javascript:alert(1)"}, "foto_tidak_sah"),
        ({"plat": "---"}, "plat_tidak_sah"),
        # Modul csv Python 3.11+ menerima NUL; plat berisi karakter kontrol tetap sampah.
        ({"plat": "BE\x001234 AB"}, "plat_tidak_sah"),
    ],
)
def test_baris_salah_dilaporkan_dengan_kodenya(ganti, kode):
    salah = _satu(**ganti)

    assert isinstance(salah, SalahBaris), salah
    assert (salah.nomor, salah.kode) == (2, kode)
    assert kode in KODE_SALAH_BARIS


def test_nilai_yang_salah_ikut_dilaporkan_tapi_dipotong():
    salah = _satu(event="x" * 500)

    assert salah.params["nilai"] == "x" * 40


def test_ripe_yang_dipaksa_rej_diterima():
    """Line memaksa REJ untuk buah bertumpuk atau terlalu kecil TANPA mengubah kelasnya
    (`frame_processing_worker`), jadi Ripe + REJ ada di setiap hari produksi yang sibuk.
    Yang mustahil cuma kelas mentah yang diterima (Unripe/JK + ACC)."""
    j = _satu(kelas="Ripe", hasil="REJ")

    assert (j.grade_class, j.ripeness_status) == ("Ripe", "REJ")


def test_tp_tanpa_kelas_buah_boleh_dengan_verdict_apa_pun():
    """TP bukan janjang (domain/grade_class.py): tidak punya verdict sendiri."""
    assert _satu(kelas="TP", hasil="REJ").grade_class == "TP"


def test_nomor_baris_seperti_di_spreadsheet_dan_baris_kosong_dilewati():
    isi = _berkas([_baris(), [], _baris(event="bukan-uuid")])

    hasil = list(baca(isi))

    assert [type(h).__name__ for h in hasil] == ["JanjangImpor", "SalahBaris"]
    assert hasil[1].nomor == 4


def test_baris_terpotong_di_akhir_berkas_dilaporkan_bukan_meledak():
    """Unduhan yang terputus di tengah menyisakan baris separuh."""
    isi = _berkas([_baris()]) + b"2026-09-24,2026-09-24 08:00:01,line-1"

    hasil = list(baca(isi))

    assert isinstance(hasil[1], SalahBaris) and hasil[1].kode == "event_id_kosong"


def test_berkas_ringkasan_per_hari_atau_per_truk_ditolak_dengan_jenisnya():
    for tampilan in ("hari", "truk"):
        buffer = io.StringIO()
        csv.writer(buffer).writerow(KEPALA_CSV[tampilan]["id"])
        with pytest.raises(InvalidInput) as galat:
            list(baca(buffer.getvalue().encode()))
        assert (galat.value.code, galat.value.params["jenis"]) == (IMPOR_BUKAN_JANJANG, tampilan)


def test_csv_lain_ditolak():
    with pytest.raises(InvalidInput) as galat:
        list(baca(b"nama,umur\nani,3\n"))
    assert (galat.value.code, galat.value.params["jenis"]) == (IMPOR_BUKAN_JANJANG, "lain")


def test_berkas_disimpan_ulang_excel_dengan_titik_koma_ditolak_sebagai_bukan_janjang():
    teks = ";".join(KEPALA_CSV["janjang"]["id"]) + "\r\n"
    with pytest.raises(InvalidInput) as galat:
        list(baca(teks.encode()))
    assert galat.value.code == IMPOR_BUKAN_JANJANG


def test_csv_rusak_ditolak_dengan_nomor_barisnya_bukan_meledak():
    """Tanda kutip yang tidak ditutup menelan sisa berkas jadi satu sel raksasa. Harus
    jadi pesan, bukan galat 500."""
    kutip = _berkas([_baris()]) + b'2026-09-24,"' + b"x" * 200_000 + b"\r\n"
    with pytest.raises(InvalidInput) as galat:
        list(baca(kutip))
    assert galat.value.code == IMPOR_RUSAK
    assert int(galat.value.params["nomor"]) >= 3


def test_berkas_kosong_dan_bukan_utf8():
    with pytest.raises(InvalidInput) as kosong:
        list(baca(b""))
    with pytest.raises(InvalidInput) as utf16:
        list(baca(",".join(KEPALA_CSV["janjang"]["id"]).encode("utf-16")))

    assert (kosong.value.code, utf16.value.code) == (IMPOR_KOSONG, IMPOR_BUKAN_UTF8)


def test_kolom_boleh_berurutan_lain_dan_kolom_tambahan_diabaikan():
    kepala = ["Catatan", *reversed(KEPALA_CSV["janjang"]["id"])]
    buffer = io.StringIO()
    penulis = csv.writer(buffer)
    penulis.writerow(kepala)
    penulis.writerow(["dari kantor", *reversed(_baris())])

    (j,) = baca(buffer.getvalue().encode())

    assert (j.event_id, j.plat) == (EVENT, "BE 1234 AB")


def test_hari_ini_dan_sesudahnya_masih_berjalan():
    j = _satu()
    assert not hari_berjalan(j, "2026-09-25")
    assert hari_berjalan(j, "2026-09-24")
    assert hari_berjalan(j, "2026-09-23")


def test_waktu_pabrik_jadi_timestamp_utc_berformat_sama_dengan_line():
    assert timestamp_utc("2026-09-24 08:00:00", ZoneInfo("Asia/Jakarta")) == "2026-09-24T01:00:00+00:00"


def test_sidik_berkas_tetap_untuk_isi_yang_sama():
    assert sidik(b"abc") == sidik(b"abc") != sidik(b"abd")
    assert len(sidik(b"abc")) == 64
