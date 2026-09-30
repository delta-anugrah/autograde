"""Aturan mengirim ringkasan galat ke Discord (batch 3.5). Murni, tanpa I/O.

Internet pabrik sering putus, dan itu kondisi normal: ringkasan menunggu di disk dan
dikirim begitu jalannya ada, tidak pernah dibuang. Yang dijaga lajunya:

- paling sering SATU ringkasan tiap 15 menit, dikumpulkan 2 menit sesudah galat
  pertama supaya satu badai jadi satu pesan;
- selama masih ada pesan yang belum terkirim, tidak ada ringkasan baru: galat terus
  dihitung di antrean, jadi internet mati semalam = satu ringkasan, bukan 96;
- Discord tidak terjangkau atau 5xx: coba lagi 30 dtk berlipat sampai 15 menit;
- 429: tunggu selama yang diminta Discord;
- 4xx lain (401/403/404 webhook dihapus atau salah, 400): berhenti sejam, tidak
  berputar cepat, dan layar support menyebutnya.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

JEDA_ANTAR_RINGKASAN_S = 900.0
JEDA_KUMPUL_S = 120.0
JEDA_GAGAL_DASAR_S = 30.0
JEDA_GAGAL_MAKS_S = 900.0
JEDA_DITOLAK_S = 3600.0
JEDA_429_MAKS_S = 900.0
MAKS_KIRIM_PER_PUTARAN = 5


class NasibDiscord(Enum):
    TERKIRIM = "terkirim"
    #: Jaringan, timeout, 5xx: coba lagi dengan jeda berlipat.
    ULANG = "ulang"
    #: 429: tunggu `tunggu_s` dari Discord, bukan kegagalan.
    TUNGGU = "tunggu"
    #: 4xx lain: webhook atau isi ditolak. Berhenti sejam, tampil di layar support.
    DITOLAK = "ditolak"


@dataclass(frozen=True)
class PutusanDiscord:
    nasib: NasibDiscord
    tunggu_s: float = 0.0


def nilai_jawaban_discord(status: int, retry_after: float | None) -> PutusanDiscord:
    if 200 <= status < 300:
        return PutusanDiscord(NasibDiscord.TERKIRIM)
    if status == 429:
        tunggu = retry_after if retry_after is not None and retry_after > 0 else JEDA_GAGAL_DASAR_S
        return PutusanDiscord(NasibDiscord.TUNGGU, min(tunggu, JEDA_429_MAKS_S))
    if 400 <= status < 500:
        return PutusanDiscord(NasibDiscord.DITOLAK, JEDA_DITOLAK_S)
    return PutusanDiscord(NasibDiscord.ULANG)


def boleh_susun(
    *,
    sekarang: float,
    ada_kiriman: bool,
    tertua_masuk_at: float | None,
    ringkasan_terakhir_at: float | None,
) -> bool:
    """Ringkasan baru dibuat sekarang? Lihat docstring modul untuk ketiga syaratnya."""
    if ada_kiriman or tertua_masuk_at is None:
        return False
    if sekarang - tertua_masuk_at < JEDA_KUMPUL_S:
        return False
    return ringkasan_terakhir_at is None or sekarang - ringkasan_terakhir_at >= JEDA_ANTAR_RINGKASAN_S


#: Keadaan lapor Discord untuk layar support.
KEADAAN_MATI = "mati"
KEADAAN_URL_SALAH = "url_salah"
KEADAAN_AKTIF = "aktif"
KEADAAN_TERTAHAN = "tertahan"
KEADAAN_DITOLAK = "ditolak"


def url_webhook_sah(url: str) -> bool:
    return url.startswith("https://")


def keadaan_lapor(url: str, galat: str | None, status_http: int | None) -> str:
    """Satu kata untuk layar: mati / url_salah / aktif / tertahan / ditolak."""
    if not url:
        return KEADAAN_MATI
    if not url_webhook_sah(url):
        return KEADAAN_URL_SALAH
    if galat is None:
        return KEADAAN_AKTIF
    if status_http is not None and nilai_jawaban_discord(status_http, None).nasib is NasibDiscord.DITOLAK:
        return KEADAAN_DITOLAK
    return KEADAAN_TERTAHAN
