"""`LogStore.serap_line` (batch 3.2): log line masuk `event_log` tanpa hilang dan tanpa ganda."""
from __future__ import annotations

import sqlite3

import pytest

from palmgrade.domain.log_line import EntriTarik, JawabanLog, KursorLine
from palmgrade.repositories import log_serap_line
from palmgrade.repositories.log_repository import LogStore


def _e(id_: int, seq: int, *, count: int = 1, level: str = "ERROR", message: str | None = None,
       first_at: float = 100.0, last_at: float = 100.0, detail: str | None = None) -> EntriTarik:
    return EntriTarik(id_, seq, first_at, last_at, level, "palmgrade.workers.x",
                      message or f"pesan {id_}", detail, count)


def _tb(kelas_pesan: str, baris: int = 12) -> str:
    """Traceback berbentuk asli: penanda, frame, baris kode, lalu kepala galat."""
    return ("Traceback (most recent call last):\n"
            f'  File "/app/src/palmgrade/workers/x.py", line {baris}, in f\n'
            "    jalan()\n"
            f"{kelas_pesan}\n")


def _j(*entri: EntriTarik, generasi: str = "g1", seq_akhir: int | None = None,
       lagi: bool = False, dibuang: int = 0) -> JawabanLog:
    akhir = seq_akhir if seq_akhir is not None else max((e.seq for e in entri), default=0)
    return JawabanLog(generasi, tuple(entri), akhir, lagi, dibuang)


def _baris(store: LogStore) -> list[dict]:
    return store.read(level=None, search=None, limit=100, offset=0)["items"]


def test_entri_line_tersimpan_bertanda_line_dengan_waktu_pertama_dari_line(tmp_path):
    store = LogStore(tmp_path / "log.db")

    store.serap_line("line-2", _j(_e(1, 1, first_at=100.0, last_at=160.0, count=3, detail="tb")), now=200.0)

    (b,) = _baris(store)
    assert (b["line_code"], b["level"], b["message"], b["count"]) == ("line-2", "ERROR", "pesan 1", 3)
    assert (b["logged_at"], b["last_seen_at"], b["detail"]) == (100.0, 160.0, "tb")


def test_kursor_maju_bersama_barisnya(tmp_path):
    store = LogStore(tmp_path / "log.db")
    assert store.kursor_line("line-1") == KursorLine()

    store.serap_line("line-1", _j(_e(1, 4), dibuang=2), now=1.0)

    assert store.kursor_line("line-1") == KursorLine("g1", 4, 2)
    assert store.kursor_line("line-2") == KursorLine()


def test_halaman_yang_sama_diserap_dua_kali_tidak_ganda(tmp_path):
    """Jawaban hilang di jalan lalu diminta ulang: tetap satu baris."""
    store = LogStore(tmp_path / "log.db")
    halaman = _j(_e(1, 1), _e(2, 2))

    store.serap_line("line-1", halaman, now=1.0)
    store.serap_line("line-1", halaman, now=2.0)

    assert len(_baris(store)) == 2


def test_baris_yang_digabung_di_line_memperbarui_hitungan_bukan_menambah(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-1", _j(_e(1, 1, count=1, last_at=100.0)), now=1.0)
    halaman = _j(_e(1, 5, count=4, last_at=150.0))

    galat = store.galat_baru_line("line-1", halaman)
    store.serap_line("line-1", halaman, now=2.0)

    (b,) = _baris(store)
    assert (b["count"], b["last_seen_at"], b["logged_at"]) == (4, 150.0, 100.0)
    assert [g.tambah for g in galat] == [3]


def test_galat_baru_cuma_error_yang_benar_benar_bertambah(tmp_path):
    store = LogStore(tmp_path / "log.db")
    halaman = _j(_e(1, 1, count=2), _e(2, 2, level="WARNING"))

    pertama = store.galat_baru_line("line-3", halaman)
    store.serap_line("line-3", halaman, now=1.0)
    ulang = store.galat_baru_line("line-3", halaman)

    assert [(g.line_code, g.message, g.tambah) for g in pertama] == [("line-3", "pesan 1", 2)]
    assert ulang == ()


def test_galat_baru_tidak_menulis_apa_pun(tmp_path):
    """Carry B-T7 no. 2: dipanggil SEBELUM serapan. Kalau ia ikut menulis, galat yang
    diteruskan ke Discord lalu mati sebelum serapan akan terbaca "sudah terlihat" dan
    hilang dari tarikan ulang, bukan dihitung lagi."""
    store = LogStore(tmp_path / "log.db")
    halaman = _j(_e(1, 1, count=2))

    assert len(store.galat_baru_line("line-1", halaman)) == 1
    assert len(store.galat_baru_line("line-1", halaman)) == 1
    assert _baris(store) == []
    assert store.kursor_line("line-1") == KursorLine()


def test_id_sama_dari_line_lain_baris_lain(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-1", _j(_e(1, 1)), now=1.0)
    store.serap_line("line-2", _j(_e(1, 1)), now=1.0)

    assert sorted(b["line_code"] for b in _baris(store)) == ["line-1", "line-2"]


def test_generasi_baru_id_sama_tetap_baris_baru(tmp_path):
    """Log line direset: id 1 generasi baru bukan id 1 generasi lama."""
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-1", _j(_e(1, 1, message="lama")), now=1.0)
    store.serap_line("line-1", _j(_e(1, 1, message="baru"), generasi="g2"), now=2.0)

    assert sorted(b["message"] for b in _baris(store)) == ["baru", "lama"]
    assert store.kursor_line("line-1").generasi == "g2"


def test_dibuang_baru_dihitung_selisih_per_generasi(tmp_path):
    store = LogStore(tmp_path / "log.db")
    assert store.serap_line("line-1", _j(_e(1, 1), dibuang=5), now=1.0).dibuang_baru == 5
    assert store.serap_line("line-1", _j(seq_akhir=1, dibuang=5), now=2.0).dibuang_baru == 0
    assert store.serap_line("line-1", _j(seq_akhir=1, dibuang=9), now=3.0).dibuang_baru == 4
    assert store.serap_line("line-1", _j(seq_akhir=0, dibuang=1, generasi="g2"), now=4.0).dibuang_baru == 1


def test_penggabungan_milik_konsol_tidak_menyentuh_baris_line(tmp_path):
    """Pesan konsol yang teksnya sama persis dengan baris line tetap baris sendiri."""
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-1", _j(_e(1, 1, message="sama", last_at=1000.0)), now=1000.0)

    store.write("ERROR", "palmgrade.workers.x", "sama", None, now=1001.0)

    baris = _baris(store)
    assert len(baris) == 2
    assert sorted((b["line_code"] or "konsol", b["count"]) for b in baris) == [("konsol", 1), ("line-1", 1)]


def test_serapan_yang_gagal_di_tengah_tidak_menyimpan_apa_pun(tmp_path, monkeypatch):
    """Satu transaksi: baris kedua gagal = baris pertama dan kursor ikut batal."""
    store = LogStore(tmp_path / "log.db")
    asli = log_serap_line._simpan_entri
    panggilan = {"n": 0}

    def _simpan_lalu_mati(db, line_code, generasi, e):
        panggilan["n"] += 1
        if panggilan["n"] == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return asli(db, line_code, generasi, e)

    monkeypatch.setattr(log_serap_line, "_simpan_entri", _simpan_lalu_mati)
    with pytest.raises(sqlite3.OperationalError):
        store.serap_line("line-1", _j(_e(1, 1), _e(2, 2)), now=1.0)

    assert _baris(store) == []
    assert store.kursor_line("line-1") == KursorLine()


def test_kursor_selamat_saat_danger_zone_mengosongkan_log(tmp_path):
    """Hapus log tidak menarik ulang baris line lama yang sudah pernah tampil."""
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-1", _j(_e(1, 7)), now=1.0)

    store.hapus_semua()

    assert store.kursor_line("line-1") == KursorLine("g1", 7, 0)


def test_cari_menemukan_kode_line(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.serap_line("line-2", _j(_e(1, 1, message="kamera putus")), now=1.0)
    store.write("ERROR", "konsol", "lain", None, now=2.0)

    hasil = store.read(level=None, search="line-2", limit=10, offset=0)

    assert [b["message"] for b in hasil["items"]] == ["kamera putus"]


_SKEMA_LAMA = """
CREATE TABLE event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at REAL NOT NULL, level TEXT NOT NULL,
    source TEXT NOT NULL, message TEXT NOT NULL, detail TEXT, fingerprint TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1, last_seen_at REAL NOT NULL
);
"""


def test_berkas_log_konsol_lama_diberi_kolom_di_tempat(tmp_path):
    """PC Lampung: `log_kejadian.db` versi sebelum batch 3 punya isi. Isinya utuh."""
    jalur = tmp_path / "log.db"
    db = sqlite3.connect(str(jalur))
    db.executescript(_SKEMA_LAMA)
    with db:
        db.execute(
            "INSERT INTO event_log (logged_at, level, source, message, fingerprint, last_seen_at)"
            " VALUES (1.0, 'ERROR', 'konsol', 'galat lama', 'abc', 1.0)"
        )
    db.close()

    store = LogStore(jalur)
    store.serap_line("line-1", _j(_e(1, 1)), now=2.0)

    pesan = {(b["message"], b["line_code"]) for b in _baris(store)}
    assert pesan == {("galat lama", None), ("pesan 1", "line-1")}
    LogStore(jalur)  # dibuka lagi: idempoten


def test_konsol_versi_lama_tetap_bisa_menulis_ke_berkas_baru(tmp_path):
    """Rollback: INSERT tanpa kolom baru (bentuk `LogStore.write` lama) tetap diterima."""
    jalur = tmp_path / "log.db"
    LogStore(jalur).serap_line("line-1", _j(_e(1, 1)), now=1.0)
    db = sqlite3.connect(str(jalur))
    with db:
        db.execute(
            "INSERT INTO event_log (logged_at, level, source, message, detail, fingerprint, count, last_seen_at)"
            " VALUES (5.0, 'ERROR', 'konsol', 'dari versi lama', NULL, 'f', 1, 5.0)"
        )
    assert db.execute("SELECT COUNT(*) FROM event_log").fetchone()[0] == 2


def test_galat_baru_line_membawa_nama_kelas_galatnya(tmp_path):
    """Dua 500 berbeda di line jadi dua baris di sana; untuk Discord keduanya harus
    tetap dua kelompok, jadi pesan yang diteruskan membawa nama kelasnya."""
    store = LogStore(tmp_path / "log.db")
    asgi = "Exception in ASGI application"
    halaman = _j(
        _e(1, 1, message=asgi, detail=_tb("KeyError: 'a'")),
        _e(2, 2, message=asgi, detail=_tb("OSError: disk\nB1234XY")),
        _e(3, 3, message="tanpa traceback"),
    )
    galat = store.galat_baru_line("line-2", halaman)
    assert [g.message for g in galat] == [
        f"{asgi} (KeyError)", f"{asgi} (OSError)", "tanpa traceback",
    ]
