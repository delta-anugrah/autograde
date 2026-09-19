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

from .garis_capture import SUMBU, TEGAK

KUNCI_SETELAN = "setelan_grading"

#: field -> (minimum eksklusif, maksimum inklusif). Lihat docstring modul soal
#: kenapa batasnya dibuat lebar.
BATAS: dict[str, tuple[float, float]] = {
    "conf_threshold": (0.0, 1.0),
    # 100 juta piksel: jauh di atas sensor mana pun yang dipakai (1224x1024 ≈ 1,25
    # juta), jadi yang tersaring cuma salah ketik yang benar-benar ngawur.
    "minimum_size": (0.0, 100_000_000.0),
    # Garis capture, dalam ruang STREAM (px dari kiri). Batas bawahnya 0 dan
    # INKLUSIF (lihat `BAWAH_INKLUSIF`) karena 0 = garis mati = perilaku lama.
    # Batas atasnya lebar — 10.000 px — karena `STREAM_WIDTH` boleh diubah per
    # PKS; yang ditolak cuma angka yang pasti di luar layar mana pun, karena
    # garis di sana tidak akan pernah disentuh janjang dan line terlihat jalan
    # sambil tidak pernah memfoto apa pun.
    "garis_capture": (0.0, 10_000.0),
}

#: Field yang nilainya PILIHAN, bukan angka — divalidasi terhadap daftar, bukan
#: rentang. Satu-satunya anggotanya sejauh ini `sumbu_garis`, yang menentukan
#: garis capture tegak (conveyor mendatar) atau mendatar (conveyor menurun).
PILIHAN: dict[str, tuple[str, ...]] = {"sumbu_garis": SUMBU}

#: Field saklar (True/False). `mode_dev` menampilkan angka confidence di
#: kotak janjang — untuk support yang sedang menyetel ambang, BUKAN untuk
#: operator: dari jarak jauh "54%" terbaca seperti "54% matang".
SAKLAR: tuple[str, ...] = ("mode_dev",)

#: Field yang boleh tidak ada di payload, beserta nilai bawaannya.
#:
#: `garis_capture` ditambahkan belakangan (2026-09-18), dan konsol versi lama
#: (juga `.env` yang belum tahu field ini) mengirim payload tanpa dia. Menolaknya
#: 400 akan membuat line berhenti menerima setelan **sama sekali** — termasuk dua
#: setelan lain yang sudah lama jalan. Bawaan `0` = garis mati = perilaku lama.
OPSIONAL: dict[str, Any] = {"garis_capture": 0, "sumbu_garis": TEGAK, "mode_dev": False}

#: Field yang batas bawahnya INKLUSIF (`bawah <= nilai`), bukan eksklusif.
#:
#: `conf_threshold` 0 dan `minimum_size` 0 mematikan grading diam-diam, jadi
#: keduanya ditolak. `garis_capture` 0 justru sah dan berarti "tidak ada garis" —
#: tanpa ini tidak ada cara mengembalikan perilaku sebelum fitur ini ada.
BAWAH_INKLUSIF = frozenset({"garis_capture"})


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

    dikenal = set(BATAS) | set(PILIHAN) | set(SAKLAR)
    asing = set(payload) - dikenal
    if asing:
        raise SetelanTidakSah(f"field tidak dikenal: {', '.join(sorted(asing))}")

    kurang = dikenal - set(payload) - set(OPSIONAL)
    if kurang:
        raise SetelanTidakSah(f"field wajib belum diisi: {', '.join(sorted(kurang))}")

    bersih: dict[str, Any] = {}
    for field in SAKLAR:
        nilai = payload.get(field, OPSIONAL[field])
        # Layar mengirim boolean JSON; nilai lain ("true", 1) juga diterima
        # karena input HTML dan konsol lama tidak seragam. Yang ditolak cuma
        # yang tidak bisa dibaca sebagai ya/tidak sama sekali.
        if isinstance(nilai, str):
            nilai = nilai.strip().lower() in ("1", "true", "ya", "on")
        elif not isinstance(nilai, bool):
            nilai = bool(nilai)
        bersih[field] = nilai
    for field, sah in PILIHAN.items():
        nilai = payload.get(field, OPSIONAL[field])
        if nilai not in sah:
            # Ditolak DI SINI, bukan di jalur deteksi: gerbang simpan mencegah
            # nilai cacat sampai ke tiga line sekaligus, sementara jalur deteksi
            # sengaja memaafkan supaya line yang terlanjur memegang nilai aneh
            # tidak berhenti menggrading.
            raise SetelanTidakSah(
                f"{field} harus salah satu dari: {', '.join(sah)}"
            )
        bersih[field] = nilai

    for field, (bawah, atas) in BATAS.items():
        if field not in payload:
            bersih[field] = OPSIONAL[field]
            continue
        nilai = _angka(field, payload[field])
        inklusif = field in BAWAH_INKLUSIF
        sah = (bawah <= nilai <= atas) if inklusif else (bawah < nilai <= atas)
        if not sah:
            pembanding = "minimal" if inklusif else "lebih besar dari"
            raise SetelanTidakSah(
                f"{field} harus {pembanding} {bawah:g} dan maksimal {atas:g}"
            )
        # `minimum_size` itu luas piksel — bilangan bulat, dan menyimpannya
        # sebagai float membuat perbandingan `area < minimum_size` bekerja pada
        # angka yang bukan piksel. `garis_capture` sama: koordinat px.
        bersih[field] = nilai if field == "conf_threshold" else int(nilai)
    return bersih
