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
- sumber selesai: video tanpa ulang yang habis diputar, sumber uji yang memang
  berakhir, bukan line yang rusak;
- baru mulai: loop deteksi baru jalan atau gambar baru mengalir lagi sesudah
  jeda, dan frame pertama belum selesai.

Batch 3.6 menambah satu kerusakan lagi yang dinilai di sini: **frame berhenti**.
Kamera tersambung (atau ada sambung ulang yang berhasil sejak gambar terakhir)
tapi tidak mengirim satu gambar pun selama `ambang_detik`. Buah lewat tanpa disortir persis seperti AI
mati, jadi keduanya menaikkan coil ERROR dan membuat `/health` 503. Bedanya
dengan kamera putus: kamera putus = semua sambung ulang sejak gambar terakhir
GAGAL (kabel, IP, MVS masih memegang kamera); frame berhenti = paling sedikit satu
BERHASIL tapi gambarnya tetap tidak datang (Hikrobot yang berhenti mengirim tanpa
terputus, SDK yang macet).

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
#: Batch 3.6: kamera tersambung tapi tidak mengirim gambar.
KODE_FRAME_BERHENTI = "FRAME_BERHENTI"

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
    SUMBER_SELESAI = "sumber_selesai"
    FRAME_BERHENTI = "frame_berhenti"
    AI_MATI = "ai_mati"


#: Keadaan yang berarti buah lewat tanpa disortir padahal line terlihat hidup.
#: Dua-duanya menaikkan coil ERROR dan membuat `/health` 503.
KEADAAN_GAGAL = frozenset({KeadaanAi.AI_MATI, KeadaanAi.FRAME_BERHENTI})
_KODE = {KeadaanAi.AI_MATI: KODE_AI_MATI, KeadaanAi.FRAME_BERHENTI: KODE_FRAME_BERHENTI}


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
    #: Sumber yang memang berakhir (`CameraSource.exhausted`): video tanpa ulang.
    sumber_selesai: bool = False
    #: Sambung berhasil pertama sesudah yang GAGAL, sejak gambar terakhir: kamera
    #: kembali dari putus sungguhan, tenggang gambar dimulai lagi.
    kamera_pulih_at: float = 0.0
    #: Hasil sambung terakhir (boot atau sambung ulang) sejak gambar terakhir. None = belum ada.
    sambung_terakhir_ok: bool | None = None
    #: Ada sambung yang berhasil sejak gambar terakhir, walau yang sesudahnya gagal.
    sambung_ok_sejak_frame: bool = False


@dataclass(frozen=True)
class PenilaianAi:
    keadaan: KeadaanAi
    #: Detik sejak frame terakhir selesai digrading. None = belum pernah.
    umur_detik: float | None
    #: Jam monotonic sejak kapan line ditunggu tapi diam. Diisi hanya untuk
    #: keadaan di `KEADAAN_GAGAL`.
    diam_sejak: float | None = None

    @property
    def mati(self) -> bool:
        """AI mati SAJA. Tetap sempit dengan sengaja: konsol versi lama membaca
        `ai.mati` dan menulis "AI berhenti memproses", kalimat yang salah untuk
        kamera yang berhenti mengirim."""
        return self.keadaan is KeadaanAi.AI_MATI

    @property
    def gagal(self) -> bool:
        """Buah lewat tanpa disortir: AI mati ATAU frame berhenti."""
        return self.keadaan in KEADAAN_GAGAL

    @property
    def error_plc(self) -> bool:
        """Level coil ERROR. Kamera putus tetap menaikkannya persis seperti
        sebelum batch 2.1; AI mati (2.1) dan frame berhenti (3.6) ditambahkan.
        Keadaan lain tidak."""
        return self.keadaan is KeadaanAi.KAMERA_PUTUS or self.gagal


def _acuan_frame(f: FaktaAi) -> float:
    """Sejak kapan gambar ditunggu: frame terakhir, loop mulai, atau kamera
    kembali dari putus sungguhan, mana yang paling belakangan."""
    return max(f.frame_terakhir_at, f.dimulai_at, f.kamera_pulih_at)


def _tersambung(f: FaktaAi) -> bool:
    """`connected` yang sudah dicatat hasilnya. `connect()` menyetel `connected`
    sebelum `FrameCaptureWorker` mencatat hasil sambungnya; di sela itu hasil
    tercatat masih gagal dari percobaan sebelumnya. Tanpa ini tick PLC yang jatuh
    di sela itu, di akhir putus panjang, menulis satu ERROR frame berhenti palsu
    tepat saat kameranya kembali."""
    return f.kamera_tersambung and f.sambung_terakhir_ok is not False


def _frame_berhenti(f: FaktaAi) -> bool:
    """Kamera ADA (tersambung sekarang, atau ada sambung yang berhasil sejak gambar
    terakhir) tapi tidak ada gambar masuk selama lebih dari ambang.

    "Berhasil sejak gambar terakhir", bukan "sambung terakhir berhasil": Hikrobot
    yang berhenti mengirim diputus lalu disambung lagi oleh `FrameCaptureWorker`
    tiap lima grab gagal, dan sambungnya bisa berselang berhasil dan gagal (MVS
    atau handle lama yang masih memegang kamera). Menilai dari sambung terakhir
    saja membuat penilaian berkedip antara kamera putus (200) dan frame berhenti
    (503) tiap siklus. Kamera yang semua sambungnya sejak gambar terakhir gagal
    tetap kamera putus.
    """
    ada = _tersambung(f) or f.sambung_ok_sejak_frame
    return f.dimulai_at > 0 and ada and f.sekarang - _acuan_frame(f) > f.ambang_detik


def nilai_ai(f: FaktaAi) -> PenilaianAi:
    """Satu keadaan untuk satu line. Urutannya bagian dari aturan."""
    umur = f.sekarang - f.inferensi_selesai_at if f.inferensi_selesai_at > 0 else None

    # Sebelum kamera putus: video yang habis memutus dirinya sendiri
    # (`OpenCVCamera.grab_frame`), dan itu sumber uji yang selesai, bukan kabel.
    if f.sumber_selesai:
        return PenilaianAi(KeadaanAi.SUMBER_SELESAI, umur)
    berhenti = _frame_berhenti(f)
    if not _tersambung(f) and (f.grading_diblokir or not berhenti):
        return PenilaianAi(KeadaanAi.KAMERA_PUTUS, umur)
    if f.grading_diblokir:
        return PenilaianAi(KeadaanAi.LISENSI, umur)
    if f.dimulai_at <= 0:
        return PenilaianAi(KeadaanAi.MEMULAI, umur)
    if berhenti:
        return PenilaianAi(KeadaanAi.FRAME_BERHENTI, umur, diam_sejak=_acuan_frame(f))
    if f.sekarang - max(f.frame_terakhir_at, f.dimulai_at) > f.ambang_detik:
        # Kamera baru kembali dari putus sungguhan dan gambar pertamanya belum
        # tiba: masih di tenggang `kamera_pulih_at`. AI tidak bisa dituntut
        # tanpa gambar.
        return PenilaianAi(KeadaanAi.MEMULAI, umur)

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
        "kode": _KODE.get(p.keadaan),
        "sejak": sejak,
        "umur_detik": None if p.umur_detik is None else round(p.umur_detik, 1),
        "ambang_detik": int(ambang_detik),
    }


def kode_http_health(ai: dict[str, Any] | None) -> int:
    """503 hanya untuk AI mati dan frame berhenti (batch 3.6). Kamera putus,
    lisensi, dan sumber selesai tetap 200: gerbang update `autograde.sh` membaca
    `/health` dengan `curl -f` dan memundurkan versi yang tidak menjawab 200, dan
    tidak satu pun dari ketiganya salah versi. Gerbang itu selesai pada 200
    pertama, yang jatuh di tenggang `memulai`: line yang rusak SESUDAH start tidak
    memicu rollback (CLAUDE.md aturan 32)."""
    if not ai:
        return 200
    gagal = ai.get("mati") or ai.get("keadaan") in {k.value for k in KEADAAN_GAGAL}
    return 503 if gagal else 200


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
