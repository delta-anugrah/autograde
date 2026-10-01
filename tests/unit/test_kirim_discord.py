"""Aturan kirim Discord (batch 3.5): arti jawaban, kapan menyusun, keadaan layar."""
from __future__ import annotations

import pytest

from palmgrade.domain.kirim_discord import (
    JEDA_429_MAKS_S,
    JEDA_ANTAR_RINGKASAN_S,
    JEDA_DITOLAK_S,
    JEDA_GAGAL_DASAR_S,
    JEDA_KUMPUL_S,
    KEADAAN_AKTIF,
    KEADAAN_DITOLAK,
    KEADAAN_ISI_DITOLAK,
    KEADAAN_MATI,
    KEADAAN_TERTAHAN,
    KEADAAN_URL_SALAH,
    NasibDiscord,
    boleh_susun,
    keadaan_lapor,
    nilai_jawaban_discord,
    url_webhook_sah,
)

URL = "https://discord.com/api/webhooks/1/palsu"


@pytest.mark.parametrize("status", [200, 204])
def test_2xx_terkirim(status):
    assert nilai_jawaban_discord(status, None).nasib is NasibDiscord.TERKIRIM


def test_429_menunggu_selama_yang_diminta_dibatasi():
    assert nilai_jawaban_discord(429, 2.5).tunggu_s == 2.5
    assert nilai_jawaban_discord(429, None).tunggu_s == JEDA_GAGAL_DASAR_S
    assert nilai_jawaban_discord(429, 99999).tunggu_s == JEDA_429_MAKS_S
    assert nilai_jawaban_discord(429, 1).nasib is NasibDiscord.TUNGGU


@pytest.mark.parametrize("status", [401, 403, 404])
def test_4xx_ditolak_berhenti_sejam(status):
    putusan = nilai_jawaban_discord(status, None)
    assert (putusan.nasib, putusan.tunggu_s) == (NasibDiscord.DITOLAK, JEDA_DITOLAK_S)


def test_400_isi_ditolak_bukan_webhook_salah():
    """400 = Discord menolak ISI pesan, bukan alamatnya: saran "periksa webhook" salah,
    dan pesan itu yang harus disisihkan, bukan seluruh laporan berhenti."""
    assert nilai_jawaban_discord(400, None).nasib is NasibDiscord.ISI_DITOLAK


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com:99999/api/webhooks/1/x",   # port di luar jangkauan
        "https://discord.com:abc/api/webhooks/1/x",     # port bukan angka
        "https:///api/webhooks/1/x",                    # tanpa host
    ],
)
def test_alamat_https_yang_tidak_bisa_dipakai_bukan_alamat_sah(url):
    """Dulu cuma awalan yang diperiksa: httpx menolaknya tiap kirim dan layar tetap "aktif"."""
    assert url_webhook_sah(url) is False
    assert keadaan_lapor(url, None, None) == KEADAAN_URL_SALAH


@pytest.mark.parametrize("status", [500, 502, 503, 301])
def test_5xx_dan_lainnya_diulang(status):
    assert nilai_jawaban_discord(status, None).nasib is NasibDiscord.ULANG


def test_tidak_menyusun_tanpa_galat_atau_selama_ada_kiriman():
    assert not boleh_susun(sekarang=10_000, ada_kiriman=False, tertua_masuk_at=None, ringkasan_terakhir_at=None)
    assert not boleh_susun(sekarang=10_000, ada_kiriman=True, tertua_masuk_at=1.0, ringkasan_terakhir_at=None)


def test_menunggu_jendela_kumpul_sesudah_galat_pertama():
    masuk = 10_000.0
    assert not boleh_susun(sekarang=masuk + JEDA_KUMPUL_S - 1, ada_kiriman=False,
                           tertua_masuk_at=masuk, ringkasan_terakhir_at=None)
    assert boleh_susun(sekarang=masuk + JEDA_KUMPUL_S, ada_kiriman=False,
                       tertua_masuk_at=masuk, ringkasan_terakhir_at=None)


def test_paling_sering_satu_ringkasan_tiap_15_menit():
    terakhir = 50_000.0
    assert not boleh_susun(sekarang=terakhir + JEDA_ANTAR_RINGKASAN_S - 1, ada_kiriman=False,
                           tertua_masuk_at=0.0, ringkasan_terakhir_at=terakhir)
    assert boleh_susun(sekarang=terakhir + JEDA_ANTAR_RINGKASAN_S, ada_kiriman=False,
                       tertua_masuk_at=0.0, ringkasan_terakhir_at=terakhir)


def test_keadaan_layar():
    assert keadaan_lapor("", None, None) == KEADAAN_MATI
    assert keadaan_lapor("http://discord.com/x", None, None) == KEADAAN_URL_SALAH
    assert keadaan_lapor(URL, None, None) == KEADAAN_AKTIF
    assert keadaan_lapor(URL, "Discord tidak terjangkau (ConnectError)", None) == KEADAAN_TERTAHAN
    assert keadaan_lapor(URL, "Discord menjawab HTTP 503", 503) == KEADAAN_TERTAHAN
    assert keadaan_lapor(URL, "Discord menjawab HTTP 404", 404) == KEADAAN_DITOLAK
    assert keadaan_lapor(URL, "Discord menjawab HTTP 400", 400) == KEADAAN_ISI_DITOLAK
