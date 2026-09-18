"""Garis capture: satu garis vertikal, janjang difoto saat menyentuhnya.

Menggantikan aturan lama "titik tengah kotak janjang masuk kotak ROI" untuk
menentukan KAPAN foto diambil (permintaan operator 2026-09-18). Bedanya bukan
kosmetik, dan itu yang menjelaskan keluhan "capture terlalu cepat":

| | Lama | Sekarang |
|---|---|---|
| bentuk zona | kotak ROI 4 sisi | satu garis vertikal |
| pemicu | titik TENGAH masuk kotak | tepi janjang menyentuh garis |

Buah bergerak kanan → kiri di conveyor, jadi tepi kiri kotak janjang adalah
ujung depannya. Titik tengah berarti foto diambil saat setengah janjang sudah
lewat — setengah panjang janjang lebih awal dari yang dilihat operator.

ROI **tidak dihapus**: dia tetap menyaring janjang yang memang di luar wilayah
conveyor (`_is_in_roi`), dan `TP` tetap dikecualikan darinya. Yang berpindah cuma
penentu waktunya.

Modul domain: nol I/O, nol cv2 — aturan yang menentukan uang harus bisa diuji
tanpa merakit satu line pun.
"""
from __future__ import annotations


def menyentuh_garis(*, x1: int, x2: int, garis_x: int) -> bool:
    """True kalau kotak janjang (`x1`..`x2`) bersinggungan dengan garis.

    `garis_x == 0` berarti **tidak ada garis**, dan semua janjang lolos — itu
    perilaku sebelum fitur ini ada, dan satu-satunya cara PKS yang belum
    menyetel tidak kehilangan janjang.

    Sengaja BUKAN "tepi kiri persis menyentuh". Garis dievaluasi sekali per
    frame, dan pada 8-20 fps janjang bisa melompati garis di antara dua frame:
    menuntut sentuhan persis akan membuat janjang cepat tidak pernah difoto,
    hilang tanpa satu pun pesan. Yang diuji perpotongan — begitu kotaknya
    menyeberangi garis, frame berikutnya sudah cukup.

    Arah gerak tidak perlu diketahui kode ini: perpotongan berlaku dari sisi
    mana pun, jadi line yang conveyor-nya terbalik tidak butuh setelan lain.
    """
    if garis_x <= 0:
        return True
    return x1 <= garis_x <= x2


#: Sumbu garis. `tegak` = garis vertikal, janjang menyeberangnya kiri↔kanan
#: (conveyor mendatar). `mendatar` = garis horizontal, janjang menyeberangnya
#: atas↔bawah (conveyor menurun). Arah gerak DI DALAM satu sumbu tidak perlu
#: disetel: perpotongan berlaku dari sisi mana pun.
TEGAK = "tegak"
MENDATAR = "mendatar"
SUMBU = (TEGAK, MENDATAR)


def menyentuh_kotak(
    *, x1: int, y1: int, x2: int, y2: int, garis: int, sumbu: str = TEGAK
) -> bool:
    """True kalau kotak janjang bersinggungan dengan garis pada `sumbu`.

    Sumbu yang tidak dikenal diperlakukan sebagai `tegak`, **tidak** melempar:
    nilainya bisa datang dari konsol versi lain, dan satu string asing tidak
    boleh menghentikan grading satu line. Yang menolak nilai aneh adalah jalur
    SIMPAN (`domain/setelan_grading`), di gerbang, sebelum sampai ke line.
    """
    if sumbu == MENDATAR:
        return menyentuh_garis(x1=y1, x2=y2, garis_x=garis)
    return menyentuh_garis(x1=x1, x2=x2, garis_x=garis)


def skala_garis(
    garis: int,
    *,
    sumbu: str,
    stream_width: int,
    stream_height: int,
    frame_width: int,
    frame_height: int,
) -> int:
    """`skala_garis_ke_frame` yang tahu sumbu.

    Garis mendatar diskalakan dengan TINGGI, bukan lebar. Memakai lebar untuk
    keduanya adalah versi lain dari bug ROI (`bdcb300`): frame 2448x2048 tidak
    persegi, jadi garis mendatar akan mendarat ~19% meleset dari tempat yang
    dilihat operator — dan tidak ada yang memberi tahu.
    """
    if sumbu == MENDATAR:
        return skala_garis_ke_frame(
            garis, stream_width=stream_height, frame_width=frame_height
        )
    return skala_garis_ke_frame(garis, stream_width=stream_width, frame_width=frame_width)


def skala_garis_ke_frame(garis_x: int, *, stream_width: int, frame_width: int) -> int:
    """Garis dari ruang STREAM (yang disetel operator) ke ruang frame deteksi.

    Operator menyetel angkanya dari gambar yang dia lihat di browser
    (`STREAM_WIDTH`, bawaan 1280), sementara deteksi berjalan pada frame mentah
    kamera — `frame_queue` tidak pernah di-resize, jadi di Hikrobot itu 2448 px.

    Melewatkan penskalaan ini adalah bug yang sudah pernah terjadi pada ROI
    (diperbaiki commit `bdcb300`): satu angka dipakai di dua ruang koordinat,
    kotaknya terlihat benar di layar sementara yang benar-benar menyaring cuma
    sebagian kecil frame, dan janjang di luar itu dilewati tanpa pesan apa pun.

    `0` tetap `0` (garis mati), dan `stream_width` kosong dianggap tidak perlu
    diskalakan — salah setel tidak boleh berubah jadi pembagian nol yang
    mematikan line.
    """
    if garis_x <= 0 or stream_width <= 0 or frame_width <= 0:
        return garis_x
    return round(garis_x * frame_width / stream_width)
