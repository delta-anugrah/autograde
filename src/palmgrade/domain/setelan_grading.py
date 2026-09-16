"""Setelan grading yang boleh diubah dari konsol, dan batas kewarasannya.

`CONF_THRESHOLD` dan `MINIMUM_SIZE` dulu cuma hidup di `.env`: mengubahnya
berarti AnyDesk ke PC pabrik, edit berkas, restart tiga container. Sekarang
keduanya bisa diatur dari layar developer (`role=support`).

**Ini angka yang mengubah uang**, jadi modul ini sengaja rewel:

- `conf_threshold` 0 membuat model melaporkan tiap bercak sebagai buah; di atas 1
  membuatnya tidak pernah melaporkan apa pun. Dua-duanya mematikan grading tanpa
  satu pun pesan error — line tetap "jalan", angkanya saja yang tidak pernah naik.
- `minimum_size` 0 mematikan penjaga janjang kecil; terlalu besar membuat SEMUA
  janjang terhitung kekecilan dan di-REJ. Satu shift penuh tonase yang salah, dan
  rekap yang sudah naik ke AutoERP tidak ikut berubah.

Batasnya lebar dengan sengaja: yang dijaga di sini cuma nilai yang **pasti**
salah. Menyempitkannya jadi "yang kami kira wajar" akan menghalangi PKS yang
kameranya memang beda.

Nilainya **satu untuk semua line** (keputusan operator 2026-09-16), jadi
penyimpanannya satu baris di `sync_state`, bukan tiga.
"""
from __future__ import annotations

from typing import Any

KUNCI_SETELAN = "setelan_grading"

#: field -> (minimum eksklusif, maksimum inklusif). Lihat docstring modul soal
#: kenapa batasnya dibuat lebar.
BATAS: dict[str, tuple[float, float]] = {
    "conf_threshold": (0.0, 1.0),
    # 100 juta piksel: jauh di atas sensor mana pun yang dipakai (1224x1024 ≈ 1,25
    # juta), jadi yang tersaring cuma salah ketik yang benar-benar ngawur.
    "minimum_size": (0.0, 100_000_000.0),
}


class SetelanTidakSah(ValueError):
    """Nilai di luar batas. Route menerjemahkannya jadi 400, seperti timestamp cacat."""


def _angka(field: str, nilai: Any) -> float:
    if isinstance(nilai, bool) or nilai is None:
        raise SetelanTidakSah(f"{field} harus angka")
    if isinstance(nilai, str):
        # Papan ketik Indonesia menulis desimal dengan koma. Menolaknya membuat
        # operator mengetik ulang tanpa tahu apa yang salah.
        nilai = nilai.strip().replace(",", ".")
        if not nilai:
            raise SetelanTidakSah(f"{field} harus diisi")
    try:
        return float(nilai)
    except (TypeError, ValueError) as exc:
        raise SetelanTidakSah(f"{field} harus angka") from exc


def bersihkan_setelan(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload dari layar -> dict siap simpan. `SetelanTidakSah` kalau meleset.

    Field asing ditolak, tidak diabaikan: salah ketik nama field yang diterima
    diam-diam akan terlihat berhasil padahal tidak mengubah apa pun.
    """
    if not isinstance(payload, dict):
        raise SetelanTidakSah("setelan harus objek")

    asing = set(payload) - set(BATAS)
    if asing:
        raise SetelanTidakSah(f"field tidak dikenal: {', '.join(sorted(asing))}")

    kurang = set(BATAS) - set(payload)
    if kurang:
        raise SetelanTidakSah(f"field wajib belum diisi: {', '.join(sorted(kurang))}")

    bersih: dict[str, Any] = {}
    for field, (bawah, atas) in BATAS.items():
        nilai = _angka(field, payload[field])
        if not (bawah < nilai <= atas):
            raise SetelanTidakSah(
                f"{field} harus lebih besar dari {bawah:g} dan maksimal {atas:g}"
            )
        # `minimum_size` itu luas piksel — bilangan bulat, dan menyimpannya
        # sebagai float membuat perbandingan `area < minimum_size` bekerja pada
        # angka yang bukan piksel.
        bersih[field] = nilai if field == "conf_threshold" else int(nilai)
    return bersih
