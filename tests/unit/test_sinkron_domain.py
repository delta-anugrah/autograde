"""Last Sync: aturan murni status sambungan ke AutoERP dan Cloud Photo.

Permintaan user 2026-09-27: satu bagian **Last Sync** berisi AutoERP dan Cloud
Photo. Tiap baris menjawab dua hal yang sengaja dipisah:

- `terakhir`: kapan data terakhir benar-benar tersinkron;
- `keadaan`: apakah sambungannya hidup SEKARANG.

Foto naik ke R2 tiap jam, jadi "terakhir 13:05" pada jam 13:50 itu normal.
Warnanya ditentukan hasil percobaan terakhir, bukan umur `terakhir`.
"""

from __future__ import annotations

from palmgrade.domain.sinkron import (
    MEMERIKSA,
    TERPUTUS,
    TERSAMBUNG,
    TIDAK_DIPAKAI,
    Jejak,
    gabung_cloud,
    galat_jaringan_http,
    keadaan,
    ringkas,
)


def test_belum_ada_cek_sama_sekali_berarti_memeriksa():
    assert keadaan([Jejak(), Jejak()], aktif=True) == MEMERIKSA
    assert keadaan([], aktif=True) == MEMERIKSA


def test_tidak_dipakai_menang_atas_apa_pun():
    j = Jejak()
    j.gagal(100.0, "timeout")
    assert keadaan([j], aktif=False) == TIDAK_DIPAKAI
    assert ringkas([j], aktif=False, antre=3, terakhir=None)["sejak"] is None


def test_jam_terakhir_diteruskan_apa_adanya():
    """Jam Last Sync dicatat pemanggil (hanya saat data lewat), bukan dari cek."""
    j = Jejak()
    j.berhasil(160.0)

    r = ringkas([j], aktif=True, antre=0, terakhir=100.0)
    assert (r["keadaan"], r["terakhir"]) == (TERSAMBUNG, 100.0)


def test_putus_mencatat_awal_deretan_bukan_kegagalan_terbaru():
    j = Jejak()
    j.berhasil(100.0)

    assert j.gagal(200.0, "connect timeout") is True
    assert j.gagal(260.0, "connect timeout lagi") is False

    r = ringkas([j], aktif=True, antre=5, terakhir=100.0)
    assert (r["keadaan"], r["sejak"], r["terakhir"], r["antre"]) == (TERPUTUS, 200.0, 100.0, 5)
    assert j.pesan == "connect timeout lagi"


def test_pulih_menghapus_deretan_gagal_dan_memberi_tahu():
    j = Jejak()
    j.gagal(200.0, "timeout")

    assert j.berhasil(300.0) is True
    assert j.berhasil(360.0) is False
    assert (keadaan([j], aktif=True), j.gagal_sejak, j.pesan) == (TERSAMBUNG, None, None)


def test_satu_sumber_gagal_cukup_untuk_putus_walau_sumber_lain_berhasil():
    """Cek tiap menit yang lolos tidak menghapus tarikan data yang ditolak: dua sumber
    yang menilai beda dulu membuat titiknya berkedip merah-hijau."""
    cek, tarik = Jejak(), Jejak()
    tarik.gagal(200.0, "HTTP 417")
    cek.berhasil(260.0)

    r = ringkas([cek, tarik], aktif=True, antre=0, terakhir=None)
    assert (r["keadaan"], r["sejak"]) == (TERPUTUS, 200.0)


def test_galat_jaringan_http():
    """Tanpa jawaban atau gateway mati = jaringan. Yang lain = server menjawab."""
    assert [galat_jaringan_http(s) for s in (None, 502, 503, 504)] == [True] * 4
    assert [galat_jaringan_http(s) for s in (500, 401, 403, 404, 417)] == [False] * 5


def test_pesan_gagal_dipendekkan_dan_dirapikan():
    j = Jejak()
    j.gagal(1.0, "HTTP\n500   " + "x" * 500)

    assert "\n" not in j.pesan and "   " not in j.pesan
    assert len(j.pesan) <= 200


def _konsol(keadaan_, terakhir=None, sejak=None, antre=0):
    return {"keadaan": keadaan_, "terakhir": terakhir, "sejak": sejak, "antre": antre}


def _unggah(terakhir=None, gagal_sejak=None, antre=0, aktif=True):
    return {"aktif": aktif, "terakhir": terakhir, "gagal_sejak": gagal_sejak, "antre": antre, "rusak": 0}


def test_cloud_jam_terakhir_paling_baru_dan_antrean_dijumlah():
    r = gabung_cloud(_konsol(TERSAMBUNG, terakhir=50.0, antre=1), {
        "line-1": _unggah(terakhir=100.0, antre=4),
        "line-2": _unggah(terakhir=90.0, antre=2),
    })

    assert (r["keadaan"], r["terakhir"], r["antre"]) == (TERSAMBUNG, 100.0, 7)
    assert [p["line_code"] for p in r["per_line"]] == ["line-1", "line-2"]


def test_satu_line_gagal_membuat_cloud_terputus_sejak_yang_paling_awal():
    r = gabung_cloud(_konsol(TERSAMBUNG, terakhir=50.0), {
        "line-1": _unggah(terakhir=100.0),
        "line-2": _unggah(terakhir=90.0, gagal_sejak=120.0),
        "line-3": _unggah(terakhir=80.0, gagal_sejak=110.0),
    })

    assert (r["keadaan"], r["sejak"]) == (TERPUTUS, 110.0)


def test_cek_r2_dari_konsol_gagal_juga_terputus():
    r = gabung_cloud(_konsol(TERPUTUS, terakhir=50.0, sejak=70.0), {"line-1": _unggah(terakhir=100.0)})

    assert (r["keadaan"], r["sejak"]) == (TERPUTUS, 70.0)


def test_line_mati_atau_versi_lama_tidak_membuat_cloud_merah():
    """Line mati sudah terlihat di kartunya sendiri (OFFLINE). Cloud Photo
    cuma bicara soal sambungan ke cloud."""
    r = gabung_cloud(_konsol(TERSAMBUNG, terakhir=50.0), {"line-1": None, "line-2": _unggah(terakhir=100.0)})

    assert r["keadaan"] == TERSAMBUNG
    assert r["per_line"][0] == {"line_code": "line-1", "terbaca": False}


def test_cloud_tidak_dipakai_kalau_konsol_dan_semua_line_tanpa_r2():
    r = gabung_cloud(_konsol(TIDAK_DIPAKAI), {"line-1": _unggah(aktif=False), "line-2": None})

    assert r["keadaan"] == TIDAK_DIPAKAI


def test_konsol_tanpa_r2_tapi_line_mengunggah_tetap_dianggap_dipakai():
    r = gabung_cloud(_konsol(TIDAK_DIPAKAI), {"line-1": _unggah(terakhir=100.0)})

    assert (r["keadaan"], r["terakhir"]) == (TERSAMBUNG, 100.0)


def test_baru_menyala_tanpa_data_apa_pun_masih_memeriksa():
    r = gabung_cloud(_konsol(MEMERIKSA), {"line-1": _unggah(), "line-2": None})

    assert (r["keadaan"], r["terakhir"]) == (MEMERIKSA, None)


def test_cloud_memeriksa_selama_konsol_belum_cek_walau_jamnya_tersimpan():
    """Sesudah konsol restart, jam R2 yang tersimpan bukan bukti sambungannya hidup
    SEKARANG. Hijau baru boleh sesudah cek pertama, atau kalau line melaporkan upload."""
    r = gabung_cloud(_konsol(MEMERIKSA, terakhir=900.0), {"line-1": _unggah(), "line-2": None})

    assert (r["keadaan"], r["terakhir"]) == (MEMERIKSA, 900.0)


def test_laporan_line_yang_rusak_tidak_menjatuhkan_gabungan():
    """Line versi kelak bisa mengirim bentuk lain; polling layar 2 detik tidak boleh
    ikut mati karenanya."""
    r = gabung_cloud(_konsol(TERSAMBUNG, terakhir=50.0), {
        "line-1": {"aktif": True, "terakhir": "kemarin", "gagal_sejak": None, "antre": "banyak"},
        "line-2": "bukan dict",
    })

    assert (r["keadaan"], r["terakhir"], r["antre"]) == (TERSAMBUNG, 50.0, 0)
