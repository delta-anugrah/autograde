"""Sumber kamera satu line: pilihan yang sah dan batas kewarasannya.

`CAMERA_TYPE` dulu cuma hidup di `.env`, satu nilai untuk keempat container.
Mengubahnya berarti AnyDesk ke PC pabrik, edit berkas, restart. Sekarang tiap
line dipilih sendiri dari layar support.

**Empat pilihan layar, tiga nilai `CAMERA_TYPE`.** `webcam` dan `video`
sama-sama `OpenCVCamera`; yang membedakan cuma ada-tidaknya berkas. Pemisahan
itu ada di layar, bukan di `CAMERA_TYPE`, supaya nilai env-nya tidak berubah
arti bagi kode yang sudah membacanya.

**Berkas wajib untuk `video` dan `foto`, terlarang untuk dua lainnya.**
`OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat berkasnya tidak terbaca
(fail-fast), berbeda dengan `hikrobot` yang cuma memberi peringatan. Berkas
kosong yang lolos ke sini berarti: line boot, gagal, mati, `restart:
unless-stopped` menyalakannya lagi, gagal lagi — selamanya. Sebaliknya berkas
yang diisi untuk `hikrobot` tidak pernah dibaca siapa pun: keadaan yang terlihat
benar di layar dan tidak melakukan apa-apa.

Nama berkas **disaring, bukan di-escape**. Berkas dipilih dari daftar yang
konsol susun sendiri dari folder `media/`, jadi nilai di luar daftar itu payload
yang dibuat tangan, dan satu-satunya alasan membuatnya adalah keluar dari
folder itu.

Bebas dari numpy/torch/cv2 supaya ikut CI ringan (aturan yang sama dengan
`domain/grade_class.py`).
"""
from __future__ import annotations

from typing import Any

#: Pilihan sebagaimana layar menampilkannya, dalam urutan tampil.
SUMBER: tuple[str, ...] = ("hikrobot", "webcam", "video", "foto")

#: Pilihan yang berkasnya wajib ada. Sisanya justru menolak berkas.
BUTUH_BERKAS: frozenset[str] = frozenset({"video", "foto"})

#: Pilihan layar -> nilai `CAMERA_TYPE` yang dibaca `Settings`.
CAMERA_TYPE_UNTUK: dict[str, str] = {
    "hikrobot": "hikrobot",
    "webcam": "opencv",
    "video": "opencv",
    "foto": "photo",
}

#: Karakter yang membuat nama berkas bisa menunjuk keluar dari `media/`.
_BERBAHAYA = ("/", "\\", "..", "\x00")

_FIELD = frozenset({"sumber", "berkas", "ulang"})


class SumberTidakSah(ValueError):
    """Nilai di luar batas. Route menerjemahkannya jadi 400."""


def _boolean(nilai: Any) -> bool:
    """`True`/`False` dari boolean JSON, string input HTML, atau apa pun."""
    if isinstance(nilai, str):
        return nilai.strip().lower() in ("1", "true", "ya", "on")
    return bool(nilai)


def bersihkan_sumber(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload satu line dari layar -> dict siap simpan.

    Field asing ditolak, tidak diabaikan: salah ketik nama field akan terlihat
    berhasil padahal tidak mengubah apa pun.
    """
    if not isinstance(payload, dict):
        raise SumberTidakSah("setelan sumber harus objek")

    asing = set(payload) - _FIELD
    if asing:
        raise SumberTidakSah(f"field tidak dikenal: {', '.join(sorted(asing))}")

    sumber = str(payload.get("sumber") or "").strip().lower()
    if sumber not in SUMBER:
        raise SumberTidakSah(f"sumber harus salah satu dari: {', '.join(SUMBER)}")

    berkas = str(payload.get("berkas") or "").strip()
    if berkas and any(tanda in berkas for tanda in _BERBAHAYA):
        raise SumberTidakSah(
            "nama berkas tidak boleh memuat pemisah folder atau '..'"
        )

    if sumber in BUTUH_BERKAS and not berkas:
        raise SumberTidakSah(f"{sumber} butuh berkas")
    if sumber not in BUTUH_BERKAS and berkas:
        raise SumberTidakSah(f"{sumber} tidak memakai berkas")

    return {"sumber": sumber, "berkas": berkas, "ulang": _boolean(payload.get("ulang"))}
