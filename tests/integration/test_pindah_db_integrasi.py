"""Integrasi pemindahan DB line: boot sungguhan urutannya hapus lalu serap.

Yang dirangkai tanpa tiruan: `OutboxStore`, `LicenseLocalRepo`,
`hapus_kalau_diminta`, `folder_db_line`, dan `pindahkan_db_lama` yang ASLI, di
atas berkas SQLite sungguhan. Yang tiruan cuma isi `/proc/self/mountinfo`.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.license.local_repo import LicenseLocalRepo
from palmgrade.services import pindah_db_line
from palmgrade.services.hapus_data_line import hapus_kalau_diminta, tulis_penanda
from palmgrade.services.pindah_db_line import folder_db_line, pindahkan_db_lama


def _outbox(path, *eids):
    store = OutboxStore(path)
    for eid in eids:
        store.add_event(eid, "m-1", {"event_id": eid})
    return store


def _lisensi(path, nilai):
    repo = LicenseLocalRepo(path)
    asyncio.run(repo.init())
    asyncio.run(repo.ratchet(nilai))
    return repo


def _boot(artifacts, folder_db):
    """Yang dijalankan awal lifespan main.py, dalam urutan yang sama."""
    hapus_kalau_diminta(artifacts, folder_db)
    outbox = OutboxStore(folder_db / "outbox.db")
    lisensi = LicenseLocalRepo(folder_db / "license.db")
    asyncio.run(pindahkan_db_lama(artifacts, folder_db, outbox=outbox, lisensi=lisensi))
    return outbox, lisensi


def _event_ids(outbox: OutboxStore) -> list[str]:
    return sorted(r["event_id"] for r in outbox._db.execute("SELECT event_id FROM outbox_events"))


def _db_tersisa(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if ".db" in p.name)


def test_upgrade_pc_lama_tanpa_kehilangan_antrean(tmp_path):
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _outbox(artifacts / "outbox.db", "e1", "e2")._db.close()
    _lisensi(artifacts / "license.db", 2_000_000_000)

    outbox, lisensi = _boot(artifacts, state)

    assert outbox.pending_count() == 2
    assert asyncio.run(lisensi.read_max_seen()) == 2_000_000_000
    assert _db_tersisa(artifacts) == []


def test_rollback_lalu_upgrade_lagi_menggabungkan_dua_berkas(tmp_path):
    """Review Focus 1: dua berkas sama-sama berisi, keduanya utuh, tanpa ganda."""
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _outbox(state / "outbox.db", "a", "c")._db.close()
    _lisensi(state / "license.db", 100)
    _outbox(artifacts / "outbox.db", "a", "b")._db.close()
    _lisensi(artifacts / "license.db", 200)

    outbox, lisensi = _boot(artifacts, state)

    assert _event_ids(outbox) == ["a", "b", "c"]
    assert asyncio.run(lisensi.read_max_seen()) == 200
    assert _db_tersisa(artifacts) == []


def test_rollback_penanda_jam_state_yang_lebih_tinggi_bertahan(tmp_path):
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _lisensi(state / "license.db", 300)
    _lisensi(artifacts / "license.db", 200)

    _, lisensi = _boot(artifacts, state)

    assert asyncio.run(lisensi.read_max_seen()) == 300


def test_listrik_mati_sesudah_serap_sebelum_hapus_tidak_menggandakan(tmp_path, monkeypatch):
    """Boot pertama menyerap lalu mati sebelum berkas lama terhapus. Boot kedua
    menyerap lagi: barisnya tetap satu, lalu berkas lama hilang."""
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _outbox(artifacts / "outbox.db", "e1", "e2")._db.close()
    _lisensi(artifacts / "license.db", 700)
    monkeypatch.setattr(pindah_db_line, "_hapus_bersama_pendamping", lambda lama: None)
    outbox, _ = _boot(artifacts, state)
    outbox._db.close()
    assert _db_tersisa(artifacts) == ["license.db", "outbox.db"]
    monkeypatch.undo()

    outbox, lisensi = _boot(artifacts, state)

    assert _event_ids(outbox) == ["e1", "e2"]
    assert asyncio.run(lisensi.read_max_seen()) == 700
    assert _db_tersisa(artifacts) == []


def test_baris_di_wal_proses_lama_yang_mati_ikut_pindah(tmp_path):
    """Salinan tiga berkas saat line lama mati: baris masih di `-wal`."""
    hidup, artifacts, state = tmp_path / "hidup", tmp_path / "artifacts", tmp_path / "state"
    lama = OutboxStore(hidup / "outbox.db")
    lama._db.execute("PRAGMA wal_autocheckpoint=0")
    for eid in ("w1", "w2"):
        lama.add_event(eid, "m-1", {"event_id": eid})
    artifacts.mkdir()
    for nama in ("outbox.db", "outbox.db-wal", "outbox.db-shm"):
        shutil.copy2(hidup / nama, artifacts / nama)
    lama._db.close()

    outbox, _ = _boot(artifacts, state)

    assert _event_ids(outbox) == ["w1", "w2"]
    assert _db_tersisa(artifacts) == []


def test_danger_zone_sesudah_pindah_menyisakan_lisensi(tmp_path):
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _outbox(artifacts / "outbox.db", "e1")._db.close()
    _lisensi(artifacts / "license.db", 300)
    outbox, _ = _boot(artifacts, state)
    outbox._db.close()
    tulis_penanda(artifacts, mode="semua", diminta_oleh="s@pks.id", now=1.0)

    outbox, lisensi = _boot(artifacts, state)

    assert outbox.pending_count() == 0
    assert asyncio.run(lisensi.read_max_seen()) == 300


def test_container_tanpa_mount_state_db_tetap_di_artifacts(tmp_path):
    """Review Focus 2: compose host lama tanpa `./state/line-N`. Antrean dan
    penanda jam tidak dipindah ke lapisan container yang dibuang saat dibuat ulang."""
    artifacts, state = tmp_path / "artifacts", tmp_path / "state"
    _outbox(artifacts / "outbox.db", "e1", "e2")._db.close()
    _lisensi(artifacts / "license.db", 900)
    mountinfo = f"1 0 0:1 / / rw - overlay overlay rw\n2 1 8:2 /x {artifacts} rw - ext4 /dev/sda2 rw\n"

    folder = folder_db_line(artifacts, state, di_container=True, mountinfo=mountinfo)
    outbox, lisensi = _boot(artifacts, folder)

    assert folder == artifacts
    assert _event_ids(outbox) == ["e1", "e2"]
    assert asyncio.run(lisensi.read_max_seen()) == 900
    assert not state.exists()
