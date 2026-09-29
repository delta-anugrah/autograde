"""Tulis berkas utuh-atau-tidak-sama-sekali (batch 2.6).

Yang paling penting dibuktikan: listrik padam di tengah tulisan TIDAK
meninggalkan berkas 0 byte dengan nama akhir. Dulu itulah yang terjadi pada
foto dan sidecar, lalu `BatchUploadWorker` mengunggahnya ke R2 dan retensi
menghapus aslinya. Padamnya ditiru dengan `os._exit` di subprocess (pola
`test_batch_upload_crash.py`): tanpa cleanup, tanpa `finally`.
"""
from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from palmgrade.domain.berkas_utuh import berkas_sementara
from palmgrade.integrations.storage.tulis_atomik import tulis_atomik

_REPO = Path(__file__).resolve().parents[2]

_PADAM_SAAT_GANTI_NAMA = """
import os, sys
from pathlib import Path
from palmgrade.integrations.storage.tulis_atomik import tulis_atomik

def padam(src, dst):
    os._exit(1)  # listrik padam: isi sudah di-fsync, nama akhir belum diganti

os.replace = padam
tulis_atomik(Path(sys.argv[1]), b"isi-foto-lengkap" * 1000)
"""


def _padamkan_saat_menulis(tujuan: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _PADAM_SAAT_GANTI_NAMA, str(tujuan)],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr


def test_menulis_isi_dan_tidak_meninggalkan_sementara(tmp_path):
    tujuan = tmp_path / "a.json"
    tulis_atomik(tujuan, b'{"ok": true}')
    assert tujuan.read_bytes() == b'{"ok": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_menimpa_berkas_lama_utuh(tmp_path):
    tujuan = tmp_path / "a.json"
    tujuan.write_bytes(b"lama")
    tulis_atomik(tujuan, b"baru")
    assert tujuan.read_bytes() == b"baru"


def test_membuat_folder_bertingkat(tmp_path):
    tujuan = tmp_path / "results" / "2026-09-28" / "truk" / "bbox" / "Ripe" / "x.webp"
    tulis_atomik(tujuan, b"webp")
    assert tujuan.read_bytes() == b"webp"


def test_padam_di_tengah_tulis_tidak_meninggalkan_berkas_kosong(tmp_path):
    """Review Focus 5."""
    tujuan = tmp_path / "2026-09-28_091432_123456_auto.webp"
    _padamkan_saat_menulis(tujuan)

    assert not tujuan.exists(), "nama akhir muncul walau tulisannya tidak pernah selesai"
    sisa = list(tmp_path.iterdir())
    assert len(sisa) == 1 and berkas_sementara(sisa[0].name)
    assert sisa[0].stat().st_size == len(b"isi-foto-lengkap") * 1000


def test_padam_saat_menimpa_menyisakan_isi_lama(tmp_path):
    tujuan = tmp_path / "a_ripeness.json"
    tujuan.write_bytes(b'{"lama": true}')
    _padamkan_saat_menulis(tujuan)
    assert tujuan.read_bytes() == b'{"lama": true}'


def test_gagal_menulis_membuang_sementara_dan_nama_akhir_tidak_berubah(tmp_path, monkeypatch):
    tujuan = tmp_path / "a.json"
    tujuan.write_bytes(b"lama")

    def disk_penuh(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_penuh)
    with pytest.raises(OSError):
        tulis_atomik(tujuan, b"baru")

    assert tujuan.read_bytes() == b"lama"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_izin_mengikuti_umask_bukan_0600(tmp_path):
    """Konsol (mount read-only) dan teknisi yang menyalin foto harus bisa membacanya.

    Baca umask di subprocess terpisah: `os.umask()` cuma bisa dibaca dengan
    menyetelnya, dan mengubah umask proses tes ini bisa membocor ke test lain
    yang jalan sesudahnya (state proses global, bukan per-test)."""
    umask = int(subprocess.run(
        [sys.executable, "-c", "import os; print(os.umask(0))"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())

    tujuan = tmp_path / "x.webp"
    tulis_atomik(tujuan, b"webp")
    assert stat.S_IMODE(tujuan.stat().st_mode) == 0o666 & ~umask


def test_gagal_fsync_lalu_gagal_bersihkan_sementara_tetap_lempar_galat_asli(tmp_path):
    """Review round 1, IMPORTANT 1.

    `fsync` gagal dengan errno tertentu, lalu `unlink` pembersihannya gagal
    dengan errno LAIN: pemanggil harus tetap menerima galat pertama (errno
    disk penuh), bukan galat kedua (errno pembersihan). Kalau tertukar, disk
    yang remount read-only tercatat dengan sebab yang salah, dan Task 8
    (media_env fallback) yang membaca errno EBUSY/EXDEV/EINVAL jadi salah
    baca."""
    from unittest.mock import patch

    with patch("os.fsync", side_effect=OSError(errno.ENOSPC, "disk penuh")), \
         patch.object(Path, "unlink", side_effect=OSError(errno.EROFS, "read-only")), \
         patch("os.replace") as replace_mock:
        with pytest.raises(OSError) as exc:
            tulis_atomik(tmp_path / "a.json", b"isi")

    assert exc.value.errno == errno.ENOSPC
    replace_mock.assert_not_called()


def test_keyboard_interrupt_saat_gagal_bersihkan_sementara_tetap_lempar_keyboard_interrupt(tmp_path):
    """Review round 1, IMPORTANT 1, kasus kedua.

    `KeyboardInterrupt` (bukan `OSError`) tidak boleh berubah jadi `OSError`
    hanya karena pembersihan sementara ikut gagal: `KeyboardInterrupt`/
    `SystemExit` yang berubah jadi `OSError` bisa tertelan pemanggil yang
    cuma menangkap `OSError`."""
    from unittest.mock import patch

    with patch("os.fsync", side_effect=KeyboardInterrupt), \
         patch.object(Path, "unlink", side_effect=OSError(errno.EROFS, "read-only")):
        with pytest.raises(KeyboardInterrupt):
            tulis_atomik(tmp_path / "a.json", b"isi")


def test_tabrakan_nama_sementara_tidak_menghapus_punya_penulis_lain(tmp_path, monkeypatch):
    """Review round 1, MINOR 1.

    Kalau `os.open(..., O_EXCL)` gagal `FileExistsError` (nama sementara kita
    kebetulan sama dengan punya penulis lain yang sedang menulis), pembersihan
    tidak boleh menghapus berkas MILIK PENULIS LAIN itu: kita belum pernah
    berhasil membuatnya, jadi bukan milik kita untuk dihapus."""
    punya_penulis_lain = tmp_path / ".x.webp.aaaaaaaa.tmp"
    punya_penulis_lain.write_bytes(b"punya orang lain, sedang ditulis")

    asli_open = os.open

    def open_selalu_kolisi(path, flags, mode=0o777):
        if str(path) == str(punya_penulis_lain):
            raise FileExistsError(errno.EEXIST, "File exists")
        return asli_open(path, flags, mode)

    monkeypatch.setattr(
        "palmgrade.integrations.storage.tulis_atomik.secrets.token_hex",
        lambda n: "aaaaaaaa",
    )
    monkeypatch.setattr(os, "open", open_selalu_kolisi)

    with pytest.raises(FileExistsError):
        tulis_atomik(tmp_path / "x.webp", b"isi kita")

    assert punya_penulis_lain.read_bytes() == b"punya orang lain, sedang ditulis"


def test_fsync_folder_error_lain_dicatat_tapi_tidak_melempar(tmp_path, monkeypatch, caplog):
    """Review round 1, MINOR 2.

    EINVAL/ENOTSUP/EOPNOTSUPP/EBADF/EACCES adalah cara filesystem menolak
    fsync folder, itu diam-diam diabaikan. Errno LAIN (mis. EIO, disk
    bermasalah) dicatat WARNING menyebut foldernya, tapi tidak melempar:
    berkasnya sudah dapat nama akhirnya, jadi menggagalkan seluruh operasi di
    titik ini cuma menyembunyikan fakta bahwa isinya sudah aman."""
    import logging

    asli_fsync = os.fsync

    tujuan = tmp_path / "a.json"

    def fsync_folder_saja_eio(fd):
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise OSError(errno.EIO, "I/O error")
        return asli_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync_folder_saja_eio)
    with caplog.at_level(logging.WARNING):
        tulis_atomik(tujuan, b"isi")

    assert tujuan.read_bytes() == b"isi"
    peringatan = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any(str(tmp_path) in rec.message and "EIO" in rec.message for rec in peringatan) \
        or any(str(tmp_path) in rec.message and str(errno.EIO) in rec.message for rec in peringatan)


def test_fsync_folder_errno_diabaikan_tidak_mencatat_apa_pun(tmp_path, monkeypatch, caplog):
    """Review round 2, MINOR 2, kasus negatif.

    EINVAL adalah salah satu errno yang berarti filesystem ini menolak fsync
    folder sama sekali, itu perilaku normal (bukan sinyal ada yang salah):
    tidak boleh mencatat apa pun, supaya WARNING benar-benar berarti sesuatu
    yang perlu dilihat, bukan noise yang muncul di setiap filesystem yang
    menolaknya."""
    import logging

    asli_fsync = os.fsync

    tujuan = tmp_path / "a.json"

    def fsync_folder_saja_einval(fd):
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise OSError(errno.EINVAL, "Invalid argument")
        return asli_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync_folder_saja_einval)
    with caplog.at_level(logging.WARNING):
        tulis_atomik(tujuan, b"isi")

    assert tujuan.read_bytes() == b"isi"
    assert caplog.records == []


def test_fsync_folder_gagal_membuka_errno_tak_terduga_dicatat_tapi_tidak_melempar(
    tmp_path, monkeypatch, caplog
):
    """Review round 2, MINOR 3.

    `_fsync_folder` membuka foldernya dulu (`os.open(folder, os.O_RDONLY)`)
    sebelum bisa `fsync`. Cabang itu dulu selalu pulang diam-diam untuk
    `OSError` apa pun (`return` tanpa mencatat), padahal errno tak terduga di
    sini (mis. EMFILE karena kehabisan file descriptor, atau EIO) sama
    pentingnya untuk dilihat dengan errno tak terduga di cabang `fsync` itu
    sendiri. Tidak boleh melempar: berkasnya sudah dapat nama akhirnya lewat
    `os.replace` sebelum titik ini dipanggil."""
    import logging

    asli_open = os.open

    tujuan = tmp_path / "a.json"

    def open_folder_saja_emfile(path, flags, mode=0o777):
        if Path(path) == tmp_path and flags == os.O_RDONLY:
            raise OSError(errno.EMFILE, "Too many open files")
        return asli_open(path, flags, mode)

    monkeypatch.setattr(os, "open", open_folder_saja_emfile)
    with caplog.at_level(logging.WARNING):
        tulis_atomik(tujuan, b"isi")

    assert tujuan.read_bytes() == b"isi"
    peringatan = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any(str(tmp_path) in rec.message and str(errno.EMFILE) in rec.message
               for rec in peringatan)


def test_fsync_folder_gagal_membuka_errno_diabaikan_tidak_mencatat_apa_pun(
    tmp_path, monkeypatch, caplog
):
    """Review round 2, MINOR 3, kasus negatif.

    EACCES saat membuka foldernya untuk fsync adalah cara sebagian
    filesystem/sandbox menolak, sama seperti errno yang diabaikan saat fsync
    itu sendiri berhasil dibuka: tidak boleh mencatat apa pun."""
    import logging

    asli_open = os.open

    tujuan = tmp_path / "a.json"

    def open_folder_saja_eacces(path, flags, mode=0o777):
        if Path(path) == tmp_path and flags == os.O_RDONLY:
            raise OSError(errno.EACCES, "Permission denied")
        return asli_open(path, flags, mode)

    monkeypatch.setattr(os, "open", open_folder_saja_eacces)
    with caplog.at_level(logging.WARNING):
        tulis_atomik(tujuan, b"isi")

    assert tujuan.read_bytes() == b"isi"
    assert caplog.records == []
