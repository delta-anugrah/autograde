"""`LogLineStore` (batch 3.2): log line di disk line, kursor `seq`, batas baris, generasi."""
from __future__ import annotations

import sqlite3

from palmgrade.domain.log_line import EntriLog
from palmgrade.repositories.log_line_repository import LogLineStore


def _semua(store: LogLineStore, setelah: int = 0, generasi: str | None = None) -> dict:
    return store.ambil(setelah=setelah, generasi=generasi or store.generasi, batas=500)


def _tb(kelas_pesan: str, baris: int = 12) -> str:
    """Traceback berbentuk asli: penanda, frame, baris kode, lalu kepala galat."""
    return ("Traceback (most recent call last):\n"
            f'  File "/app/src/palmgrade/workers/x.py", line {baris}, in f\n'
            "    jalan()\n"
            f"{kelas_pesan}\n")


def test_kejadian_tersimpan_dan_terbaca_urut_seq(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "kamera putus", "Traceback\nX", now=100.0)
    store.write("WARNING", "b", "plc lambat", None, now=101.0)

    hasil = _semua(store)

    assert [(e["level"], e["message"], e["seq"]) for e in hasil["entri"]] == [
        ("ERROR", "kamera putus", 1), ("WARNING", "plc lambat", 2),
    ]
    assert hasil["entri"][0]["detail"] == "Traceback\nX"
    assert (hasil["seq_akhir"], hasil["lagi"], hasil["dibuang"]) == (2, False, 0)


def test_pesan_sama_dalam_60_detik_digabung_dan_seq_naik(tmp_path):
    """Baris yang hitungannya naik dapat seq baru, supaya konsol membacanya ulang."""
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "grab gagal", _tb("OSError: truk B1234XY"), now=100.0)
    store.write("WARNING", "b", "lain", None, now=101.0)
    store.write("ERROR", "a", "grab gagal", _tb("OSError: truk D5678AB"), now=130.0)

    hasil = _semua(store, setelah=2)

    (e,) = hasil["entri"]
    assert (e["message"], e["count"], e["seq"], e["first_at"], e["last_at"]) == (
        "grab gagal", 2, 3, 100.0, 130.0,
    )
    # Galat yang sama (kelas + frame terakhir sama, teks galat beda): traceback pertama.
    assert e["detail"] == _tb("OSError: truk B1234XY")


def test_pesan_sama_sesudah_jendela_jadi_baris_baru(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "grab gagal", None, now=100.0)
    store.write("ERROR", "a", "grab gagal", None, now=200.0)

    assert [e["count"] for e in _semua(store)["entri"]] == [1, 1]


def test_halaman_membawa_lagi_dan_seq_akhir(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    for i in range(5):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)

    satu = store.ambil(setelah=0, generasi=store.generasi, batas=2)
    dua = store.ambil(setelah=satu["seq_akhir"], generasi=store.generasi, batas=2)
    tiga = store.ambil(setelah=dua["seq_akhir"], generasi=store.generasi, batas=2)

    assert [e["message"] for e in satu["entri"]] == ["pesan 0", "pesan 1"]
    assert (satu["lagi"], dua["lagi"], tiga["lagi"]) == (True, True, False)
    assert [e["message"] for e in tiga["entri"]] == ["pesan 4"]


def test_kursor_di_ujung_memulangkan_kosong_dan_seq_akhir_tetap(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "x", None, now=1.0)

    hasil = store.ambil(setelah=1, generasi=store.generasi, batas=100)

    assert (hasil["entri"], hasil["seq_akhir"], hasil["lagi"]) == ([], 1, False)


def test_generasi_lain_dibaca_dari_awal(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "x", None, now=1.0)
    store.write("ERROR", "a", "y", None, now=2.0)

    hasil = store.ambil(setelah=2, generasi="generasi-berkas-lama", batas=100)

    assert [e["message"] for e in hasil["entri"]] == ["x", "y"]


def test_generasi_tetap_sesudah_dibuka_ulang_dan_baru_sesudah_berkas_dihapus(tmp_path):
    """Restart line = berkas yang sama = kursor konsol tetap berlaku.
    Reset data (berkas hilang) = generasi baru."""
    jalur = tmp_path / "log_line.db"
    pertama = LogLineStore(jalur).generasi
    assert LogLineStore(jalur).generasi == pertama

    for berkas in tmp_path.iterdir():
        berkas.unlink()

    assert LogLineStore(jalur).generasi != pertama


def test_kejadian_selamat_sesudah_dibuka_ulang(tmp_path):
    """Inti 3.2: yang ditulis sebelum restart masih ada sesudahnya."""
    jalur = tmp_path / "log_line.db"
    LogLineStore(jalur).write("ERROR", "a", "sebelum restart", "tb", now=1.0)

    hasil = _semua(LogLineStore(jalur))

    assert [e["message"] for e in hasil["entri"]] == ["sebelum restart"]


def test_seq_tidak_mundur_sesudah_dibuka_ulang(tmp_path):
    jalur = tmp_path / "log_line.db"
    LogLineStore(jalur).write("ERROR", "a", "x", None, now=1.0)
    store = LogLineStore(jalur)
    store.write("ERROR", "a", "y", None, now=500.0)

    assert [e["seq"] for e in _semua(store)["entri"]] == [1, 2]


def test_batas_baris_membuang_yang_paling_lama_tidak_berubah_dan_menghitungnya(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db", batas_baris=3)
    for i in range(5):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)

    hasil = _semua(store)

    assert [e["message"] for e in hasil["entri"]] == ["pesan 2", "pesan 3", "pesan 4"]
    assert hasil["dibuang"] == 2


def test_baris_yang_sudah_ditarik_tidak_dihitung_dibuang_saat_batas(tmp_path):
    """`dibuang` = baris yang hilang SEBELUM konsol sempat menariknya. Yang sudah
    disajikan `ambil` lalu tergeser batas bukan kehilangan: tab Log sudah punya."""
    store = LogLineStore(tmp_path / "log_line.db", batas_baris=3)
    for i in range(3):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)
    seq_akhir = _semua(store)["seq_akhir"]

    for i in range(3, 6):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)

    assert _semua(store, setelah=seq_akhir)["dibuang"] == 0


def test_baris_belum_ditarik_tetap_dihitung_walau_sebagian_sudah_ditarik(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db", batas_baris=3)
    store.write("ERROR", "a", "pesan 0", None, now=100.0)
    store.ambil(setelah=0, generasi=store.generasi, batas=500)  # konsol menarik pesan 0
    for i in range(1, 7):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)

    # tergeser: pesan 0 (sudah ditarik) + pesan 1..3 (belum pernah disajikan)
    assert _semua(store)["dibuang"] == 3


def test_tanda_terbaca_selamat_sesudah_dibuka_ulang(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db", batas_baris=2)
    for i in range(2):
        store.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)
    _semua(store)

    dibuka_ulang = LogLineStore(tmp_path / "log_line.db", batas_baris=2)
    for i in range(2, 4):
        dibuka_ulang.write("ERROR", "a", f"pesan {i}", None, now=100.0 + i * 100)

    assert _semua(dibuka_ulang)["dibuang"] == 0


def test_disk_tidak_bisa_ditulis_ambil_tetap_menyajikan_halaman(tmp_path):
    """Disk `state/` yang di-remount read-only (atau penuh): justru saat itu log line yang
    menjelaskannya harus tetap sampai ke tab Log. Penanda `terbaca` cuma usaha terbaik."""
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "disk mulai rusak", None, now=100.0)
    store.write("ERROR", "a", "tulis gagal", None, now=200.0)
    store._db.execute("PRAGMA query_only=ON")  # meniru disk yang tidak bisa ditulis

    hasil = _semua(store)

    assert [e["message"] for e in hasil["entri"]] == ["disk mulai rusak", "tulis gagal"]
    assert hasil["seq_akhir"] == 2

    store._db.execute("PRAGMA query_only=OFF")  # disk pulih: kunci dan transaksi tidak rusak
    store.write("ERROR", "a", "sesudah pulih", None, now=300.0)
    assert [e["message"] for e in _semua(store, setelah=2)["entri"]] == ["sesudah pulih"]


def test_baris_yang_baru_digabung_tidak_ikut_dibuang(tmp_path):
    """Yang dibuang = seq terendah, yaitu yang paling lama tidak berubah, bukan yang tertua dibuat."""
    store = LogLineStore(tmp_path / "log_line.db", batas_baris=2)
    store.write("ERROR", "a", "berulang", None, now=100.0)
    store.write("ERROR", "a", "sekali", None, now=110.0)
    store.write("ERROR", "a", "berulang", None, now=120.0)  # seq naik, digabung
    store.write("ERROR", "a", "baru", None, now=130.0)

    assert sorted(e["message"] for e in _semua(store)["entri"]) == ["baru", "berulang"]


def test_tulis_banyak_satu_transaksi_dan_dibuang_antrean_dihitung(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.tulis_banyak(
        [EntriLog("ERROR", "a", "satu", None, 1.0), EntriLog("WARNING", "b", "dua", None, 2.0)],
        dibuang_antrean=7,
    )

    hasil = _semua(store)

    assert [e["message"] for e in hasil["entri"]] == ["satu", "dua"]
    assert hasil["dibuang"] == 7


def test_detail_dipotong_sebelum_menyentuh_disk(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    store.write("ERROR", "a", "x", "t" * 50_000 + "AKHIR", now=1.0)

    (e,) = _semua(store)["entri"]

    assert len(e["detail"]) == 8000
    assert e["detail"].endswith("AKHIR")


def test_berkas_memakai_wal(tmp_path):
    jalur = tmp_path / "log_line.db"
    LogLineStore(jalur)
    assert sqlite3.connect(str(jalur)).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_pesan_sama_beda_uuid_tergabung_kode_http_berbeda_tidak(tmp_path):
    """Sidik dihitung dari pesan yang dinormalkan (uuid diganti penanda), bukan mentah:
    dua galat yang cuma beda uuid adalah satu masalah; HTTP 404 vs 500 dua masalah beda."""
    store = LogLineStore(tmp_path / "log_line.db")
    store.write(
        "ERROR", "a",
        "Penugasan 3f2a9c1e-5b7d-4e1a-9c3f-2b6d4c8e7b01 gagal diteruskan", None, now=100.0,
    )
    store.write(
        "ERROR", "a",
        "Penugasan a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02 gagal diteruskan", None, now=110.0,
    )
    store.write("ERROR", "a", "AutoERP menjawab HTTP 404", None, now=120.0)
    store.write("ERROR", "a", "AutoERP menjawab HTTP 500", None, now=121.0)

    hasil = _semua(store)

    by_message = {e["message"]: e["count"] for e in hasil["entri"]}
    assert by_message["Penugasan 3f2a9c1e-5b7d-4e1a-9c3f-2b6d4c8e7b01 gagal diteruskan"] == 2
    assert by_message["AutoERP menjawab HTTP 404"] == 1
    assert by_message["AutoERP menjawab HTTP 500"] == 1


def test_500_berbeda_dalam_satu_jendela_jadi_dua_baris(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    asgi = "Exception in ASGI application\n"
    store.write("ERROR", "uvicorn.error", asgi, _tb("KeyError: a"), now=100.0)
    store.write("ERROR", "uvicorn.error", asgi, _tb("OSError: disk", baris=30), now=130.0)
    store.write("ERROR", "uvicorn.error", asgi, _tb("KeyError: b"), now=140.0)
    entri = _semua(store)["entri"]
    assert sorted((e["count"], e["detail"].splitlines()[-1]) for e in entri) == [
        (1, "OSError: disk"), (2, "KeyError: a"),
    ]
