"""Penghapus data SISI LINE — berkas sungguhan di folder sementara.

Line menghapus datanya sendiri SAAT BOOT, sebelum satu pun store membuka
berkasnya: SQLite yang sedang dibuka tidak boleh dihapus dari bawah proses yang
memakainya. Yang dijaga di sini:

- `license.db*` selamat — penjaga jam lisensi, bukan data transaksi;
- penanda dihapus PALING AKHIR, dan tidak dihapus kalau ada yang gagal, supaya
  boot yang terputus (listrik mati) mengulang, bukan meninggalkan separuh data;
- rekaman `line-1` tidak pernah menyeret milik `line-10`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from palmgrade.services import hapus_data_line
from palmgrade.services.hapus_data_line import (
    MILIK_LINE_DI_STATE,
    PENANDA,
    hapus_diminta,
    hapus_kalau_diminta,
    hapus_rekaman,
    ringkas_rekaman,
    tulis_penanda,
)


def _isi_line(root: Path) -> tuple[Path, Path]:
    """Folder line seperti di pabrik: foto bersarang, outbox, lisensi, manifest."""
    artifacts = root / "artifacts"
    state = root / "state"
    foto = artifacts / "results" / "2026-09-25" / "101500_B1234XY_abcd1234" / "bbox" / "Ripe"
    foto.mkdir(parents=True)
    (foto / "a_auto.webp").write_bytes(b"x" * 10)
    (artifacts / "results" / "2026-09-25" / "a_ripeness.json").write_text("{}")
    (artifacts / "outbox.db").write_bytes(b"db")
    (artifacts / "outbox.db-wal").write_bytes(b"wal")
    (artifacts / "license.db").write_bytes(b"lic")
    (artifacts / "license.db-wal").write_bytes(b"licwal")
    state.mkdir()
    (state / "upload_manifest.db").write_bytes(b"m")
    return artifacts, state


def _sisa(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")}


def test_tanpa_penanda_tidak_menyentuh_apa_pun(tmp_path):
    artifacts, state = _isi_line(tmp_path)
    sebelum = _sisa(tmp_path)

    assert hapus_kalau_diminta(artifacts, state) is None

    assert _sisa(tmp_path) == sebelum


def test_penanda_menghapus_semua_kecuali_lisensi(tmp_path):
    artifacts, state = _isi_line(tmp_path)
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="support@pks.id", now=1000.0)

    hasil = hapus_kalau_diminta(artifacts, state)

    assert _sisa(artifacts) == {"license.db", "license.db-wal"}
    assert _sisa(state) == set()
    assert hasil["mode"] == "transaksi"
    assert hasil["diminta_oleh"] == "support@pks.id"
    assert hasil["gagal"] == 0
    # Item tingkat atas, satu lintasan: results/, outbox.db, outbox.db-wal,
    # upload_manifest.db. Menghitung per berkas berarti menyisir pohon foto dua
    # kali — berbulan-bulan foto = menit tambahan saat line mati.
    assert hasil["dihapus"] == 4


def test_isi_lisensi_tidak_berubah(tmp_path):
    artifacts, state = _isi_line(tmp_path)
    tulis_penanda(artifacts, mode="semua", diminta_oleh="s", now=1.0)

    hapus_kalau_diminta(artifacts, state)

    assert (artifacts / "license.db").read_bytes() == b"lic"


def test_penanda_ditulis_sebagai_json_di_folder_artifacts(tmp_path):
    """Di `artifacts/`, bukan `state/`: artifacts SELALU milik satu line (Docker:
    `./artifacts/line-N`, native: `ARTIFACTS_DIR` per line), sedangkan `state/`
    dipakai bersama konsol dan tiga line di jalur native (`make line` + `make
    console`) — penanda di situ dimakan line pertama yang boot."""
    artifacts = tmp_path / "artifacts"
    jalur = tulis_penanda(artifacts, mode="semua", diminta_oleh="a@b.c", now=1234.5)

    assert jalur == artifacts / PENANDA
    isi = json.loads(jalur.read_text())
    assert isi == {"mode": "semua", "diminta_oleh": "a@b.c", "diminta_pada": 1234.5}


def test_penanda_dihapus_paling_akhir(tmp_path, monkeypatch):
    """Urutan: isi dulu, penanda terakhir. Kalau penanda hilang lebih dulu dan
    listrik mati di tengah, boot berikutnya tidak tahu masih ada yang harus
    dihapus — separuh data tertinggal tanpa jejak."""
    artifacts, state = _isi_line(tmp_path)
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)
    penanda_ada_saat_menghapus: list[bool] = []
    asli = hapus_data_line._hapus

    def catat(jalur: Path):
        penanda_ada_saat_menghapus.append((artifacts / PENANDA).exists())
        return asli(jalur)

    monkeypatch.setattr(hapus_data_line, "_hapus", catat)
    hapus_kalau_diminta(artifacts, state)

    assert penanda_ada_saat_menghapus, "tidak ada yang dihapus sama sekali"
    assert all(penanda_ada_saat_menghapus)
    assert not (artifacts / PENANDA).exists()


def test_yang_gagal_dihapus_menahan_penanda(tmp_path, monkeypatch):
    """Satu berkas yang tidak bisa dihapus (izin, dipegang proses lain) =
    penanda tetap, jadi boot berikutnya mencoba lagi."""
    artifacts, state = _isi_line(tmp_path)
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)
    asli = hapus_data_line._hapus

    def gagal_sekali(jalur: Path):
        if jalur.name == "outbox.db":
            return False
        return asli(jalur)

    monkeypatch.setattr(hapus_data_line, "_hapus", gagal_sekali)
    hasil = hapus_kalau_diminta(artifacts, state)

    assert hasil["gagal"] == 1
    assert (artifacts / PENANDA).exists()
    assert (artifacts / "outbox.db").exists()

    # Boot berikutnya, penghalangnya sudah hilang: tuntas, penanda ikut hilang.
    monkeypatch.setattr(hapus_data_line, "_hapus", asli)
    hasil = hapus_kalau_diminta(artifacts, state)
    assert hasil["gagal"] == 0
    assert _sisa(artifacts) == {"license.db", "license.db-wal"}
    assert not (artifacts / PENANDA).exists()


def test_penanda_rusak_tetap_diproses(tmp_path):
    """Penanda yang isinya rusak tetap berarti "hapus": keberadaannya itulah
    perintahnya. Mengabaikannya membuat line menyimpan data yang sudah diminta
    dihapus, dan konsol sudah mengosongkan index-nya."""
    artifacts, state = _isi_line(tmp_path)
    (artifacts / PENANDA).write_text("{bukan json")

    hasil = hapus_kalau_diminta(artifacts, state)

    assert hasil["mode"] == "?"
    assert _sisa(artifacts) == {"license.db", "license.db-wal"}


def test_folder_state_belum_ada_tidak_error(tmp_path):
    artifacts = tmp_path / "artifacts"
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)

    hasil = hapus_kalau_diminta(artifacts, tmp_path / "belum-ada")

    assert hasil["gagal"] == 0
    assert not (artifacts / PENANDA).exists()


# ── rekaman ─────────────────────────────────────────────────────────────────


def _rekaman(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "line-1_20260925-101500.mp4").write_bytes(b"a" * 100)
    (folder / "line-1_20260925-101500-2.mp4").write_bytes(b"b" * 50)
    (folder / "line-10_20260925-101500.mp4").write_bytes(b"c" * 7)
    (folder / "line-2_20260925-101500.mp4").write_bytes(b"d" * 9)
    (folder / "line-1_catatan.txt").write_text("bukan rekaman")


def test_ringkas_rekaman_cuma_milik_line_itu(tmp_path):
    _rekaman(tmp_path / "videos")

    assert ringkas_rekaman(tmp_path / "videos", "line-1") == {"berkas": 2, "bytes": 150}


def test_hapus_rekaman_tidak_menyeret_line_10(tmp_path):
    videos = tmp_path / "videos"
    _rekaman(videos)

    hasil = hapus_rekaman(videos, "line-1")

    assert hasil == {"berkas": 2, "bytes": 150}
    assert {p.name for p in videos.iterdir()} == {
        "line-10_20260925-101500.mp4",
        "line-2_20260925-101500.mp4",
        "line-1_catatan.txt",
    }


def test_folder_rekaman_belum_ada(tmp_path):
    assert ringkas_rekaman(tmp_path / "tidak-ada", "line-1") == {"berkas": 0, "bytes": 0}
    assert hapus_rekaman(tmp_path / "tidak-ada", "line-1") == {"berkas": 0, "bytes": 0}


@pytest.mark.parametrize("kode", ["", "../line-1", "line-1/x"])
def test_kode_line_aneh_ditolak(tmp_path, kode):
    """Kode line datang dari Settings, tapi dipakai membentuk pola hapus — yang
    kosong akan cocok dengan SEMUA rekaman, yang bergaris miring keluar folder."""
    _rekaman(tmp_path / "videos")
    with pytest.raises(ValueError):
        hapus_rekaman(tmp_path / "videos", kode)


# ── fix pass review 2026-09-25 ──────────────────────────────────────────────


def test_state_bersama_konsol_tidak_pernah_disentuh(tmp_path):
    """I-1: di jalur native `state/` dipakai konsol DAN line. Yang dihapus di
    sana cuma milik line (`upload_manifest.db*`) — basis data konsol yang
    sedang dibuka tidak boleh hilang dari bawahnya."""
    artifacts, state = _isi_line(tmp_path)
    for nama in ("console.db", "console.db-wal", "erp_outbox.db", "log_kejadian.db",
                 "manifest_outbox.db"):
        (state / nama).write_bytes(b"konsol")
    (state / "upload_manifest.db-wal").write_bytes(b"m")
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)

    hapus_kalau_diminta(artifacts, state)

    assert _sisa(state) == {
        "console.db", "console.db-wal", "erp_outbox.db", "log_kejadian.db", "manifest_outbox.db",
    }


def test_tiga_line_native_berbagi_state_masing_masing_tetap_terhapus(tmp_path):
    """Penanda per line (di artifacts), jadi line pertama yang boot tidak
    'memakan' perintah milik dua line lainnya."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "console.db").write_bytes(b"konsol")
    lines = []
    for n in (1, 2, 3):
        artifacts = tmp_path / "artifacts" / f"line-{n}"
        (artifacts / "results").mkdir(parents=True)
        (artifacts / "results" / "a.webp").write_bytes(b"w")
        (artifacts / "license.db").write_bytes(b"lic")
        tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)
        lines.append(artifacts)

    for artifacts in lines:
        hasil = hapus_kalau_diminta(artifacts, state)
        assert hasil is not None
        assert _sisa(artifacts) == {"license.db"}
    assert _sisa(state) == {"console.db"}


def test_penanda_disimpan_ke_disk_sebelum_line_keluar(tmp_path, monkeypatch):
    """M-7: listrik mati sedetik sesudah penanda ditulis tidak boleh
    menghilangkannya — konsol sudah mengosongkan index-nya saat itu."""
    disinkron: list[int] = []
    asli = hapus_data_line.os.fsync

    def catat(fd):
        disinkron.append(fd)
        return asli(fd)

    monkeypatch.setattr(hapus_data_line.os, "fsync", catat)
    tulis_penanda(tmp_path / "artifacts", mode="transaksi", diminta_oleh="s", now=1.0)

    assert len(disinkron) >= 1


def test_hapus_diminta_membaca_penanda(tmp_path):
    artifacts = tmp_path / "artifacts"
    assert hapus_diminta(artifacts) is False
    tulis_penanda(artifacts, mode="transaksi", diminta_oleh="s", now=1.0)
    assert hapus_diminta(artifacts) is True


def test_mulai_hapus_dicatat_sebelum_menghapus(tmp_path, caplog):
    """M-6: menghapus berbulan-bulan foto bisa makan menit, dan selama itu line
    terbaca mati. Baris log di awal yang menjelaskannya."""
    artifacts, state = _isi_line(tmp_path)
    tulis_penanda(artifacts, mode="semua", diminta_oleh="s@pks.id", now=1.0)

    with caplog.at_level("WARNING"):
        hapus_kalau_diminta(artifacts, state)

    assert any("mulai" in r.getMessage().lower() for r in caplog.records)



# ── penjaga: setiap berkas .db di state/ harus tergolong ────────────────────

_DB_KONSOL = {"console.db", "erp_outbox.db", "log_kejadian.db", "manifest_outbox.db"}


def test_semua_berkas_db_di_state_digolongkan():
    """Setiap `state_dir / "x.db"` di kode harus diputuskan pemiliknya.

    Milik line → dihapus line saat boot (`MILIK_LINE_DI_STATE`). Milik konsol →
    dikosongkan konsol lewat SQL (`BahayaService`), TIDAK PERNAH oleh line —
    di jalur native folder ini dipakai bersama. Berkas baru yang belum
    digolongkan membuat test ini merah, bukan diam-diam tertinggal atau
    terhapus dari bawah proses yang membukanya.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src/palmgrade"
    ditemukan = {
        m.group(1)
        for f in src.rglob("*.py")
        for m in re.finditer(r'state_dir / "([a-z_]+\.db)"', f.read_text())
    }
    milik_line = {n for n in ditemukan if n.startswith(MILIK_LINE_DI_STATE)}
    assert ditemukan - milik_line == _DB_KONSOL & ditemukan, ditemukan - milik_line - _DB_KONSOL
    assert milik_line == {"upload_manifest.db"}
