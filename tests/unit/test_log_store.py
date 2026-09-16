from palmgrade.repositories.log_repository import LogStore

SEJAM = 3600.0


def test_baris_tersimpan_dan_terbaca(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["pesan"] == "line-2 putus"
    assert hasil["items"][0]["jumlah"] == 1


def test_pesan_kembar_digabung_bukan_ditumpuk(tmp_path):
    """Kabel kamera putus bikin error tiap detik; 347 baris identik tidak kebaca."""
    store = LogStore(tmp_path / "log.db")
    for i in range(5):
        store.write("ERROR", "kamera", "line-2 putus", None, now=1000.0 + i)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["jumlah"] == 5
    assert hasil["items"][0]["terakhir_at"] == 1004.0


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
    assert hasil["items"][0]["sumber"] == "plc"


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
    assert store.read(level=None, search=None, limit=10, offset=0)["items"][0]["pesan"] == "baru"


def test_baris_lewat_retensi_dibuang(tmp_path):
    store = LogStore(tmp_path / "log.db", retention_days=180)
    lama = 1000.0
    store.write("ERROR", "a", "lama", None, now=lama)
    sekarang = lama + 181 * 24 * SEJAM
    store.write("ERROR", "b", "baru", None, now=sekarang)
    assert store.purge_expired(now=sekarang) == 1
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    assert hasil["items"][0]["pesan"] == "baru"


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
    assert hasil["items"][0]["pesan"] == "line-1 putus"
