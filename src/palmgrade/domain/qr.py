"""Isi QR truk: **nomor plat, tidak lebih** (keputusan operator 2026-09-15).

Kenapa cuma plat, dan bukan seluruh data truk:

- supplier, nama sopir, dan kelas kendaraan berubah di AutoERP **sesudah** QR
  dicetak. QR yang membawanya jadi bohong, dan tidak ada yang tahu — backoffice
  sudah memperbarui, yang menempel di truk masih data lama.
- itu jadi dua sumber kebenaran untuk hal yang sama, tanpa aturan siapa yang menang.
- nama sopir itu data pribadi yang menempel di kaca truk, difoto siapa saja. Plat
  memang publik; nama orang tidak perlu ikut menyebar untuk hal yang bisa dibaca
  dari ERP.

Kenapa bukan id truk AutoERP: truk **pinjaman** belum terdaftar, jadi belum punya
id, jadi tidak bisa di-scan — padahal truk pinjaman justru alasan fitur ini ada
(`docs/PERTANYAAN-TERBUKA.md` S4).

Plat masuk lewat tiga tempat dengan tiga gaya tulisan (operator, program timbangan,
ERP), jadi yang disimpan di QR sudah bentuk ternormalisasi: satu truk = satu QR,
walau platnya pernah ditulis `be-4412-ofl` di satu tempat dan `BE 4412 OFL` di
tempat lain.

**Yang mencetak kartunya AutoERP (2026-09-17), bukan lagi konsol ini.** Backoffice
yang mendaftarkan truk sudah ada di ERP Desk, jadi tombol cetaknya di sana. Aturan
normalisasi di atas tetap satu-satunya yang berlaku: `palm_mill/utils.py`
memakai regex yang sama persis, dan `plate_normalized` di DocType `Truck` itulah
yang dicetak ke dalam QR. Endpoint `qr.png` di konsol **tidak dihapus** - dia
cadangan waktu internet pabrik putus dan ada truk baru datang.
"""

from __future__ import annotations

import re

from .operator_error import BUKAN_PLAT, InvalidInput
from .plate import normalisasi_plat

# Bentuk plat, dicek SESUDAH dinormalisasi (pemisahnya sudah hilang): huruf
# wilayah opsional, angka, huruf akhir opsional.
#
# **Sengaja lebih longgar dari plat sipil biasa.** Sejak kartu QR dicetak dari
# AutoERP, backoffice boleh mendaftarkan plat yang bentuknya menyimpang - plat
# dinas, plat lama, kendaraan luar daerah - setelah mengiyakan peringatan di
# layar. Kalau gerbang lebih ketat dari yang mencetak, kartunya tercetak, tertempel
# di kaca, lalu ditolak scanner; sopirnya yang menanggung, dan tidak ada yang tahu
# sampai truknya sampai.
#
# Yang tetap harus ditolak: apa pun yang jelas bukan plat. Dua batas menjaga itu:
#
# - huruf wilayah maksimal **dua**, karena `TRK0042` (id ERP) berbentuk mirip plat
#   dan tiga huruf awal akan meloloskannya;
# - **wajib ada huruf**, karena angka telanjang seperti `1234` itu bisa apa saja -
#   nomor tiket, berat, harga - dan scanner gerbang membaca apa pun yang disodorkan.
#
# Satu salah scan yang lolos menambah truk hantu ke master data, dan truk itu naik
# ke AutoERP lewat interface B.
_BENTUK_PLAT = re.compile(r"^(?:[A-Z]{1,2}\d{1,5}[A-Z]{0,4}|\d{1,5}[A-Z]{1,4})$")


def isi_qr_untuk(plat: str) -> str:
    """Yang dicetak ke dalam QR untuk satu truk.

    Bentuk ternormalisasi, bukan plat apa adanya: QR dicetak sekali dan dipakai
    bertahun-tahun, jadi dua gaya tulisan tidak boleh menghasilkan dua QR.
    """
    return normalisasi_plat(plat)


def baca_qr(teks: str) -> str:
    """Hasil bacaan scanner → plat ternormalisasi. Menolak yang bukan plat.

    Longgar soal tulisan, ketat soal bentuk. Scanner membaca dari layar HP yang
    retak atau kertas fotokopi, dan QR lama mungkin dicetak sebelum aturan
    normalisasi ada — jadi apa pun gaya tulisannya diterima.

    Tapi **apa pun** bisa masuk ke scanner: struk parkir, QR promo, id ERP. Kalau
    yang begitu lolos, satu salah scan menambah truk hantu ke master data, dan truk
    itu naik ke AutoERP lewat interface B.
    """
    plat = normalisasi_plat(teks)  # raise sendiri kalau kosong
    if not _BENTUK_PLAT.match(plat):
        raise InvalidInput(
            BUKAN_PLAT,
            f"hasil scan {teks!r} tidak berbentuk nomor polisi",
            field="plate_number",
            value=teks,
        )
    return plat
