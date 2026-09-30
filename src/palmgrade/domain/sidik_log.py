"""Sidik pesan log untuk penggabungan tab Log (batch 3.3), murni tanpa I/O.

`LogStore` menggabungkan pesan yang SAMA dalam 60 detik jadi satu baris dengan
hitungan. "Sama" dulu berarti identik huruf per huruf, jadi satu galat yang
menyebut id yang berubah tiap kali (uuid assignment, potongan hex, epoch, durasi
`1.52 s`) tidak pernah tergabung: tiap kejadian satu baris, dan banjirnya mendorong
keluar galat lain yang lebih tua dari layar.

Yang dinormalkan HANYA angka yang memang berganti tiap kejadian tanpa mengubah
arti galatnya. Yang sengaja TIDAK disentuh, karena membedakan dua masalah yang
berbeda:

- bilangan bulat pendek (kode HTTP `404`/`500`, errno `111`, port `8001` vs `8002`
  yang berarti line yang berbeda, nomor coil);
- alamat IP dan nomor versi (`192.168.3.39`, `v1.19.0`): bertitik lebih dari sekali;
- nomor plat dan kata apa pun: pola plat terlalu mirip kata biasa, dan menggabungkan
  dua truk yang berbeda lebih buruk daripada dua baris yang mirip.

Pesan yang DISIMPAN tetap pesan asli kejadian pertama; ini cuma untuk sidiknya.

Galat yang pesannya tetap tapi sebabnya berbeda (uvicorn menulis TIAP 500 sebagai
"Exception in ASGI application", `logger.exception("... gagal")` dengan pesan tetap)
dibedakan lewat `ringkas_galat`: baris terakhir traceback ikut sidik. Tanpa itu satu
500 yang berulang menelan setiap 500 lain selama jendela 60 detiknya terus bergeser,
dan traceback kedua tidak tersimpan di mana pun.
"""

from __future__ import annotations

import re

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
#: Potongan hex >= 8 yang memuat angka DAN huruf a-f (assignment[:8], sha, id
#: acak). Syarat keduanya mencegah kata biasa (`deadbeef`, `facade`) dan angka
#: murni ikut tertelan di sini; angka murni punya aturannya sendiri di bawah.
_HEX = re.compile(r"\b(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b", re.IGNORECASE)
#: Pecahan desimal lepas (durasi, epoch berkoma). Lookaround menolak bagian dari
#: IP/versi yang bertitik lebih dari sekali.
_DESIMAL = re.compile(r"(?<![\w.])\d+\.\d+(?![\w.])")
#: Bilangan bulat >= 6 digit (epoch, id baris besar). Lima digit ke bawah dibiarkan.
_BULAT_PANJANG = re.compile(r"(?<![\w.])\d{6,}(?![\w.])")


def normalkan_pesan(pesan: str) -> str:
    """Pesan dengan id yang berganti-ganti diganti penanda tetap, untuk sidik saja."""
    hasil = _UUID.sub("<uuid>", pesan)
    hasil = _HEX.sub("<id>", hasil)
    hasil = _DESIMAL.sub("<n>", hasil)
    return _BULAT_PANJANG.sub("<n>", hasil)

#: Nama kelas di awal baris galat Python: `KeyError`, `sqlite3.IntegrityError`.
_KELAS = re.compile(r"[A-Za-z_][\w.]*")


def _baris_terakhir(detail: str | None) -> str:
    for baris in reversed((detail or "").splitlines()):
        if baris.strip():
            return baris.strip()
    return ""


def ringkas_galat(detail: str | None) -> str:
    """Baris terakhir traceback (`KeyError: 'state'`), dinormalkan. Kosong tanpa traceback.

    Ikut sidik penggabungan: dua galat dengan pesan log yang sama tapi sebab berbeda
    jadi dua baris. Pesan tanpa traceback menghasilkan kosong, jadi sidiknya sama dengan
    versi sebelum batch 3.
    """
    return normalkan_pesan(_baris_terakhir(detail))


def jenis_galat(detail: str | None) -> str:
    """Nama kelas galat dari baris terakhir traceback (`KeyError`). Kosong kalau bukan.

    Untuk Discord: yang keluar pabrik cuma nama kelasnya, bukan isi pesan galatnya
    (bisa memuat plat, nilai SQL, jalur berkas). Rinciannya tetap di tab Log.
    """
    kepala = _baris_terakhir(detail).split(":", 1)[0].strip()
    return kepala if _KELAS.fullmatch(kepala) else ""


def dengan_jenis_galat(message: str, detail: str | None) -> str:
    """Pesan untuk digest Discord: pesan log plus nama kelas galatnya, kalau ada."""
    jenis = jenis_galat(detail)
    return f"{message.rstrip()} ({jenis})" if jenis else message
