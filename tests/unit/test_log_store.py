import sqlite3

from palmgrade.repositories.log_repository import LogStore, _fingerprint

SEJAM = 3600.0


def test_baris_tersimpan_dan_terbaca(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["message"] == "line-2 putus"
    assert hasil["items"][0]["count"] == 1


def test_pesan_kembar_digabung_bukan_ditumpuk(tmp_path):
    """Kabel kamera putus bikin error tiap detik; 347 baris identik tidak kebaca."""
    store = LogStore(tmp_path / "log.db")
    for i in range(5):
        store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0 + i)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["count"] == 5
    assert hasil["items"][0]["last_seen_at"] == 1004.0


def test_kembar_di_luar_jendela_jadi_baris_baru(tmp_path):
    """Kejadian yang sama besok bukan kejadian yang sama."""
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0 + 61)
    assert store.read(level=None, search=None, limit=10, offset=0)["total"] == 2


def test_sumber_berbeda_tidak_digabung(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "kamera", "putus", None, now=1000.0)
    store.write("ERROR", "plc", "putus", None, now=1001.0)
    assert store.read(level=None, search=None, limit=10, offset=0)["total"] == 2


def test_saring_level(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "a", "satu", None, now=1000.0)
    store.write("WARNING", "b", "dua", None, now=1001.0)
    assert store.read(level="ERROR", search=None, limit=10, offset=0)["total"] == 1


def test_cari_di_pesan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    store.write("ERROR", "plc", "modbus timeout", None, now=1001.0)
    hasil = store.read(level=None, search="modbus", limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["source"] == "plc"


def test_total_hitungan_seluruh_kecocokan_bukan_sepanjang_halaman(tmp_path):
    """Jebakan yang sama dengan pagination grading: total datang dari SQL."""
    store = LogStore(tmp_path / "log.db")
    for i in range(25):
        store.write("ERROR", f"s{i}", f"pesan {i}", None, now=1000.0 + i * 100)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 25
    assert len(hasil["items"]) == 10


def test_terbaru_di_atas(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "a", "lama", None, now=1000.0)
    store.write("ERROR", "b", "baru", None, now=2000.0)
    assert store.read(level=None, search=None, limit=10, offset=0)["items"][0]["message"] == "baru"


def test_baris_lewat_retensi_dibuang(tmp_path):
    store = LogStore(tmp_path / "log.db", retention_days=180)
    lama = 1000.0
    store.write("ERROR", "a", "lama", None, now=lama)
    sekarang = lama + 181 * 24 * SEJAM
    store.write("ERROR", "b", "baru", None, now=sekarang)
    assert store.purge_expired(now=sekarang) == 1
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["message"] == "baru"


def test_baris_dalam_retensi_tidak_dibuang(tmp_path):
    store = LogStore(tmp_path / "log.db", retention_days=180)
    store.write("ERROR", "a", "masih muda", None, now=1000.0)
    assert store.purge_expired(now=1000.0 + 179 * 24 * SEJAM) == 0


def test_buka_ulang_db_yang_sudah_ada_tidak_gagal(tmp_path):
    """Konstruksi kedua di path yang sama tidak boleh gagal atau membuang baris."""
    db_path = tmp_path / "log.db"
    store1 = LogStore(db_path)
    store1.write("ERROR", "kamera", "line-1 putus", None, now=1000.0)

    store2 = LogStore(db_path)
    hasil = store2.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["message"] == "line-1 putus"


def test_tabel_lama_log_kejadian_dimigrasi(tmp_path):
    """A database written before the English rename must keep its rows.

    Builds the OLD schema directly with sqlite3 (not LogStore, which only
    ever writes the new one), then opens it with LogStore and checks the
    rows read back under the new table and column names.
    """
    db_path = tmp_path / "log.db"
    # Real fingerprints, not placeholders: the follow-up `store.write()` below
    # computes its own fingerprint the normal way, and it must land on the
    # migrated row to prove the merge-by-fingerprint path survives the rename.
    fp_kamera = _fingerprint("ERROR", "kamera", "line-2 putus")
    fp_plc = _fingerprint("WARNING", "plc", "modbus timeout")
    raw = sqlite3.connect(str(db_path))
    raw.executescript(
        """
        CREATE TABLE log_kejadian (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            waktu       REAL NOT NULL,
            level       TEXT NOT NULL,
            sumber      TEXT NOT NULL,
            pesan       TEXT NOT NULL,
            detail      TEXT,
            sidik       TEXT NOT NULL,
            jumlah      INTEGER NOT NULL DEFAULT 1,
            terakhir_at REAL NOT NULL
        );
        """
    )
    raw.execute(
        "INSERT INTO log_kejadian"
        " (waktu, level, sumber, pesan, detail, sidik, jumlah, terakhir_at)"
        " VALUES (1000.0, 'ERROR', 'kamera', 'line-2 putus', NULL, ?, 3, 1002.0)",
        (fp_kamera,),
    )
    raw.execute(
        "INSERT INTO log_kejadian"
        " (waktu, level, sumber, pesan, detail, sidik, jumlah, terakhir_at)"
        " VALUES (2000.0, 'WARNING', 'plc', 'modbus timeout', 'trace', ?, 1, 2000.0)",
        (fp_plc,),
    )
    raw.commit()
    raw.close()

    store = LogStore(db_path)
    hasil = store.read(level=None, search=None, limit=10, offset=0)

    assert hasil["total"] == 2
    baris = {r["message"]: r for r in hasil["items"]}
    assert baris["line-2 putus"]["source"] == "kamera"
    assert baris["line-2 putus"]["count"] == 3
    assert baris["line-2 putus"]["last_seen_at"] == 1002.0
    assert baris["modbus timeout"]["detail"] == "trace"

    # The old table must be gone, not left behind alongside the new one.
    tables = {
        r[0]
        for r in store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "log_kejadian" not in tables
    assert "event_log" in tables

    # A duplicate of the merged row still fits the merge window off its
    # migrated last_seen_at - proves the new column, not just its name, works.
    store.write("ERROR", "kamera", "line-2 putus", None, now=1002.0 + 5)
    hasil2 = store.read(level=None, search=None, limit=10, offset=0)
    assert next(r for r in hasil2["items"] if r["message"] == "line-2 putus")["count"] == 4
