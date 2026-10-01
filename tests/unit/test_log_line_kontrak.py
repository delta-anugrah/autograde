"""Kontrak `GET /internal/log` (batch 3.2): potong, baca jawaban, titik mulai kursor."""
from __future__ import annotations

import pytest

from palmgrade.domain.log_line import (
    PANJANG_DETAIL_MAKS,
    PANJANG_PESAN_MAKS,
    KursorLine,
    baca_jawaban_log,
    mulai_dari,
    potong_detail,
    potong_pesan,
)


def _entri(**ubah) -> dict:
    dasar = {
        "id": 3, "seq": 7, "first_at": 100.0, "last_at": 160.5, "level": "ERROR",
        "source": "palmgrade.workers.frame_capture_worker", "message": "grab gagal",
        "detail": "Traceback...\nRuntimeError: x", "count": 4,
    }
    return {**dasar, **ubah}


def _jawaban(**ubah) -> dict:
    dasar = {"generasi": "g1", "entri": [_entri()], "seq_akhir": 7, "lagi": False, "dibuang": 0}
    return {**dasar, **ubah}


def test_detail_pendek_tidak_diubah():
    assert potong_detail("Traceback\nX") == "Traceback\nX"
    assert potong_detail(None) is None


def test_detail_panjang_disimpan_ekornya_dengan_tanda():
    """Baris exception ada di ujung traceback: itu yang harus selamat."""
    panjang = "a" * PANJANG_DETAIL_MAKS + "\nValueError: inti masalah"
    hasil = potong_detail(panjang)
    assert len(hasil) == PANJANG_DETAIL_MAKS
    assert hasil.startswith("...(dipotong)\n")
    assert hasil.endswith("ValueError: inti masalah")


def test_pesan_panjang_dipotong_dengan_titik_tiga():
    hasil = potong_pesan("x" * (PANJANG_PESAN_MAKS + 50))
    assert len(hasil) == PANJANG_PESAN_MAKS
    assert hasil.endswith("...")


def test_jawaban_sah_terbaca_lengkap():
    j = baca_jawaban_log(_jawaban())
    assert (j.generasi, j.seq_akhir, j.lagi, j.dibuang) == ("g1", 7, False, 0)
    (e,) = j.entri
    assert (e.id, e.seq, e.count, e.level, e.message) == (3, 7, 4, "ERROR", "grab gagal")
    assert (e.first_at, e.last_at) == (100.0, 160.5)


def test_jawaban_kosong_sah():
    j = baca_jawaban_log(_jawaban(entri=[], seq_akhir=0))
    assert j.entri == ()


@pytest.mark.parametrize(
    "rusak",
    [
        None,
        [],
        _jawaban(generasi=""),
        _jawaban(generasi=5),
        _jawaban(entri="bukan daftar"),
        _jawaban(lagi="ya"),
        _jawaban(seq_akhir=-1),
        _jawaban(seq_akhir=True),
        _jawaban(dibuang=None),
        _jawaban(entri=[_entri(level="INFO")]),
        _jawaban(entri=[_entri(id=0)]),
        _jawaban(entri=[_entri(count=0)]),
        _jawaban(entri=[_entri(first_at="kemarin")]),
        _jawaban(entri=[_entri(detail=12)]),
        _jawaban(entri=[_entri(message=None)]),
        _jawaban(entri=["bukan objek"]),
    ],
)
def test_jawaban_cacat_ditolak_seluruhnya(rusak):
    """Satu entri cacat menolak seluruh halaman: kursor konsol tidak maju."""
    with pytest.raises(ValueError):
        baca_jawaban_log(rusak)


def test_detail_dan_pesan_dari_line_dipotong_lagi_di_konsol():
    """Line versi lain boleh saja lupa memotong; konsol tidak menyimpan lebih dari batasnya."""
    j = baca_jawaban_log(
        _jawaban(entri=[_entri(message="m" * 5000, detail="d" * 20000, source="s" * 999)])
    )
    (e,) = j.entri
    assert len(e.message) <= PANJANG_PESAN_MAKS
    assert len(e.detail) == PANJANG_DETAIL_MAKS
    assert len(e.source) == 200


def test_mulai_dari_kursor_kalau_generasi_sama():
    assert mulai_dari(41, "g1", "g1") == 41


def test_mulai_dari_nol_kalau_berkas_line_generasi_baru():
    """Log line dihapus (reset data): nomor seq mulai dari 1 lagi, kursor lama tidak berlaku."""
    assert mulai_dari(41, "g-lama", "g-baru") == 0
    assert mulai_dari(0, "", "g1") == 0


def test_kursor_kosong_bawaan():
    assert KursorLine() == KursorLine(generasi="", seq=0, dibuang=0)
