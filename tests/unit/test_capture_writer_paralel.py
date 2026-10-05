"""`CaptureWriter.write_pair` writes the clean copy beside the evidence copy (batch 6.2).

One bunch is two full-size WebP encodes (`bbox/` and `clean/`) plus a thumbnail. The two big
ones used to run one after the other on the writer thread; cv2 releases the GIL while it
encodes, so a second thread halves the wait.

What must stay as it was, and is pinned here:

* rule 8: the evidence copy failing raises `OSError`, and then NOTHING of that bunch stays
  on disk: no clean copy without its evidence copy, no thumbnail;
* a failing clean copy or thumbnail is logged and never fails the bunch;
* rule 9: a saved bunch has its three variants.

The storage below writes real (tiny) files so "what is left on disk" is checked on disk.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from palmgrade.core.config import Settings
from palmgrade.services import capture_writer
from palmgrade.services.capture_writer import CaptureWriter

DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"
NAMA = "2026-09-08_021432_781225_auto.webp"
BATAS_TUNGGU_S = 5.0


class PenyimpanBerkas:
    """Writes the frame (bytes here) to the path, like the real storage but without cv2.

    `gagal` names the variants (`bbox`, `clean`, `thumb`) whose write raises; `bersama` makes
    the two full-size writes wait for each other, which only works if they overlap.
    """

    def __init__(self, *, gagal: set[str] = frozenset(), galat: type[Exception] = OSError,
                 bersama: threading.Barrier | None = None) -> None:
        self.gagal = set(gagal)
        self.galat = galat
        self.bersama = bersama
        self.thread: dict[str, str] = {}

    def _varian(self, path: Path) -> str:
        return next(v for v in ("bbox", "clean", "thumb") if v in path.parts)

    def write_image(self, path: Path, frame, quality: int = 80) -> None:
        varian = self._varian(path)
        self.thread[varian] = threading.current_thread().name
        if self.bersama is not None and varian != "thumb":
            self.bersama.wait(timeout=BATAS_TUNGGU_S)
        if varian in self.gagal:
            raise self.galat(f"disk menolak {varian}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(frame)

    def write_thumbnail(self, path: Path, frame, *, max_width: int, quality: int) -> None:
        self.write_image(path, frame, quality)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")


def _tulis(settings: Settings, storage: PenyimpanBerkas) -> str:
    return CaptureWriter(settings, storage).write_pair(
        date_folder=DAY, truck_folder=TRUCK, grade_class="Ripe", filename=NAMA,
        annotated_frame=b"bergambar-kotak", clean_frame=b"polos",
    )


def _di_disk(settings: Settings) -> set[str]:
    akar = settings.results_dir
    return {str(p.relative_to(akar / DAY / TRUCK)) for p in akar.rglob("*") if p.is_file()}


def test_salinan_bukti_dan_salinan_clean_ditulis_bersamaan(settings):
    """Each full-size write waits for the other inside the storage. Written one after the
    other, the first would wait alone until the barrier breaks."""
    storage = PenyimpanBerkas(bersama=threading.Barrier(2))

    _tulis(settings, storage)

    assert storage.thread["bbox"] != storage.thread["clean"]
    assert storage.thread["bbox"] == threading.current_thread().name, (
        "the evidence copy must stay on the calling thread: its failure is the one that raises"
    )


def test_janjang_tersimpan_punya_tiga_varian(settings):
    tautan = _tulis(settings, PenyimpanBerkas())

    assert _di_disk(settings) == {f"bbox/Ripe/{NAMA}", f"clean/Ripe/{NAMA}", f"thumb/Ripe/{NAMA}"}
    assert tautan == f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{NAMA}"
    assert (settings.results_dir / DAY / TRUCK / "clean" / "Ripe" / NAMA).read_bytes() == b"polos"


def test_salinan_bukti_gagal_melempar_oserror_dan_tidak_menyisakan_apa_pun(settings):
    """Rule 8. The clean copy is already being written when the evidence copy fails, so it is
    taken back: a clean copy has no manifest row of its own, and one without its evidence
    copy would never be deleted by retention."""
    storage = PenyimpanBerkas(gagal={"bbox"})

    with pytest.raises(OSError, match="bbox"):
        _tulis(settings, storage)

    assert _di_disk(settings) == set(), "something of a bunch with no evidence copy stayed on disk"
    assert "thumb" not in storage.thread, "a thumbnail was attempted for a bunch that failed"


def test_salinan_clean_gagal_hanya_dicatat(settings, caplog):
    storage = PenyimpanBerkas(gagal={"clean"})

    with caplog.at_level(logging.ERROR, logger=capture_writer.__name__):
        tautan = _tulis(settings, storage)

    assert tautan.endswith(f"bbox/Ripe/{NAMA}")
    assert _di_disk(settings) == {f"bbox/Ripe/{NAMA}", f"thumb/Ripe/{NAMA}"}
    assert any("Clean capture copy failed" in r.getMessage() for r in caplog.records)


def test_thumbnail_gagal_hanya_dicatat(settings, caplog):
    with caplog.at_level(logging.ERROR, logger=capture_writer.__name__):
        _tulis(settings, PenyimpanBerkas(gagal={"thumb"}))

    assert _di_disk(settings) == {f"bbox/Ripe/{NAMA}", f"clean/Ripe/{NAMA}"}
    assert any("Thumbnail failed" in r.getMessage() for r in caplog.records)


def test_galat_tak_terduga_di_salinan_clean_tetap_sampai_ke_pemanggil(settings):
    """Only `OSError` is the expected, logged failure. Anything else in the helper thread must
    not vanish with the thread: the writer logs it with the bunch, as before."""
    storage = PenyimpanBerkas(gagal={"clean"}, galat=ValueError)

    with pytest.raises(ValueError, match="clean"):
        _tulis(settings, storage)


def test_tidak_ada_thread_pembantu_yang_tertinggal(settings):
    sebelum = {t.ident for t in threading.enumerate()}

    for _ in range(5):
        _tulis(settings, PenyimpanBerkas())

    assert {t.ident for t in threading.enumerate() if t.is_alive()} <= sebelum


def test_dua_gagal_sekaligus_tetap_oserror_dari_salinan_bukti(settings):
    with pytest.raises(OSError, match="bbox"):
        _tulis(settings, PenyimpanBerkas(gagal={"bbox", "clean"}))

    assert _di_disk(settings) == set()
