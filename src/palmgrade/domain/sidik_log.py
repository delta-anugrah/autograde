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
dibedakan lewat `ringkas_galat`: nama kelas galat + frame pembedanya ikut sidik. Tanpa
itu satu 500 yang berulang menelan setiap 500 lain selama jendela 60 detiknya terus
bergeser, dan traceback kedua tidak tersimpan di mana pun. Teks galatnya sendiri tidak
ikut: plat, hitungan, jam, atau jalur di sana akan memecah satu galat jadi banyak baris.
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

#: Kepala galat Python: nama kelas (bertitik boleh) lalu ": pesan" atau akhir baris.
_KEPALA = re.compile(r"([A-Za-z_][\w.]*)(?:: |:?$)")
#: Satu frame traceback: `  File "jalur", line N, in fungsi`.
_FRAME = re.compile(r'^  File "([^"]+)", line (\d+)')
_PENANDA_TRACEBACK = "Traceback (most recent call last):"


#: Awal detail yang kepalanya dipotong `domain/log_line.potong_detail`.
_TANDA_POTONG = "...(dipotong)"


def _kepala_dan_frame(detail: str | None) -> tuple[str, str]:
    """(kelas galat, frame pembeda) dari sebuah traceback. Satu lintasan, tidak melempar.

    KELAS (satu-satunya yang pernah ditampilkan, misalnya di Discord): kepala blok traceback
    PERTAMA, yaitu baris tidak menjorok pertama sesudah frame-frame-nya, dan HANYA kalau
    blok itu dicapai tanpa sinkron ulang. Detail apa pun yang dipotong `potong_detail`
    (berawalan tanda potong, potongan di offset karakter) memberi kelas kosong, walau kepalanya
    masih ada: yang terbaca sesudah potongan bisa teks pesan galat. Teks lain tidak pernah dibaca sebagai kelas, jadi galat
    berantai dikenali dari akar penyebabnya (dicetak lebih dulu). Blok tanpa frame cuma sah
    kalau dibuka penanda `Traceback (most recent call last):`.

    FRAME (cuma masuk sidik, tidak pernah ditampilkan): frame `palmgrade/` TERAKHIR di seluruh
    detail (semua blok), kalau tidak ada, frame terakhir. Galat yang dilempar pustaka
    (pydantic, httpx) atau dibungkus `raise ... from e` dari dua rute berbeda tetap dua baris.
    Frame tiruan yang tersalin ke pesan galat paling buruk memecah baris, tidak pernah bocor.
    """
    baris = (detail or "").splitlines()
    if not baris:
        return "", ""
    disinkron = baris[0].strip() == _TANDA_POTONG
    berpenanda = baris[0].startswith(_PENANDA_TRACEBACK)
    kepala = ""
    kepala_lewat = False
    frame_blok_pertama = False
    frame_kita = frame_akhir = ""
    for b in baris[1 if (disinkron or berpenanda) else 0:]:
        cocok = _FRAME.match(b)
        if cocok:
            frame_akhir = f"{_jalur_pendek(cocok.group(1))}:{cocok.group(2)}"
            if frame_akhir.startswith("palmgrade/"):
                frame_kita = frame_akhir
            frame_blok_pertama = frame_blok_pertama or not kepala_lewat
            continue
        if kepala_lewat or not b.strip() or b[0].isspace():
            continue
        kepala_lewat = True
        if not disinkron and (frame_blok_pertama or berpenanda):
            kepala = b
    return _nama_kelas(kepala), frame_kita or frame_akhir


def _nama_kelas(kepala: str) -> str:
    """Nama kelas di awal kepala galat, diawali huruf besar di segmen terakhirnya
    (`sqlite3.IntegrityError`). Kosong kalau bukan."""
    cocok = _KEPALA.match(kepala)
    nama = cocok.group(1) if cocok else ""
    return nama if nama and nama.rsplit(".", 1)[-1][:1].isupper() else ""


def _jalur_pendek(jalur: str) -> str:
    """Jalur frame tanpa bagian yang berbeda antar mesin: sesudah `site-packages/` atau
    `src/`, kalau tidak ada, nama berkasnya saja."""
    for penanda in ("site-packages/", "src/"):
        if penanda in jalur:
            return jalur.rsplit(penanda, 1)[1]
    return jalur.replace("\\", "/").rsplit("/", 1)[-1]


def ringkas_galat(detail: str | None) -> str:
    """Pembeda galat untuk sidik: kelas (kepala blok pertama) + frame `palmgrade/` terakhir di
    seluruh detail, kalau tidak ada frame terakhir (`ValueError@palmgrade/x.py:12`).

    Ikut sidik penggabungan: dua galat dengan pesan log yang sama tapi sebab berbeda (kelas
    atau tempat lemparnya beda) jadi dua baris, galat yang sama berulang tetap satu. Teks
    galatnya sengaja TIDAK ikut: galat yang sama dengan plat, hitungan, jam, atau jalur
    berbeda di teksnya akan memecah jadi ratusan baris, dan `event_log` tidak punya batas
    baris. Tanpa traceback: kosong, jadi sidiknya sama dengan versi sebelum batch 3.
    """
    jenis, frame = _kepala_dan_frame(detail)
    return f"{jenis}@{frame}" if jenis or frame else ""


def jenis_galat(detail: str | None) -> str:
    """Nama kelas galat dari kepala blok traceback pertama (`KeyError`; galat berantai: akar
    penyebabnya). Kosong kalau tidak jelas atau kalau detailnya dipotong `potong_detail`.

    Untuk Discord: yang keluar pabrik cuma nama kelasnya, bukan isi pesan galatnya
    (bisa memuat plat, nilai SQL, jalur berkas). Rinciannya tetap di tab Log.
    """
    return _kepala_dan_frame(detail)[0]


def dengan_jenis_galat(message: str, detail: str | None) -> str:
    """Pesan untuk digest Discord: pesan log plus nama kelas galatnya, kalau ada."""
    jenis = jenis_galat(detail)
    return f"{message.rstrip()} ({jenis})" if jenis else message
