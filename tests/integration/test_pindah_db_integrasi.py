"""Integrasi pemindahan DB line: boot sungguhan urutannya hapus lalu serap.

Yang dirangkai tanpa tiruan: `OutboxStore`, `LicenseLocalRepo`,
`hapus_kalau_diminta`, `folder_db_line`, dan `pindahkan_db_lama` yang ASLI, di
atas berkas SQLite sungguhan. Yang tiruan cuma isi `/proc/self/mountinfo`.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.bahaya import MODE_TRANSAKSI
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.license.local_repo import LicenseLocalRepo
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services import pindah_db_line
from palmgrade.services.bahaya_service import BahayaDitolak, BahayaService
from palmgrade.services.hapus_data_line import hapus_kalau_diminta, tulis_penanda
from palmgrade.services.health_service import HealthService
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
    hapus_kalau_diminta(artifacts, folder_db, folder_db=folder_db)
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


# ── serapan yang gagal: terlihat, menahan Danger Zone, tidak terhapus ─────────

SECRET = "kunci-perintah-palsu"


def _serap_meledak(self, lama):
    raise MemoryError("antrean lama terlalu besar")


def _baris_di(berkas: Path) -> list[str]:
    db = sqlite3.connect(berkas)
    try:
        return sorted(r[0] for r in db.execute("SELECT event_id FROM outbox_events"))
    finally:
        db.close()


def _danger_zone(tmp_path, kesehatan: HealthService) -> BahayaService:
    """Konsol sungguhan membaca `/health/detail` line lewat HTTP (ASGI)."""
    line_app = FastAPI()

    @line_app.get("/health/detail")
    def detail() -> dict:
        return {"status": "ok", "current_assignment_id": None, **kesehatan.ringkasan_outbox()}

    konsol = tmp_path / "konsol"
    return BahayaService(
        ConsoleStore(konsol / "console.db"),
        LogStore(konsol / "log.db"),
        LineClient(
            replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
            transport=httpx.ASGITransport(app=line_app),
        ),
        (LineEndpoint("line-1", "Line 1", 8001, "m-1"),),
        ErpOutboxStore(konsol / "erp_outbox.db"),
        erp_aktif=False,
        hari_kerja=lambda: "2026-09-28",
        tunggu_mati_s=0.0,
    )


def test_serap_gagal_terlihat_menahan_danger_zone_dan_tidak_terhapus(tmp_path, monkeypatch):
    """Final review Important 1. Dulu: serapan gagal, `/health/detail` melapor 0,
    Danger Zone mengizinkan, dan boot berikutnya menghapus `artifacts/outbox.db`
    beserta janjang yang belum pernah sampai ke konsol."""
    settings = replace(Settings(), repo_root=tmp_path / "line-1")
    artifacts, state = settings.artifacts_dir, settings.state_dir
    _outbox(artifacts / "outbox.db", "e1", "e2")._db.close()
    _lisensi(artifacts / "license.db", 500)
    monkeypatch.setattr(OutboxStore, "serap", _serap_meledak)

    outbox, _ = _boot(artifacts, state)

    # 1. Terlihat: bukan nol palsu.
    kesehatan = HealthService(
        settings=settings, state=None, camera=None, outbox=outbox, folder_db=state
    )
    assert kesehatan.ringkasan_outbox() == {
        "outbox_pending": None, "outbox_failed": 0, "outbox_lama_tertinggal": True,
    }
    # 2. Danger Zone menahan dengan alasannya.
    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(_danger_zone(tmp_path, kesehatan).hapus_data(
            mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s@pks.id"
        ))
    assert exc.value.hambatan == [{"kode": "outbox_lama", "line": "line-1"}]

    # 3. Penanda tetap tertulis (mis. dari versi konsol lama), serapan masih
    #    gagal saat boot itu: berkas lama dan isinya tetap ada.
    outbox._db.close()
    tulis_penanda(artifacts, mode="semua", diminta_oleh="s@pks.id", now=1.0)
    outbox, _ = _boot(artifacts, state)
    outbox._db.close()
    assert _baris_di(artifacts / "outbox.db") == ["e1", "e2"]

    # 4. Boot sesudah penyebabnya beres: barisnya pindah, sisa hilang.
    monkeypatch.undo()
    outbox, _ = _boot(artifacts, state)
    assert _event_ids(outbox) == ["e1", "e2"]
    assert _db_tersisa(artifacts) == []
