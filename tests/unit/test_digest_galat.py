"""Isi ringkasan galat untuk Discord (batch 3.5): kelompok, redaksi, batas 2000 karakter."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from palmgrade.domain.digest_galat import (
    BATAS_KARAKTER_DISCORD,
    KelompokGalat,
    identitas_pabrik,
    redaksi_discord,
    sidik_digest,
    susun_pesan,
)

WIB = ZoneInfo("Asia/Jakarta")
#: 2026-09-30 10:00 WIB
T = datetime(2026, 9, 30, 10, 0, tzinfo=WIB).timestamp()


def _k(pesan: str = "kamera putus", *, jumlah: int = 1, line: str | None = "line-2",
       pertama: float = T, terakhir: float | None = None, source: str = "palmgrade.workers.x") -> KelompokGalat:
    return KelompokGalat("ERROR", source, line, pesan, pertama, terakhir or pertama, jumlah)


def _susun(kelompok, **kw):
    kw.setdefault("identitas", "PT Nexio (host pc-lampung)")
    kw.setdefault("versi", "v1.20.0")
    kw.setdefault("zona", WIB)
    return susun_pesan(kelompok, **kw)


def test_galat_berbeda_kode_http_tidak_sekelompok():
    a = sidik_digest("ERROR", "s", "line-1", "gagal kirim, HTTP 404")
    b = sidik_digest("ERROR", "s", "line-1", "gagal kirim, HTTP 500")
    assert a != b


def test_galat_yang_cuma_beda_id_satu_kelompok_beda_line_beda_kelompok():
    a = sidik_digest("ERROR", "s", "line-1", "assignment 11111111-2222-4333-8444-555555555555 hilang")
    b = sidik_digest("ERROR", "s", "line-1", "assignment 99999999-2222-4333-8444-555555555555 hilang")
    c = sidik_digest("ERROR", "s", "line-2", "assignment 99999999-2222-4333-8444-555555555555 hilang")
    assert a == b
    assert a != c
    assert sidik_digest("ERROR", "s", None, "x") != sidik_digest("ERROR", "s", "line-1", "x")


def test_redaksi_menyaring_rahasia_dan_alamat_webhook():
    teks = redaksi_discord(
        "gagal token=abc123 ke https://discord.com/api/webhooks/123/RahasiaSekali lalu x"
    )
    assert "abc123" not in teks
    assert "RahasiaSekali" not in teks
    assert teks.endswith("lalu x")


def test_identitas_memakai_company_dan_host():
    assert identitas_pabrik("PT Nexio", "pc-lampung") == "PT Nexio (host pc-lampung)"
    assert identitas_pabrik("", "pc-lampung") == "ERP_COMPANY belum diisi (host pc-lampung)"
    assert identitas_pabrik("PT Nexio", "") == "PT Nexio"


def test_kosong_tanpa_pesan():
    assert _susun([]) == []


def test_satu_pesan_memuat_identitas_versi_hitungan_dan_jam_pabrik():
    (pesan,) = _susun([_k(jumlah=12, terakhir=T + 14 * 60), _k("plc lambat", line=None)])

    baris = pesan.splitlines()
    assert baris[0] == "**AutoGrade PT Nexio (host pc-lampung)** · versi v1.20.0"
    assert baris[1] == "Ringkasan galat: 13 kejadian, 2 jenis, 10:00 sampai 10:14 WIB."
    assert baris[2] == "- 12x line-2 · palmgrade.workers.x: `kamera putus` (10:00 sampai 10:14)"
    assert baris[3] == "- 1x konsol · palmgrade.workers.x: `plc lambat` (10:00)"
    assert baris[-1] == "Rincian dan traceback: konsol, tab Log."


def test_urut_hitungan_terbanyak_dulu():
    (pesan,) = _susun([_k("jarang", jumlah=1), _k("sering", jumlah=50)])
    assert pesan.index("sering") < pesan.index("jarang")


def test_hari_lain_ditulis_dengan_tanggal():
    kemarin = T - 86400
    (pesan,) = _susun([_k("lama", pertama=kemarin), _k("baru")])
    assert "`lama` (29/09 10:00)" in pesan


def test_backtick_baris_baru_dan_pesan_panjang_dirapikan():
    (pesan,) = _susun([_k("a`b\nc " + "x" * 1000)])
    baris = pesan.splitlines()[2]
    assert "`a'b c " in baris
    assert "..." in baris
    assert len(baris) < 400


def test_ringkasan_panjang_dipecah_bernomor_dan_tiap_pesan_di_bawah_batas():
    kelompok = [_k(f"galat berbeda nomor {'z' * 200} {i}", jumlah=100 - i, line=f"line-{i}") for i in range(30)]

    pesan = _susun(kelompok)

    assert 1 < len(pesan) <= 5
    assert all(len(p) <= BATAS_KARAKTER_DISCORD for p in pesan)
    assert pesan[0].startswith(f"(1/{len(pesan)})\n**AutoGrade")
    assert pesan[-1].endswith("Rincian dan traceback: konsol, tab Log.")


def test_terlalu_banyak_jenis_disebut_jumlah_sisanya():
    kelompok = [_k(f"galat {'q' * 250} {i}", jumlah=1000 - i, line=f"l{i}") for i in range(200)]

    pesan = _susun(kelompok, maks_pesan=2)

    assert len(pesan) == 2
    assert all(len(p) <= BATAS_KARAKTER_DISCORD for p in pesan)
    assert "jenis galat lain." in pesan[-1]


def test_tanpa_em_dash():
    (pesan,) = _susun([_k(terakhir=T + 600)])
    assert "—" not in pesan
    assert " - " not in pesan


def test_identitas_sangat_panjang_tidak_membuat_pesan_lewat_batas():
    identitas = "PT " + "A" * 2500
    (pesan,) = _susun([_k()], identitas=identitas)
    assert len(pesan) <= BATAS_KARAKTER_DISCORD
    assert "..." in pesan.splitlines()[0]


def test_versi_sangat_panjang_tidak_membuat_pesan_lewat_batas():
    (pesan,) = _susun([_k()], versi="v" + "9" * 2500)
    assert len(pesan) <= BATAS_KARAKTER_DISCORD
    assert "..." in pesan.splitlines()[0]


def test_banyak_ukuran_pesan_selalu_di_bawah_batas_dan_tidak_hilang_diam_diam():
    import random

    acak = random.Random(0)
    for _ in range(200):
        n = acak.choice([1, 2, 5, 20, 50, 300, 3000])
        identitas = "PT " + "X" * acak.choice([1, 10, 500, 3000])
        versi = "v" + "1" * acak.choice([1, 5, 500, 3000])
        kelompok = [_k(f"galat {i} " + "z" * acak.choice([0, 5, 400, 3000]), jumlah=n - i, line=f"l{i}")
                    for i in range(n)]
        pesan = _susun(kelompok, identitas=identitas, versi=versi)
        assert pesan, "ringkasan tidak boleh hilang total"
        for p in pesan:
            assert len(p) <= BATAS_KARAKTER_DISCORD, (n, len(p))
