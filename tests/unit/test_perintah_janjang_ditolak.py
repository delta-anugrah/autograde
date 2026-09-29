"""Perintah tangan di MANUAL §7.1 dan skill `compose-host-pabrik` benar-benar jalan.

Teknisi mengetiknya lewat AnyDesk di PC pabrik tanpa source code, satu-satunya jalan
mengeluarkan janjang yang ditolak konsol (CLAUDE.md aturan 31). Perintah yang salah
kutip atau salah nama kolom baru ketahuan di pabrik, jadi di sini kode Python di
dalam `python -c '...'` diambil dari dokumen apa adanya dan dijalankan lawan berkas
`OutboxStore` sungguhan (dan berkas versi lama untuk pemeriksaan sebelum update).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from antrean_line_rakit import berkas_outbox_versi_lama

from palmgrade.integrations.outbox.outbox_store import OutboxStore

REPO = Path(__file__).resolve().parents[2]
MANUAL = (REPO / "docs/MANUAL.md").read_text()
SKILL = (REPO / ".claude/skills/compose-host-pabrik/SKILL.md").read_text()
TS = "2026-09-20T03:00:00+00:00"


def _perintah(teks: str) -> list[str]:
    """Kode `python -c '...'` di semua blok bash yang menyentuh `outbox_events`."""
    kode = []
    for blok in re.findall(r"```bash\n(.*?)```", teks, re.S):
        if "outbox_events" in blok:
            kode += re.findall(r"python -c '([^']*)'", blok)
    return kode


def _bagian_71() -> str:
    return MANUAL.split("### 7.1 ", 1)[1].split("\n## ", 1)[0]


LIHAT, SIMPAN, HAPUS = _perintah(_bagian_71())


def _jalankan(kode: str, jalur: Path, *arg: str) -> subprocess.CompletedProcess:
    kode = kode.replace("/app/state/outbox.db", str(jalur)).replace("/app/artifacts/outbox.db", "/tidak/ada")
    return subprocess.run([sys.executable, "-c", kode, *arg], capture_output=True, text=True, timeout=30)


@pytest.fixture
def berkas(tmp_path) -> Path:
    """Satu line: `rusak` ditolak konsol, `mati` gagal karena konsol mati, `baru` belum dicoba."""
    jalur = tmp_path / "outbox.db"
    store = OutboxStore(jalur)
    for eid in ("rusak", "mati", "baru"):
        store.add_event(eid, "m-1", {"event_id": eid, "timestamp": TS})
    baris = {r["event_id"]: r["id"] for r in store.get_pending()}
    store.mark_failed_attempt(baris["rusak"], "HTTP 400: timestamp cacat", ditolak=True)
    store.mark_failed_attempt(baris["mati"], "ConnectError: refused")
    return jalur


def _sisa(jalur: Path) -> list[str]:
    return sorted(r["event_id"] for r in OutboxStore(jalur)._db.execute("SELECT event_id FROM outbox_events"))


def test_perintah_ada_di_manual_dan_skill_dengan_teks_yang_sama():
    assert all((LIHAT, SIMPAN, HAPUS))
    for kode in (LIHAT, SIMPAN, HAPUS):
        assert kode in _perintah(SKILL), "salinan di skill compose-host-pabrik berbeda dari MANUAL §7.1"


def test_lihat_menyebut_hanya_yang_ditolak(berkas):
    hasil = _jalankan(LIHAT, berkas)

    assert hasil.returncode == 0, hasil.stderr
    [baris] = [b for b in hasil.stdout.splitlines() if " | " in b]
    assert baris.startswith("rusak | " + TS)
    assert baris.endswith("HTTP 400: timestamp cacat")


def test_simpan_lalu_hapus_satu_baris_ditolak(berkas):
    simpan = _jalankan(SIMPAN, berkas, "rusak")
    assert simpan.returncode == 0, simpan.stderr
    isi = json.loads(simpan.stdout)
    assert (isi["event_id"], json.loads(isi["payload"])["timestamp"]) == ("rusak", TS)

    hapus = _jalankan(HAPUS, berkas, "rusak")

    assert hapus.stdout.strip() == "1 baris dihapus"
    assert _sisa(berkas) == ["baru", "mati"]


@pytest.mark.parametrize("event_id", ["mati", "baru", "salah-ketik"])
def test_baris_yang_tidak_ditolak_tidak_tersimpan_dan_tidak_terhapus(berkas, event_id):
    simpan = _jalankan(SIMPAN, berkas, event_id)
    hapus = _jalankan(HAPUS, berkas, event_id)

    assert simpan.returncode != 0 and simpan.stdout == ""
    assert "tidak ada baris ditolak" in simpan.stderr
    assert hapus.stdout.strip() == "0 baris dihapus"
    assert _sisa(berkas) == ["baru", "mati", "rusak"]


def test_pemeriksaan_sebelum_update_jalan_di_berkas_versi_lama(tmp_path):
    """Skill `compose-host-pabrik`, urutan pasang batch 2 langkah 1: dijalankan SEBELUM
    tag, jadi berkasnya masih skema versi lama (tanpa `dibuat_at`, masih ada `failed`)."""
    [cek] = [k for k in _perintah(SKILL) if "group by status" in k]
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [
        ("e1", "failed", 50, json.dumps({"timestamp": "2026-09-01T03:00:00+00:00"})),
        ("e2", "failed", 50, json.dumps({"timestamp": TS})),
        ("e3", "pending", 2, json.dumps({"timestamp": TS})),
    ])

    hasil = _jalankan(cek, jalur)

    assert hasil.returncode == 0, hasil.stderr
    assert "('failed', 2, '2026-09-01T03:00:00+00:00', '2026-09-20T03:00:00+00:00')" in hasil.stdout
    assert "('pending', 1, " in hasil.stdout
