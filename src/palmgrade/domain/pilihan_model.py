"""Model deteksi per line: nama berkas yang sah dan bentuk pilihan dari layar.

Dulu satu `MODEL_FILE` di `.env` untuk ketiga line, diedit tangan lewat
AnyDesk. PC Lampung seminggu memuat model 3 kelas lama karena `.env` itu tidak
pernah ikut rilis kode (2026-09-23). Sekarang tiap line dipilih dari layar
Support dan disimpan sebagai `LINE_N_MODEL_FILE` di `media.env`.

Nilai kosong berarti "bawaan PC": line memakai `MODEL_FILE` dari `.env`. PC
yang belum pernah menyentuh layar ini tidak berubah perilaku.

Nama berkas **disaring, bukan di-escape** — aturan yang sama dengan
`domain/sumber_kamera`. Layar memilih dari daftar yang konsol susun sendiri
dari `models/release/`, jadi nama di luar daftar itu payload buatan tangan.
Newline ikut diblok karena nama ini ditulis apa adanya sebagai satu baris
`media.env`.

Bebas dari numpy/torch/cv2 supaya ikut CI ringan, dan bebas dari lapis service
supaya `core/config.py` (dibaca tiap proses, termasuk line) boleh memakainya.
"""
from __future__ import annotations

from typing import Any

#: Tiga line, dalam urutan tampil. Sengaja disalin, bukan diimpor dari
#: `services/media_env_service.LINE_CODES`: domain tidak bergantung pada
#: service. Tes `test_media_env_service` menjaga keduanya tetap sama.
LINE_MODEL: tuple[str, ...] = ("line-1", "line-2", "line-3")

_BERBAHAYA = ("/", "\\", "..", "\x00", "\n", "\r")


class ModelTidakSah(ValueError):
    """Nilai di luar batas. Route menerjemahkannya jadi 400."""


def bersihkan_nama_model(nama: Any) -> str:
    """Nama berkas model yang aman, atau `""` untuk bawaan PC.

    Yang dicek di sini cuma bentuk nama. Ada-tidaknya berkas dan cocok-tidaknya
    kelasnya diperiksa konsol, yang bisa melihat folder model.
    """
    if not isinstance(nama, str):
        raise ModelTidakSah("nama model harus teks")
    nama = nama.strip()
    if not nama:
        return ""
    if any(b in nama for b in _BERBAHAYA):
        raise ModelTidakSah(f"nama model tidak sah: {nama!r}")
    if not nama.endswith(".pt") or nama == ".pt":
        raise ModelTidakSah(f"{nama}: harus berkas .pt")
    return nama


def bersihkan_pilihan_model(payload: Any) -> dict[str, str]:
    """`{line: nama}` untuk tepat ketiga line, tiap nama sudah disaring."""
    if not isinstance(payload, dict):
        raise ModelTidakSah("payload harus objek")
    asing = set(payload) - set(LINE_MODEL)
    if asing:
        raise ModelTidakSah(f"line tidak dikenal: {', '.join(sorted(map(str, asing)))}")
    kurang = set(LINE_MODEL) - set(payload)
    if kurang:
        raise ModelTidakSah(f"line belum diisi: {', '.join(sorted(kurang))}")

    hasil: dict[str, str] = {}
    for kode in LINE_MODEL:
        try:
            hasil[kode] = bersihkan_nama_model(payload[kode])
        except ModelTidakSah as exc:
            raise ModelTidakSah(f"{kode}: {exc}") from exc
    return hasil
