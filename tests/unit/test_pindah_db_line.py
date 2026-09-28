"""Folder DB line (state/) dan penyerapan sekali jalan dari artifacts/ (batch 1.2)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palmgrade.services import pindah_db_line
from palmgrade.services.pindah_db_line import ada_mount, folder_db_line, pindahkan_db_lama

AKAR_CONTAINER = "790 1 0:50 / / rw,relatime - overlay overlay rw,lowerdir=/x\n"
MOUNT_STATE = "812 790 8:2 /opt/palmgrade/autograde/state/line-1 /app/state rw,relatime - ext4 /dev/sda2 rw\n"
MOUNT_LAIN = "811 790 8:2 /opt/palmgrade/autograde/artifacts/line-1 /app/artifacts rw - ext4 /dev/sda2 rw\n"
MOUNT_REPO = "813 790 8:2 /home/dev/autograde /app rw,relatime - ext4 /dev/sda2 rw\n"


def test_ada_mount_membaca_kolom_titik_mount():
    assert ada_mount(MOUNT_STATE, Path("/app/state")) is True
    assert ada_mount(MOUNT_LAIN, Path("/app/state")) is False
    assert ada_mount("1 2 3:4 / /app/a\\040b rw - x y rw\n", Path("/app/a b")) is True


def test_akar_overlay_container_bukan_mount_host():
    """`/` selalu ada di mountinfo container; itu lapisan yang dibuang saat
    container dibuat ulang, jadi tidak dihitung."""
    assert ada_mount(AKAR_CONTAINER + MOUNT_LAIN, Path("/app/state")) is False
    assert ada_mount(AKAR_CONTAINER + MOUNT_STATE + MOUNT_LAIN, Path("/app/state")) is True


def test_folder_di_dalam_mount_host_yang_lebih_luas_ikut_tersimpan():
    """Compose dev me-mount seluruh repo `.:/app`: `/app/state` ada di host walau
    bukan titik mount sendiri."""
    assert ada_mount(AKAR_CONTAINER + MOUNT_REPO, Path("/app/state")) is True
    assert ada_mount(AKAR_CONTAINER + MOUNT_REPO, Path("/application")) is False


def test_escape_oktal_lain_di_mountinfo():
    assert ada_mount("1 2 3:4 / /data\\011x\\134y rw - x y rw\n", Path("/data\tx\\y")) is True


def test_mountinfo_linux_sungguhan_kalau_ada():
    """Di Linux, `/proc/self/mountinfo` asli harus terbaca dan `/` selalu ada."""
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        pytest.skip("bukan Linux: tidak ada /proc/self/mountinfo")
    assert ada_mount(mountinfo.read_text(), Path("/")) is False
    assert any(len(b.split()) > 4 for b in mountinfo.read_text().splitlines())


def test_di_luar_container_selalu_state(tmp_path):
    assert folder_db_line(tmp_path / "a", tmp_path / "s", di_container=False) == tmp_path / "s"


def test_container_dengan_mount_state(tmp_path):
    assert folder_db_line(Path("/app/artifacts"), Path("/app/state"), di_container=True, mountinfo=MOUNT_STATE) == Path("/app/state")


def test_container_tanpa_mount_state_tetap_di_artifacts(caplog):
    """Review Focus 2: compose host tanpa ./state/line-N berarti /app/state hilang tiap restart."""
    with caplog.at_level("ERROR"):
        hasil = folder_db_line(Path("/app/artifacts"), Path("/app/state"), di_container=True, mountinfo=MOUNT_LAIN)
    assert hasil == Path("/app/artifacts")
    assert any("/app/state" in r.getMessage() for r in caplog.records)


def test_container_dikenali_dari_dockerenv(monkeypatch, tmp_path):
    penanda = tmp_path / ".dockerenv"
    monkeypatch.setattr(pindah_db_line, "_PENANDA_DOCKER", penanda)
    tanpa_mount = AKAR_CONTAINER + MOUNT_LAIN

    assert folder_db_line(Path("/app/artifacts"), Path("/app/state"), mountinfo=tanpa_mount) == Path("/app/state")
    penanda.write_text("")
    assert folder_db_line(Path("/app/artifacts"), Path("/app/state"), mountinfo=tanpa_mount) == Path("/app/artifacts")


class _Outbox:
    def __init__(self, gagal: bool = False) -> None:
        self.gagal = gagal
        self.diserap: list[Path] = []

    def serap(self, lama: Path) -> int:
        if self.gagal:
            raise RuntimeError("rusak")
        self.diserap.append(lama)
        return 3


class _Lisensi:
    def __init__(self) -> None:
        self.diserap: list[Path] = []

    async def serap(self, lama: Path) -> int:
        self.diserap.append(lama)
        return 1


@pytest.fixture
def lama(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for nama in ("outbox.db", "outbox.db-wal", "outbox.db-shm", "license.db"):
        (artifacts / nama).write_bytes(b"x")
    (tmp_path / "state").mkdir()
    return artifacts, tmp_path / "state"


def test_pindah_lalu_hapus_berkas_lama_beserta_pendamping(lama):
    artifacts, state = lama
    hasil = asyncio.run(pindahkan_db_lama(artifacts, state, outbox=_Outbox(), lisensi=_Lisensi()))
    assert hasil == {"outbox.db": "dipindah", "license.db": "dipindah"}
    assert list(artifacts.iterdir()) == []


def test_pendamping_dihapus_sebelum_berkas_utama(lama, monkeypatch):
    """`-wal` yang tertinggal sendirian bisa diputar ulang SQLite ke `outbox.db`
    baru yang dibuat versi lama sesudah rollback. Berkas utama yang tertinggal
    sendirian tidak berbahaya: boot berikutnya menyerapnya lagi tanpa ganda."""
    artifacts, state = lama
    urutan: list[str] = []
    asli = Path.unlink

    def catat(self, missing_ok=False):
        urutan.append(self.name)
        return asli(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", catat)
    asyncio.run(pindahkan_db_lama(artifacts, state, outbox=_Outbox(), lisensi=_Lisensi()))

    outbox = [n for n in urutan if n.startswith("outbox.db")]
    assert outbox[-1] == "outbox.db"
    assert set(outbox[:-1]) == {"outbox.db-wal", "outbox.db-shm", "outbox.db-journal"}


def test_gagal_serap_membiarkan_berkas_lama_dan_tidak_melempar(lama):
    artifacts, state = lama
    hasil = asyncio.run(pindahkan_db_lama(artifacts, state, outbox=_Outbox(gagal=True), lisensi=_Lisensi()))
    assert hasil["outbox.db"] == "gagal"
    assert (artifacts / "outbox.db").exists()
    assert (artifacts / "outbox.db-wal").exists()
    assert hasil["license.db"] == "dipindah"


def test_tidak_ada_berkas_lama(tmp_path):
    (tmp_path / "a").mkdir()
    hasil = asyncio.run(pindahkan_db_lama(tmp_path / "a", tmp_path / "s", outbox=_Outbox(), lisensi=_Lisensi()))
    assert hasil == {"outbox.db": "tidak_ada", "license.db": "tidak_ada"}


def test_folder_db_sama_dengan_artifacts_tidak_menyentuh_apa_pun(lama):
    artifacts, _ = lama
    outbox = _Outbox()
    hasil = asyncio.run(pindahkan_db_lama(artifacts, artifacts, outbox=outbox, lisensi=_Lisensi()))
    assert hasil == {"outbox.db": "tetap", "license.db": "tetap"}
    assert outbox.diserap == [] and (artifacts / "outbox.db").exists()
