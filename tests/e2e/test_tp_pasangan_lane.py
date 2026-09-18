"""End-to-end: satu janjang melintasi garis, dengan TP di depan dan di belakang.

Unit test membuktikan aturan jaraknya benar. Yang belum terbukti di sana adalah
perilakunya sepanjang beberapa frame berurutan, dan itu justru pertanyaan yang
diajukan operator: "kadang TP duluan, kadang TP di belakang".

Keputusan yang dikunci berkas ini (operator, 2026-09-18):

* janjang difoto **apa adanya** begitu menyentuh garis, ada TP atau tidak;
* TP yang sudah terlihat dipasangkan lewat **jarak**, bukan urutan waktu — TP
  milik janjang lain tidak boleh ikut;
* TP yang baru muncul **sesudah** janjangnya difoto memang tidak ikut, tapi
  **dihitung** (`tp_telat`), supaya keputusan menambah jendela tunggu nanti
  diambil dari angka nyata.

Murni logika: `tp_untuk_janjang` tidak menyentuh cv2 maupun torch, jadi seluruh
perjalanan bisa disimulasikan sebagai daftar kotak per frame.
"""
from __future__ import annotations

from palmgrade.domain.garis_capture import menyentuh_kotak, tp_untuk_janjang

GARIS = 800
# Janjang 300x400 bergerak kanan → kiri, 120 px per frame.
LEBAR, TINGGI = 300, 400


def _janjang(x_kiri: int) -> tuple[int, int, int, int]:
    return (x_kiri, 300, x_kiri + LEBAR, 300 + TINGGI)


def _jalankan(frames: list[tuple[int, list[dict]]]) -> list[dict | None]:
    """Putar beberapa frame; kembalikan TP yang terpasang pada frame pemicu.

    Meniru `FrameProcessingWorker`: satu janjang, single-trigger lewat
    `sudah_difoto`, TP dikumpulkan lebih dulu lalu dipasangkan lewat jarak.
    """
    hasil: list[dict | None] = []
    sudah_difoto = False
    for x_kiri, tp_di_frame in frames:
        kotak = _janjang(x_kiri)
        if sudah_difoto:
            continue
        if not menyentuh_kotak(
            x1=kotak[0], y1=kotak[1], x2=kotak[2], y2=kotak[3],
            garis=GARIS, sumbu="tegak",
        ):
            continue
        hasil.append(tp_untuk_janjang(janjang=kotak, kandidat=tp_di_frame))
        sudah_difoto = True
    return hasil


def _tp(x: int, y: int = 640) -> dict:
    return {"tp_status": "PASS", "tp_confidence": 0.8, "bbox": (x, y, x + 90, y + 90)}


def test_tp_yang_datang_duluan_ikut_ke_janjangnya():
    """Urutan TP → Janjang: tangkai sudah di frame saat janjang menyentuh garis."""
    (terpasang,) = _jalankan([
        (1100, [_tp(1150)]),   # belum menyentuh garis
        (980, [_tp(1030)]),    # belum
        (860, [_tp(910)]),     # belum
        (740, [_tp(790)]),     # MENYENTUH — TP menempel di janjang
    ])

    assert terpasang is not None, "TP yang jelas milik janjang ini tidak ikut"
    assert terpasang["tp_status"] == "PASS"


def test_janjang_tanpa_tp_tetap_difoto_saat_menyentuh_garis():
    """Keputusan operator: capture apa adanya, tidak menunggu TP.

    Kalau janjang tanpa TP ikut ditahan, conveyor yang sebagian besar isinya
    janjang polos akan tertunda tanpa alasan.
    """
    (terpasang,) = _jalankan([(1100, []), (980, []), (740, [])])

    assert terpasang is None, "janjang tanpa TP harus tetap difoto, tanpa TP"


def test_tp_milik_janjang_lain_tidak_ikut():
    """Inti perbaikan: aturan lama memberikan TP terakhir ke janjang berikutnya.

    TP di seberang frame jelas bukan milik janjang ini; ikut-nya akan menambah
    tangkai panjang ke janjang yang tidak punya, dan itu menggeser potongan
    yang dibayar ke supplier.
    """
    (terpasang,) = _jalankan([(740, [_tp(2200, 1700)])])

    assert terpasang is None


def test_tp_yang_datang_belakangan_tidak_ikut_tapi_terhitung():
    """Urutan Janjang → TP. Sesudah janjang difoto, TP-nya baru muncul.

    Ini harga yang sadar dibayar dari "capture apa adanya": tangkainya tidak
    ikut. Yang tidak boleh terjadi adalah tangkai itu menempel ke janjang
    BERIKUTNYA — itu dulu yang terjadi, dan itu salah bayar yang senyap.
    """
    frames = [
        (1100, []),
        (980, []),
        (740, []),            # MENYENTUH, tanpa TP
        (620, [_tp(670)]),    # TP baru muncul — janjangnya sudah difoto
    ]
    hasil = _jalankan(frames)

    assert hasil == [None], "TP yang telat tidak boleh ikut ke janjang ini"

    # Dan TP itu memang berada di dekat janjang yang sudah difoto — itulah yang
    # dihitung `tp_telat` di worker, bukan sekadar "ada TP nyasar".
    assert tp_untuk_janjang(janjang=_janjang(620), kandidat=[_tp(670)]) is not None


def test_dua_tp_di_frame_yang_sama_diambil_yang_terdekat():
    """Conveyor padat: dua tangkai terlihat sekaligus."""
    dekat, jauh = _tp(790), _tp(1180, 900)
    (terpasang,) = _jalankan([(740, [jauh, dekat])])

    assert terpasang is dekat


def test_satu_janjang_hanya_difoto_sekali_walau_terus_menyentuh_garis():
    """Single-trigger: janjang lebar menyentuh garis selama beberapa frame."""
    hasil = _jalankan([
        (740, [_tp(790)]),
        (620, [_tp(670)]),
        (500, [_tp(550)]),
    ])

    assert len(hasil) == 1, "janjang terfoto lebih dari sekali"


def test_satu_tangkai_tidak_ikut_ke_dua_janjang():
    """Satu TP milik SATU janjang.

    Dua janjang berurutan menyentuh garis pada frame yang sama, dan tangkainya
    berada di antara keduanya. Tanpa penandaan, tangkai itu ikut ke dua-duanya —
    dan tangkai panjang adalah kriteria yang dibukukan AutoERP, jadi satu
    tangkai terhitung dua kali menggeser potongan yang dibayar ke supplier.
    """
    tp = dict(_tp(760), track_id=99)
    kandidat = [tp]

    # Janjang pertama mengambilnya, lalu membuangnya dari kandidat — persis
    # seperti `FrameProcessingWorker` melakukannya.
    pertama = tp_untuk_janjang(janjang=_janjang(740), kandidat=kandidat)
    assert pertama is tp
    kandidat = [t for t in kandidat if t is not pertama]

    kedua = tp_untuk_janjang(janjang=_janjang(700), kandidat=kandidat)
    assert kedua is None, "tangkai yang sama ikut ke janjang kedua"
