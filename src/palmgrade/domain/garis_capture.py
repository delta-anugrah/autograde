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


#: Sejauh mana TP boleh berada dari janjangnya, sebagai kelipatan ukuran janjang
#: (setengah diagonal kotaknya). Ambang RELATIF, bukan piksel tetap: janjang di
#: dekat kamera jauh lebih besar daripada yang di ujung frame, dan satu angka
#: piksel akan benar cuma di satu jarak kamera. 1,5 = kira-kira satu badan
#: janjang di sekitarnya — cukup untuk tangkai yang menjulur keluar kotak
#: (operator menegaskan TP bisa terpisah), belum cukup untuk menjangkau janjang
#: tetangga di conveyor.
_JANGKAUAN_TP = 1.5


def _pusat(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def tp_untuk_janjang(
    *,
    janjang: tuple[int, int, int, int],
    kandidat: list[dict],
    janjang_lain: list[tuple[int, int, int, int]] | None = None,
) -> dict | None:
    """TP milik `janjang` dari daftar `kandidat`, atau `None` kalau tidak ada.

    Menggantikan aturan lama "TP terakhir yang terlihat", yang tidak pernah
    melihat posisi dan karena itu bisa menempelkan TP milik janjang A ke janjang
    B yang kebetulan menyentuh garis lebih dulu. Dua-duanya salah bayar, dan
    dua-duanya tidak meninggalkan jejak apa pun.

    Jaraknya antar PUSAT kotak, bukan irisan: TP bisa terpisah dari kotak
    janjangnya (jawaban operator 2026-09-18), jadi menuntut irisan akan
    membuang TP yang sah. Ambangnya ikut ukuran janjang — lihat `_JANGKAUAN_TP`.

    Yang terdekat yang menang, bukan yang paling yakin: confidence mengukur
    seberapa yakin model itu TP, bukan seberapa mungkin TP itu milik janjang ini.

    `janjang_lain` = janjang lain di frame yang sama. Ambang jarak saja tidak
    cukup begitu dua janjang berdempetan di conveyor: keduanya bisa sama-sama
    berada dalam jangkauan TP yang sama, dan yang menang tinggal siapa yang
    kebetulan diproses lebih dulu — padahal urutan kotak dalam satu frame tidak
    dijamin. Sebuah TP diberikan hanya kalau janjang INI yang paling dekat
    dengannya, jadi hasilnya tidak lagi bergantung urutan.
    """
    if not kandidat:
        return None

    jx, jy = _pusat(janjang)
    x1, y1, x2, y2 = janjang
    # Setengah diagonal: satu angka yang mewakili "ukuran" janjang tanpa
    # memihak lebar atau tinggi, jadi janjang tegak dan janjang rebah
    # menjangkau sama jauhnya.
    ukuran = (((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5) / 2
    batas = ukuran * _JANGKAUAN_TP

    pusat_lain = [_pusat(b) for b in (janjang_lain or [])]

    terdekat, jarak_terdekat = None, None
    for tp in kandidat:
        tx, ty = _pusat(tp["bbox"])
        jarak = ((tx - jx) ** 2 + (ty - jy) ** 2) ** 0.5
        if jarak > batas:
            continue
        # Janjang lain yang lebih dekat ke TP ini = TP itu miliknya, bukan milik
        # janjang ini. Dibandingkan apa adanya, tanpa ambang: yang ditanyakan
        # "siapa pemiliknya", dan pemiliknya cuma satu.
        if any(
            ((tx - ox) ** 2 + (ty - oy) ** 2) ** 0.5 < jarak for ox, oy in pusat_lain
        ):
            continue
        if jarak_terdekat is None or jarak < jarak_terdekat:
            terdekat, jarak_terdekat = tp, jarak
    return terdekat


def kandidat_tp_sah(*, track_id: int, sudah_diproses: bool) -> bool:
    """Boleh tidaknya satu kotak TP dipakai sebagai kandidat pasangan.

    Dua gerbang, keduanya diwarisi dari kode sebelum pasangan-lewat-jarak dan
    keduanya punya alasan sendiri:

    * `track_id == -1` berarti ByteTrack belum menetapkan identitas untuk kotak
      ini — deteksi yang dia sendiri belum yakini. Menempelkannya ke janjang
      berarti menambah tangkai panjang yang mungkin tidak ada, dan tangkai
      panjang itu kriteria yang dibukukan AutoERP.
    * Track yang sudah diproses berarti tangkainya sudah menempel ke satu
      janjang. Satu tangkai milik satu janjang; tanpa gerbang ini dia ikut ke
      setiap janjang yang lewat selama dia masih terlihat di frame.
    """
    return track_id != -1 and not sudah_diproses
