"""`LaporDiscordStore` (batch 3.5): galat menunggu → kiriman.

Tanpa hilang sampai konsol menyimpannya (galat_menunggu → kiriman satu transaksi,
M1/I1). Sesudah itu paling sedikit sekali (at-least-once) sampai Discord: kiriman yang
sudah dijawab 2xx tapi belum sempat `tandai_terkirim` (proses mati/koneksi putus di
antara keduanya) akan dikirim lagi saat dicoba ulang, M2. Webhook Discord tidak punya
kunci idempotensi untuk mencegah ini di sisi penerima.
"""
from __future__ import annotations

import logging
import sqlite3
import threading

import pytest

from palmgrade.domain.digest_galat import BATAS_KELOMPOK_MENUNGGU, PESAN_LAIN
from palmgrade.repositories import lapor_discord_repository
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.repositories.log_serap_line import TambahGalat


class _Jam:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _tb(kelas_pesan: str, baris: int = 12) -> str:
    """Traceback berbentuk asli: penanda, frame, baris kode, lalu kepala galat."""
    return ("Traceback (most recent call last):\n"
            f'  File "/app/src/palmgrade/workers/x.py", line {baris}, in f\n'
            "    jalan()\n"
            f"{kelas_pesan}\n")


def _susun_mentah(kelompok) -> list[str]:
    return [f"{k.jumlah}x {k.line_code or 'konsol'} {k.message}" for k in sorted(kelompok, key=lambda k: k.message)]


def test_galat_konsol_dan_line_sekelompok_per_jenis_dengan_hitungan(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    # Dua id 8+ hex yang berbeda tapi teks lain identik: `normalkan_pesan` (Task 5,
    # `domain/sidik_log.py`) menganggap keduanya id yang berganti-ganti, jadi sidik-nya
    # SAMA dan keduanya digabung satu kelompok dengan hitungan naik. Pesan yang tersimpan
    # tetap milik kejadian PERTAMA (`_antre_satu`: ON CONFLICT tidak menimpa `message`).
    store.write("ERROR", "palmgrade.x", "truk gagal assign deadbeef01", "traceback tidak ikut", now=10.0)
    store.write("ERROR", "palmgrade.x", "truk gagal assign facade0102", None, now=20.0)
    store.antre_line([TambahGalat("ERROR", "palmgrade.y", "line-2", "grab gagal", 5.0, 30.0, 7)])

    store.susun(_susun_mentah, now=100.0)

    isi = []
    while (k := store.kiriman_berikut()) is not None:
        isi.append(k.isi)
        store.tandai_terkirim(k.id, now=101.0)
    assert isi == ["7x line-2 grab gagal", "2x konsol truk gagal assign deadbeef01"]
    store.close()


def test_galat_beda_angka_pendek_tetap_dua_kelompok(tmp_path):
    """Pin R2: angka pendek yang berarti (dua truk berbeda) TIDAK dilebur, beda dengan
    id acak 8+ hex di atas. `normalkan_pesan` sengaja tidak menyentuh bilangan pendek."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "palmgrade.x", "truk 11 gagal", None, now=10.0)
    store.write("ERROR", "palmgrade.x", "truk 12 gagal", None, now=20.0)

    assert store.susun(_susun_mentah, now=100.0) == 2
    r = store.ringkasan()
    assert r["kiriman"] == 2
    store.close()


def test_susun_memindah_semuanya_dalam_satu_transaksi(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    assert store.susun(_susun_mentah, now=5.0) == 1
    assert store.tertua_masuk_at() is None
    assert store.ada_kiriman()
    assert store.ringkasan_terakhir_at() == 5.0
    assert store.susun(_susun_mentah, now=6.0) == 0
    store.close()


def test_susun_yang_gagal_meninggalkan_galat_menunggu(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    def _meledak(kelompok):
        raise RuntimeError("susun rusak")

    with pytest.raises(RuntimeError):
        store.susun(_meledak, now=5.0)

    assert store.tertua_masuk_at() == 1000.0
    assert not store.ada_kiriman()
    assert store.ringkasan_terakhir_at() is None
    store.close()


def test_galat_yang_sudah_dibatalkan_sqlite_sendiri_tetap_galat_aslinya(tmp_path):
    """Carry B-T7 no. 6: SQLITE_FULL/IOERR bisa membuat SQLite membatalkan transaksinya
    SENDIRI. `ROLLBACK` mentah sesudahnya melempar "cannot rollback - no transaction is
    active" dan menutupi galat asli (disk penuh), yang justru harus dibaca support.

    Pembatalan otomatis itu tidak bisa dipicu dengan andal dari test, jadi ditiru: kode di
    dalam `susun` membatalkan transaksi koneksi store lalu melempar galat disk penuh."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    def _disk_penuh(kelompok):
        store._db.execute("ROLLBACK")  # yang dilakukan SQLite sendiri pada SQLITE_FULL
        raise sqlite3.OperationalError("database or disk is full")

    with pytest.raises(sqlite3.OperationalError, match="database or disk is full"):
        store.susun(_disk_penuh, now=5.0)

    assert store.tertua_masuk_at() == 1000.0
    assert not store.ada_kiriman()
    store.write("ERROR", "b", "sesudahnya", None, now=6.0)  # store tetap bisa dipakai
    assert store.ringkasan()["menunggu_jenis"] == 2
    store.close()


def test_antrean_selamat_sesudah_konsol_restart(tmp_path):
    """Ringkasan yang disusun saat offline terkirim sesudah restart, tidak dibuang."""
    jalur = tmp_path / "lapor.db"
    store = LaporDiscordStore(jalur, jam=_Jam())
    store.write("ERROR", "a", "sebelum restart", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    store.write("ERROR", "a", "belum disusun", None, now=3.0)
    store.close()

    baru = LaporDiscordStore(jalur, jam=_Jam())

    assert baru.kiriman_berikut().isi == "1x konsol sebelum restart"
    assert baru.ringkasan()["menunggu_jenis"] == 1
    assert baru.ringkasan_terakhir_at() == 2.0
    baru.close()


def test_gagal_tetap_menyimpan_pesan_dan_mencatat_galat(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    k = store.kiriman_berikut()

    store.tandai_gagal(k.id, galat="Discord menjawab HTTP 404", status_http=404, now=3.0)
    store.tandai_gagal(k.id, galat="Discord tidak terjangkau (ConnectError)", status_http=None, now=4.0)

    ulang = store.kiriman_berikut()
    assert (ulang.id, ulang.percobaan) == (k.id, 2)
    r = store.ringkasan()
    assert (r["galat"], r["galat_at"], r["status_http"], r["kiriman"]) == (
        "Discord tidak terjangkau (ConnectError)", 4.0, None, 1,
    )
    store.close()


def test_terkirim_menghapus_pesan_dan_membersihkan_galat(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)
    store.susun(_susun_mentah, now=2.0)
    k = store.kiriman_berikut()
    store.tandai_gagal(k.id, galat="HTTP 503", status_http=503, now=3.0)

    store.tandai_terkirim(k.id, now=9.0)

    r = store.ringkasan()
    assert (r["kiriman"], r["galat"], r["status_http"], r["terkirim_terakhir_at"]) == (0, None, None, 9.0)
    store.close()


def test_jenis_galat_terlalu_banyak_dilebur_ke_kelompok_lain_bukan_dibuang(tmp_path, monkeypatch):
    monkeypatch.setattr(lapor_discord_repository, "BATAS_KELOMPOK_MENUNGGU", 1)
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "pertama", None, now=1.0)
    store.write("ERROR", "a", "kedua", None, now=2.0)
    store.write("ERROR", "a", "ketiga", None, now=3.0)
    store.write("ERROR", "a", "pertama", None, now=4.0)  # jenis lama tetap dihitung di tempatnya

    kelompok = []
    store.susun(lambda ks: kelompok.extend(ks) or ["x"], now=5.0)

    assert sorted((k.message, k.jumlah) for k in kelompok) == [(PESAN_LAIN, 2), ("pertama", 2)]
    store.close()


def test_batas_jenis_bawaan():
    assert BATAS_KELOMPOK_MENUNGGU == 500


def test_berkas_memakai_wal(tmp_path):
    store = LaporDiscordStore(tmp_path / "lapor.db")
    db = sqlite3.connect(str(tmp_path / "lapor.db"))
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()
    store.close()


def test_susun_satu_transaksi_kegagalan_di_tengah_tidak_menyisakan_setengah(tmp_path):
    """I1: kegagalan INSERT kiriman kedua (NOT NULL) tidak boleh menyisakan kiriman
    pertama atau menghapus galat menunggu. Ini yang membuktikan `susun` benar-benar
    satu transaksi, bukan cuma "kebetulan tidak pernah gagal di tengah" di test lain."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    def _pesan_kedua_null(kelompok):
        return ["ok", None]  # None gagal NOT NULL saat INSERT ke kiriman

    with pytest.raises(sqlite3.IntegrityError):
        store.susun(_pesan_kedua_null, now=5.0)

    r = store.ringkasan()
    assert r["kiriman"] == 0
    assert r["menunggu_jenis"] == 1
    assert r["ringkasan_terakhir_at"] is None
    store.close()


def test_susun_pesan_yang_log_error_tidak_deadlock(tmp_path):
    """I2: `susun` memegang kunci sambil memanggil `susun_pesan` (kode luar). Kalau
    kode itu mencatat ERROR lewat root handler yang disambungkan ke store yang sama
    (`write`), thread yang sama tidak boleh mengunci dirinya sendiri selamanya. Guard
    re-entry per-thread: entri dari dalam `susun_pesan` dilewati (bukan disimpan),
    bukan menunggu kunci."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "sebelum susun", None, now=1.0)

    logger = logging.getLogger("test_i2_" + str(id(store)))
    logger.setLevel(logging.ERROR)

    class _HandlerKeStore(logging.Handler):
        def createLock(self) -> None:
            # Tanpa kunci handler: kalau guard re-entry regresi, thread daemon yang
            # menggantung tidak memegang kunci yang ditunggu `logging.shutdown()` saat
            # interpreter keluar, jadi test gagal alih-alih menggantungkan pytest.
            self.lock = None

        def emit(self, record: logging.LogRecord) -> None:
            store.write("ERROR", record.name, record.getMessage(), None, now=99.0)

    handler = _HandlerKeStore()
    logger.addHandler(handler)

    def _susun_yang_log(kelompok):
        logger.error("galat dari dalam susun_pesan")
        return ["pesan jadi"]

    hasil = {}

    def _jalankan():
        try:
            hasil["jumlah"] = store.susun(_susun_yang_log, now=5.0)
        except BaseException as e:  # pragma: no cover, dilaporkan lewat assert di bawah
            hasil["galat"] = e

    t = threading.Thread(target=_jalankan, daemon=True)
    t.start()
    t.join(timeout=5.0)

    logger.removeHandler(handler)
    if t.is_alive():
        # susun() masih memegang self._lock di thread lain: SETIAP panggilan lain ke
        # store (termasuk store.ringkasan() atau store.close()) akan ikut menggantung
        # di sini. Gagal SEKARANG, jangan sentuh store lagi.
        pytest.fail("susun() masih menggantung, deadlock re-entry belum diperbaiki")
    assert "galat" not in hasil, hasil.get("galat")
    assert hasil["jumlah"] == 1

    r = store.ringkasan()
    assert r["kiriman"] == 1
    assert r["menunggu_jenis"] == 0
    store.close()


def test_susun_begin_immediate_menahan_tulisan_koneksi_lain(tmp_path):
    """M1: `susun` mengunci tulis (`BEGIN IMMEDIATE`) sebelum SELECT, supaya galat
    yang ditulis koneksi/proses lain di antara SELECT dan DELETE tidak hilang begitu
    saja. Dibuktikan dengan dua instance store pada satu berkas: instance kedua yang
    menulis SAAT instance pertama sedang menyusun harus menunggu, bukan menyelinap
    lalu terhapus tanpa pernah ikut kelompokkan."""
    jalur = tmp_path / "lapor.db"
    store_a = LaporDiscordStore(jalur, jam=_Jam())
    store_b = LaporDiscordStore(jalur, jam=_Jam(2000.0))
    store_a.write("ERROR", "a", "pertama", None, now=1.0)

    mulai_susun = threading.Event()
    boleh_tulis_b = threading.Event()
    hasil = {}

    def _susun_pesan_lambat(kelompok):
        mulai_susun.set()
        boleh_tulis_b.wait(timeout=5.0)
        return _susun_mentah(kelompok)

    def _jalankan_susun():
        hasil["jumlah"] = store_a.susun(_susun_pesan_lambat, now=10.0)

    t = threading.Thread(target=_jalankan_susun, daemon=True)
    t.start()
    assert mulai_susun.wait(timeout=5.0)

    def _tulis_dari_b():
        store_b.write("ERROR", "b", "kedua dari koneksi lain", None, now=3.0)

    tb = threading.Thread(target=_tulis_dari_b, daemon=True)
    tb.start()
    tb.join(timeout=0.3)
    b_selesai_lebih_dulu = not tb.is_alive()

    boleh_tulis_b.set()
    tb.join(timeout=5.0)
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert not tb.is_alive()
    assert not b_selesai_lebih_dulu, "tulisan store_b tidak tertahan BEGIN IMMEDIATE store_a"

    r = store_a.ringkasan()
    # Galat dari store_b ditulis SESUDAH susun store_a commit, jadi menunggu ringkasan berikutnya.
    assert r["menunggu_jenis"] == 1
    store_a.close()
    store_b.close()


def test_pesan_kosong_untuk_galat_tidak_kosong_menolak_bukan_menghapus(tmp_path):
    """M4: `susun_pesan` yang mengembalikan [] padahal ada galat menunggu adalah bug
    pemanggil (bukan "tidak ada apa-apa untuk dikirim"), jadi tidak boleh diam-diam
    mengosongkan antrean tanpa mengirim satu pesan pun."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    store.write("ERROR", "a", "x", None, now=1.0)

    with pytest.raises(ValueError):
        store.susun(lambda kelompok: [], now=5.0)

    r = store.ringkasan()
    assert r["menunggu_jenis"] == 1
    assert r["kiriman"] == 0
    store.close()


def test_pesan_dan_sumber_dipotong_saat_masuk(tmp_path):
    """M3: pesan/sumber yang sangat panjang tidak membuat baris `galat_menunggu`
    tumbuh tanpa batas (bug atau serangan di hulu tidak boleh membengkakkan berkas)."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    panjang = "x" * 10_000

    store.write("ERROR", panjang, panjang, None, now=1.0)

    kelompok = []
    store.susun(lambda ks: kelompok.extend(ks) or ["p"], now=5.0)
    (k,) = kelompok
    assert len(k.message) < 10_000
    assert len(k.source) < 10_000
    store.close()


def test_write_di_bawah_error_diabaikan(tmp_path):
    """M5: pertahanan lapis kedua, seandainya handler yang memanggil `write` suatu
    hari salah level. `galat_menunggu` tidak boleh menerima WARNING/INFO."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())

    store.write("WARNING", "a", "cuma peringatan", None, now=1.0)

    assert store.ringkasan()["menunggu_jenis"] == 0
    store.close()


def test_pesan_sama_galat_berbeda_dua_kelompok_dengan_nama_kelasnya(tmp_path):
    """Tiap 500 uvicorn berpesan "Exception in ASGI application": tanpa nama kelas
    galatnya, Discord menulis satu kelompok yang tidak mengatakan apa pun."""
    store = LaporDiscordStore(tmp_path / "lapor.db", jam=_Jam())
    asgi = "Exception in ASGI application\n"
    store.write("ERROR", "uvicorn.error", asgi, _tb("KeyError: 'state'"), now=10.0)
    store.write("ERROR", "uvicorn.error", asgi, _tb("sqlite3.IntegrityError: x\nB1234XY"), now=20.0)
    store.write("ERROR", "uvicorn.error", asgi, _tb("KeyError: 'lain'"), now=30.0)

    store.susun(_susun_mentah, now=100.0)

    isi = []
    while (k := store.kiriman_berikut()) is not None:
        isi.append(k.isi)
        store.tandai_terkirim(k.id, now=101.0)
    assert isi == [
        "2x konsol Exception in ASGI application (KeyError)",
        "1x konsol Exception in ASGI application (sqlite3.IntegrityError)",
    ]
    store.close()


def test_berkas_lama_tanpa_kolom_isi_ditolak_diberi_kolom_di_tempat(tmp_path):
    """Berkas dari versi sebelum kolom `isi_ditolak` (dan `disisihkan_at`) tetap bisa dibuka;
    pesan yang menunggu di sana utuh dan mulai dari nol penolakan."""
    jalur = tmp_path / "lapor.db"
    db = sqlite3.connect(jalur)
    db.executescript(
        "CREATE TABLE kiriman (id INTEGER PRIMARY KEY AUTOINCREMENT, isi TEXT NOT NULL,"
        " dibuat_at REAL NOT NULL, percobaan INTEGER NOT NULL DEFAULT 0, galat TEXT, galat_at REAL);"
        "INSERT INTO kiriman (isi, dibuat_at, percobaan) VALUES ('pesan lama', 1.0, 4);"
    )
    db.commit()
    db.close()
    store = LaporDiscordStore(jalur, jam=_Jam())
    k = store.kiriman_berikut()
    assert (k.isi, k.percobaan, k.isi_ditolak) == ("pesan lama", 4, 0)
    store.tandai_gagal(k.id, galat="Discord menjawab HTTP 400", status_http=400, now=2.0, isi_ditolak=True)
    store.tandai_gagal(k.id, galat="Discord tidak terjangkau", status_http=None, now=3.0)
    assert store.kiriman_berikut().isi_ditolak == 1
    store.close()
