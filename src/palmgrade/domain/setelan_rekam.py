"""Setelan rekam video yang boleh diubah dari layar developer, dan batas
kewarasannya.

Sengaja TIDAK di `.env`: mengubah `.env` di PC pabrik berarti AnyDesk, edit
berkas, lalu membuat ulang container — dan fitur ini dipakai justru saat sedang
menelusuri masalah, ketika membuat ulang container menghapus gejalanya.

Beda dari `setelan_grading`, angka di sini **tidak mengubah uang**: salah setel
cuma membuat videonya besar atau buram, bukan janjang salah dibuang. Jadi
batasnya lebar dan tujuannya cuma menyaring nilai yang pasti gagal di encoder.

Nilainya **satu untuk semua line**, seperti `setelan_grading` — penyimpanannya
satu baris di `sync_state`, bukan tiga.
"""
from __future__ import annotations

from typing import Any

KUNCI_SETELAN_REKAM = "setelan_rekam"

#: Nilai awal sebelum siapa pun menyimpan setelan. 1280x1024 — cukup untuk mata
#: manusia melihat gerakan janjang, dan jauh di bawah resolusi sensor (2448x2048)
#: yang dipakai model.
#:
#: `fps` bukan lagi setelan layar (kolomnya dicabut 2026-09-25): rekaman memakai
#: laju yang benar-benar dikirim kamera (`VideoRecorder._fps_efektif`), dan angka
#: ini cuma cadangan terakhir kalau kamera tidak melapor DAN `CAMERA_FPS=0`.
#: `bitrate_kbps` dicabut sama sekali — `cv2.VideoWriter` tidak menerima bitrate,
#: jadi angkanya tidak pernah sampai ke berkas. Kiriman lama yang masih
#: membawanya diabaikan seperti field asing lain.
BAWAAN: dict[str, int] = {
    "width": 1280,
    "height": 1024,
    "fps": 5,
}

#: field -> (minimum inklusif, maksimum inklusif).
BATAS: dict[str, tuple[int, int]] = {
    # 10.000 px jauh di atas sensor mana pun yang dipakai (2448x2048), jadi yang
    # tersaring cuma salah ketik yang benar-benar ngawur.
    "width": (2, 10_000),
    "height": (2, 10_000),
    # Di atas 60 fps tidak ada kamera di pabrik yang bisa memberi frame sebanyak
    # itu; 0 berarti video tanpa waktu.
    "fps": (1, 60),
}

#: Dimensi yang dipakai H.264 harus genap. Dibulatkan ke bawah, bukan ditolak:
#: operator yang mengetik 1281 bermaksud "sekitar 1280", bukan "gagalkan saya".
_GENAP = ("width", "height")


class SetelanRekamTidakSah(ValueError):
    """Nilai di luar batas, atau bukan angka."""


def bersihkan_setelan_rekam(payload: dict[str, Any]) -> dict[str, int]:
    """Kembalikan setelan lengkap yang sudah divalidasi.

    Field yang tidak disebut payload diisi dari `BAWAAN` — layar boleh mengirim
    satu field saja tanpa menghapus sisanya. Field asing diabaikan, bukan
    ditolak: layar versi berikutnya boleh mengirim yang belum dikenal build ini.
    """
    bersih: dict[str, int] = {}
    for field, bawaan in BAWAAN.items():
        if field not in payload or payload[field] is None:
            bersih[field] = bawaan
            continue

        mentah = payload[field]
        try:
            # `float` dulu supaya 8.0 dari JSON tidak ditolak, lalu `int` supaya
            # value input HTML ("8") juga lewat.
            nilai = int(float(str(mentah).strip()))
        except (TypeError, ValueError) as exc:
            raise SetelanRekamTidakSah(
                f"{field} harus angka, bukan {mentah!r}"
            ) from exc

        if field in _GENAP and nilai % 2:
            nilai -= 1

        bawah, atas = BATAS[field]
        if not bawah <= nilai <= atas:
            raise SetelanRekamTidakSah(
                f"{field} harus antara {bawah} dan {atas}, bukan {nilai}"
            )
        bersih[field] = nilai
    return bersih
