"""Gambar QR untuk kartu truk, dibuat di server.

**Di server, bukan pustaka JavaScript dari CDN.** `console.html` nol referensi
`https://` dengan sengaja: layar operator harus tetap terbuka saat internet mati,
dan QR yang gagal dimuat berarti gerbang timbangan berhenti. `segno` dipilih karena
pure-Python, nol dependency, dan 77 KB — jadi bisa ikut ke CI ringan tanpa menyeret
apa pun.

Isinya cuma plat ternormalisasi (`domain/qr.py`), dan **divalidasi ulang di sini**:
isi QR datang dari baris truk di database, dan baris itu bisa berisi apa saja kalau
pernah diisi salah. Kartu QR yang isinya bukan plat adalah kartu yang tidak akan
pernah bisa di-scan, dan tidak ada yang tahu sampai truknya sampai di gerbang.
"""

from __future__ import annotations

import io

import segno

from ..domain.qr import baca_qr, isi_qr_untuk

# Tingkat koreksi kesalahan. 'm' = 15% modul boleh rusak dan QR-nya masih terbaca.
# Bukan 'l' (7%): kartunya hidup di kaca truk — hujan, debu sawit, gesekan. Bukan 'h'
# (30%) karena polanya jadi lebih rapat, dan pola rapat justru lebih sulit dibaca
# scanner dari layar HP yang buram.
KOREKSI = "m"

# Ukuran satu modul QR dalam piksel, dan lebar bingkai putih di sekelilingnya.
# Bingkai itu bagian dari spesifikasi QR ("quiet zone"): tanpa itu scanner sering
# gagal menemukan batas kodenya, terutama di kartu yang ditempel rapat ke stiker lain.
_SKALA = 8
_BINGKAI = 2


def png_qr(plat: str) -> bytes:
    """PNG QR untuk satu plat. Raise `OperatorError` kalau platnya tidak sah."""
    isi = isi_qr_untuk(plat)  # menormalkan, dan menolak yang kosong
    _pastikan_terbaca(isi)
    buf = io.BytesIO()
    # `make_qr`, bukan `make`: `make` memilih **Micro QR** untuk teks sependek plat,
    # dan scanner gerbang kelas murah - juga OpenCV - tidak bisa membacanya sama
    # sekali (terbukti: decoder mengembalikan string kosong). Kartunya kelihatan
    # baik-baik saja di layar, dan baru ketahuan tidak terbaca di gerbang.
    segno.make_qr(isi, error=KOREKSI).save(buf, kind="png", scale=_SKALA, border=_BINGKAI)
    return buf.getvalue()


def _pastikan_terbaca(isi: str) -> None:
    """Yang dicetak harus bisa dibaca kembali lane scan.

    Dijalankan di sini, bukan dipercaya dari pemanggil: kalau dua sisi ini berbeda
    aturan, kita mencetak setumpuk kartu yang tidak bisa dibaca sendiri — dan itu
    ketahuannya di gerbang pabrik, sesudah semuanya tercetak dan tertempel.
    """
    baca_qr(isi)
