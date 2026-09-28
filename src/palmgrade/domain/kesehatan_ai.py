"""Apakah AI satu line masih memproses frame: aturan murni, tanpa I/O.

Sebelum batch 2.1, loop deteksi yang melempar exception tiap frame cuma menulis
log lalu tidur satu detik, selamanya. Coil ERROR PLC cuma mencerminkan
`camera.connected`, `/health` tetap "ok", dan kartu line di konsol tetap
terlihat sehat: buah lewat tanpa disortir tanpa satu alarm pun.

Yang dinilai di sini: kamera MENGIRIM gambar, tapi tidak ada frame yang SELESAI
digrading selama `ambang_detik`. Keadaan lain yang juga membuat AI diam punya
pemiliknya sendiri dan sengaja tidak dilaporkan sebagai AI mati, supaya alarm
ini tidak pernah berteriak serigala:

- kamera putus: kartu dan coil ERROR sudah menanganinya sejak dulu;
- lisensi habis: grading memang dihentikan dengan sengaja (banner lisensi);
- sumber diam (tidak ada frame masuk, misalnya video tanpa ulang yang habis):
  urusan kamera, bukan AI (batch 3.6);
- baru mulai: loop deteksi baru jalan atau gambar baru mengalir lagi sesudah
  jeda, dan frame pertama belum selesai.

Semua jam di sini `time.monotonic()` (lewat `RuntimeState.jam`): PC pabrik
yang offline lalu dapat internet bisa melompatkan jam dinding berjam-jam, dan
lompatan itu tidak boleh terbaca sebagai AI mati.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: Kode galat yang ditulis di kartu line konsol dan di `/health`.
KODE_AI_MATI = "AI_MATI"

#: Bawaan `AI_MATI_DETIK`. Beban nyata 300 janjang/jam/line = satu tiap 12
#: detik, jadi paling banyak dua atau tiga janjang lewat sebelum alarm. Sepuluh
#: kali lebih lama dari inferensi paling lambat yang pernah diukur (CPU Mac tanpa
#: GPU, 3 line, sekitar 3 detik per frame).
AMBANG_BAWAAN_DETIK = 30
#: Lebih pendek dari ini alarm bisa menyala di tengah jeda wajar (reconnect
#: kamera, rewind video), dan harus jauh di atas `JEDA_ALIRAN_DETIK`.
AMBANG_MIN_DETIK = 10
#: Sepuluh menit tanpa sortir sudah ratusan janjang; lebih dari itu bukan alarm.
AMBANG_MAKS_DETIK = 600

#: Jeda antar frame masuk yang dianggap "aliran baru". Semua sumber yang sah
#: mengirim paling sedikit satu frame per detik (Hikrobot 15 fps, video di laju
#: aslinya, foto dipacu `CAMERA_FPS`), jadi jeda lebih dari ini berarti gambar
#: sempat berhenti (reconnect, rewind) dan AI diberi tenggang dari awal lagi.
JEDA_ALIRAN_DETIK = 5.0


class KeadaanAi(StrEnum):
    SEHAT = "sehat"
    MEMULAI = "memulai"
    KAMERA_PUTUS = "kamera_putus"
    LISENSI = "lisensi"
    SUMBER_DIAM = "sumber_diam"
    AI_MATI = "ai_mati"


@dataclass(frozen=True)
class FaktaAi:
    """Yang dibaca dari satu line pada satu saat. Jam `0.0` = belum pernah."""

    sekarang: float
    ambang_detik: float
    kamera_tersambung: bool
    grading_diblokir: bool
    dimulai_at: float
    frame_terakhir_at: float
    aliran_frame_sejak: float
    inferensi_selesai_at: float


@dataclass(frozen=True)
class PenilaianAi:
    keadaan: KeadaanAi
    #: Detik sejak frame terakhir selesai digrading. None = belum pernah.
    umur_detik: float | None
    #: Jam monotonic sejak kapan AI ditunggu tapi diam. Diisi hanya saat AI_MATI.
    diam_sejak: float | None = None

    @property
    def mati(self) -> bool:
        return self.keadaan is KeadaanAi.AI_MATI

    @property
    def error_plc(self) -> bool:
        """Level coil ERROR. Kamera putus tetap menaikkannya persis seperti
        sebelum batch 2.1; AI mati ditambahkan. Keadaan lain tidak."""
        return self.keadaan in (KeadaanAi.KAMERA_PUTUS, KeadaanAi.AI_MATI)


def nilai_ai(f: FaktaAi) -> PenilaianAi:
    """Satu keadaan untuk satu line. Urutannya bagian dari aturan."""
    umur = f.sekarang - f.inferensi_selesai_at if f.inferensi_selesai_at > 0 else None

    if not f.kamera_tersambung:
        return PenilaianAi(KeadaanAi.KAMERA_PUTUS, umur)
    if f.grading_diblokir:
        return PenilaianAi(KeadaanAi.LISENSI, umur)
    if f.dimulai_at <= 0:
        return PenilaianAi(KeadaanAi.MEMULAI, umur)
    if f.sekarang - max(f.frame_terakhir_at, f.dimulai_at) > f.ambang_detik:
        return PenilaianAi(KeadaanAi.SUMBER_DIAM, umur)

    # AI baru boleh dituntut sejak loopnya jalan DAN sejak gambar mengalir lagi.
    ditunggu_sejak = max(f.dimulai_at, f.aliran_frame_sejak)
    acuan = max(f.inferensi_selesai_at, ditunggu_sejak)
    if f.sekarang - acuan <= f.ambang_detik:
        sudah_jalan = f.inferensi_selesai_at >= ditunggu_sejak
        return PenilaianAi(KeadaanAi.SEHAT if sudah_jalan else KeadaanAi.MEMULAI, umur)
    return PenilaianAi(KeadaanAi.AI_MATI, umur, diam_sejak=acuan)


def ke_kawat(
    p: PenilaianAi, *, ambang_detik: float, sekarang: float, jam_dinding: float
) -> dict[str, Any]:
    """Blok `ai` untuk `/health` dan `/internal/status`. Tanpa pesan galat mentah:
    blok ini sampai ke layar operator (aturan 27)."""
    sejak = None
    if p.diam_sejak is not None:
        sejak = round(jam_dinding - (sekarang - p.diam_sejak), 3)
    return {
        "keadaan": p.keadaan.value,
        "mati": p.mati,
        "kode": KODE_AI_MATI if p.mati else None,
        "sejak": sejak,
        "umur_detik": None if p.umur_detik is None else round(p.umur_detik, 1),
        "ambang_detik": int(ambang_detik),
    }


def kode_http_health(ai: dict[str, Any] | None) -> int:
    """503 hanya untuk AI mati. Kamera putus, lisensi, dan sumber diam tetap 200:
    launcher `autograde.sh` membaca `/health` dengan `curl -f` dan MEMUNDURKAN
    versi yang tidak sehat, dan tidak satu pun dari ketiganya salah versi."""
    return 503 if ai and ai.get("mati") else 200


def ambang_dari_teks(teks: str | None) -> int | None:
    """`AI_MATI_DETIK` → detik, dijepit ke [MIN, MAKS]. Kosong = bawaan.
    None = bukan bilangan bulat (pemanggil yang memutuskan dan mencatat)."""
    if teks is None or not teks.strip():
        return AMBANG_BAWAAN_DETIK
    try:
        nilai = int(teks.strip())
    except ValueError:
        return None
    return min(max(nilai, AMBANG_MIN_DETIK), AMBANG_MAKS_DETIK)
