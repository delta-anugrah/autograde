"""Rekam frame kamera ke MP4, untuk developer menelusuri masalah line.

**Aturan yang tidak boleh dilanggar: grading tidak pernah melambat karena modul
ini.** `tulis()` dipanggil dari thread capture setiap frame dan HARUS kembali
seketika. Kalau encoder ketinggalan, yang dikorbankan videonya (bolong), bukan
deteksinya. Ini pelajaran dari autograde#112: encode WebP 2448x2048 sinkron di
thread deteksi memakan ~590 ms per janjang dan terbaca operator sebagai "ngelag
1 detik".

Frame yang direkam diambil di `FrameCaptureWorker`, jadi **clean tanpa bbox**
tanpa kerja tambahan — bbox digambar jauh setelah titik itu.

Rekaman berhenti sendiri kalau disk menipis. Disk penuh berarti grading berhenti
menulis, yaitu pabrik berhenti — fitur developer tidak boleh bisa menyebabkan
itu.
"""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..domain.setelan_rekam import bersihkan_setelan_rekam

logger = logging.getLogger(__name__)

#: Berapa sering encoder memeriksa sisa disk, dalam frame. Memeriksa tiap frame
#: memanggil statvfs puluhan kali per detik tanpa guna.
_PERIKSA_DISK_TIAP = 50

#: Codec, urut dari yang paling hemat. `avc1` (H.264) diukur **5x lebih kecil**
#: dari `mp4v` pada 1280x1024 @ 5 fps — 0,48 vs 2,40 GB/jam pada noise acak,
#: yang merupakan kasus TERBURUK (conveyor dengan latar diam jauh lebih kecil).
#: `mp4v` tetap dicoba sesudahnya karena ada di setiap build OpenCV: kalau
#: build di PC pabrik ternyata tanpa H.264, rekaman tetap jadi — lebih besar,
#: bukan gagal senyap.
_CODEC = ("avc1", "mp4v")


class RekamSedangJalan(RuntimeError):
    """Diminta mulai padahal line ini sudah merekam."""


class RekamTidakJalan(RuntimeError):
    """Diminta stop padahal tidak ada rekaman."""


class DiskMepet(RuntimeError):
    """Sisa disk di bawah ambang — rekaman tidak dimulai / dihentikan."""


class VideoRecorder:
    """Satu recorder per line. Aman dipanggil dari beberapa thread."""

    def __init__(
        self,
        videos_dir: Path | str,
        line_code: str,
        *,
        disk_min_free_gb: float = 20.0,
        ukuran_antrean: int = 30,
    ) -> None:
        self._videos_dir = Path(videos_dir)
        self._line_code = line_code
        self._disk_min_free_gb = disk_min_free_gb
        self._ukuran_antrean = ukuran_antrean

        self._lock = threading.Lock()
        self._antrean: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._berhenti = threading.Event()

        self._merekam = False
        self._berkas: str | None = None
        self._mulai_epoch: float | None = None
        self._setelan: dict[str, int] | None = None
        self._frame_ditulis = 0
        self._frame_dibuang = 0
        self._alasan_berhenti: str | None = None
        self._codec: str | None = None

        #: Hanya untuk test: menahan encoder supaya antrean bisa dibuat penuh.
        self._jeda_uji: threading.Event | None = None

    # ----------------------------------------------------------------- publik

    def mulai(
        self, setelan: dict[str, int], *, fps_kamera: float = 0.0
    ) -> dict[str, Any]:
        """Mulai merekam. Raise kalau sudah jalan atau disk mepet.

        `fps_kamera` adalah laju yang BENAR-BENAR dikirim kamera. Kalau ada, ia
        menang atas angka setelan, karena keduanya harus sama agar durasi video
        sama dengan durasi kejadian.

        Diukur di Lampung 2026-09-23: kamera mengirim 20 fps, berkas ditandai
        "5 fps" karena itu yang tertulis di layar, dan 19 detik rekaman jadi 77
        detik tontonan — gerakannya melambat 4x. Yang diminta operator justru
        "apa yang terlihat di layar line adalah apa yang terekam".

        Angka setelan tetap dipakai untuk sumber yang tidak bisa melapor
        (berkas video, webcam), dan untuk lebar/tinggi yang tidak ada
        hubungannya dengan laju.
        """
        with self._lock:
            if self._merekam:
                raise RekamSedangJalan(f"{self._line_code} sudah merekam")
            self._pastikan_disk_cukup()

            setelan = self._fps_efektif(setelan, fps_kamera)

            self._videos_dir.mkdir(parents=True, exist_ok=True)
            berkas = self._nama_berkas_baru()

            self._setelan = dict(setelan)
            self._berkas = berkas
            self._mulai_epoch = time.time()
            self._frame_ditulis = 0
            self._frame_dibuang = 0
            self._alasan_berhenti = None
            self._codec = None
            self._antrean = queue.Queue(maxsize=self._ukuran_antrean)
            self._berhenti.clear()
            self._merekam = True

            self._thread = threading.Thread(
                target=self._jalan_encoder,
                name=f"video-encoder-{self._line_code}",
                daemon=True,
            )
            self._thread.start()

        logger.warning(
            "Rekam video MULAI %s -> %s (%dx%d @ %d fps)",
            self._line_code,
            berkas,
            setelan["width"],
            setelan["height"],
            setelan["fps"],
        )
        return self.status()

    def stop(self) -> dict[str, Any]:
        """Hentikan rekaman dan tutup berkas dengan rapi."""
        with self._lock:
            if not self._merekam:
                raise RekamTidakJalan(f"{self._line_code} tidak sedang merekam")
            thread = self._thread
            if self._alasan_berhenti is None:
                self._alasan_berhenti = "diminta"

        self._berhenti.set()
        if thread is not None:
            # Encoder menutup VideoWriter sendiri; tanpa join, berkas bisa
            # terbaca rusak oleh pemanggil yang langsung membukanya.
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.error(
                    "Encoder %s tidak berhenti dalam 10 detik — berkas mungkin tidak lengkap",
                    self._line_code,
                )

        with self._lock:
            self._merekam = False
            self._thread = None
            self._antrean = None

        logger.warning(
            "Rekam video STOP %s -> %s (%d frame ditulis, %d dibuang)",
            self._line_code,
            self._berkas,
            self._frame_ditulis,
            self._frame_dibuang,
        )
        return self.status()

    def tulis(self, frame: Any) -> None:
        """Serahkan satu frame ke encoder. TIDAK PERNAH blocking.

        Dipanggil dari thread capture tiap frame. Kalau tidak sedang merekam,
        atau antrean penuh, frame dibuang diam-diam — melempar di sini akan
        menjatuhkan capture worker dan mematikan line.
        """
        antrean = self._antrean
        if not self._merekam or antrean is None or frame is None:
            return
        try:
            antrean.put_nowait(frame)
        except queue.Full:
            self._frame_dibuang += 1

    def status(self) -> dict[str, Any]:
        bytes_kini = 0
        if self._berkas:
            jalur = self._videos_dir / self._berkas
            try:
                bytes_kini = jalur.stat().st_size
            except OSError:
                bytes_kini = 0
        return {
            "line_code": self._line_code,
            "merekam": self._merekam,
            "berkas": self._berkas,
            "mulai_epoch": self._mulai_epoch,
            "frame_ditulis": self._frame_ditulis,
            "frame_dibuang": self._frame_dibuang,
            "bytes": bytes_kini,
            "codec": self._codec,
            "setelan": dict(self._setelan) if self._setelan else None,
            "alasan_berhenti": self._alasan_berhenti,
        }

    # ---------------------------------------------------------------- privat

    @staticmethod
    def _fps_efektif(setelan: dict[str, int], fps_kamera: float) -> dict[str, int]:
        """Laju kamera menang atas angka setelan, kalau kamera bisa melapor.

        Dibulatkan: header MP4 menyimpan laju sebagai pecahan, tapi kamera
        melapor 19,97 dan pembulatan membuat angka di layar cocok dengan angka
        di berkas. Tetap lewat `bersihkan_setelan_rekam` supaya kamera yang
        salah setel tidak menyelundupkan nilai di luar batas ke encoder.
        """
        if fps_kamera <= 0:
            return setelan
        return bersihkan_setelan_rekam({**setelan, "fps": round(fps_kamera)})

    def _nama_berkas_baru(self) -> str:
        """Nama yang belum dipakai, berstempel detik.

        Stop lalu mulai lagi dalam detik yang sama menghasilkan nama yang sama
        persis, dan `VideoWriter` menimpa tanpa mengeluh — rekaman sebelumnya
        hilang tanpa satu pun galat. Menambah detik ke stempel tidak menolong:
        yang menekan Stop lalu Rekam lagi memang menekannya beruntun.
        """
        stempel = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dasar = f"{self._line_code}_{stempel}"
        kandidat = f"{dasar}.mp4"
        n = 2
        while (self._videos_dir / kandidat).exists():
            kandidat = f"{dasar}-{n}.mp4"
            n += 1
        return kandidat

    def _sisa_disk_gb(self) -> float:
        induk = self._videos_dir if self._videos_dir.exists() else self._videos_dir.parent
        try:
            return shutil.disk_usage(induk).free / 1e9
        except OSError:
            # Folder belum ada / tidak terbaca: jangan memblokir rekaman karena
            # pemeriksaan yang gagal, tapi catat supaya tidak senyap.
            logger.warning("Sisa disk tidak terbaca untuk %s", induk)
            return float("inf")

    def _pastikan_disk_cukup(self) -> None:
        if self._disk_min_free_gb <= 0:
            return
        sisa = self._sisa_disk_gb()
        if sisa < self._disk_min_free_gb:
            raise DiskMepet(
                f"sisa disk {sisa:.1f} GB di bawah ambang {self._disk_min_free_gb:.1f} GB"
            )

    def _buka_writer(self, jalur: Path, lebar: int, tinggi: int, fps: int):
        """Coba tiap codec sampai ada yang benar-benar terbuka.

        OpenCV memulangkan writer yang `isOpened()` False kalau codec tidak ada,
        tanpa melempar — jadi codec yang hilang harus diperiksa di sini, bukan
        dibiarkan menghasilkan berkas 0 byte yang baru ketahuan berjam-jam
        kemudian.
        """
        for tag in _CODEC:
            writer = cv2.VideoWriter(
                str(jalur), cv2.VideoWriter_fourcc(*tag), float(fps), (lebar, tinggi)
            )
            if writer.isOpened():
                if tag != _CODEC[0]:
                    logger.warning(
                        "Codec %s tidak tersedia — rekaman %s memakai %s (berkas lebih besar)",
                        _CODEC[0],
                        self._line_code,
                        tag,
                    )
                return writer, tag
            writer.release()
        return None, None

    def _jalan_encoder(self) -> None:
        setelan = self._setelan or {}
        lebar, tinggi = setelan["width"], setelan["height"]
        jalur = self._videos_dir / (self._berkas or "rekaman.mp4")

        writer, tag = self._buka_writer(jalur, lebar, tinggi, setelan["fps"])
        if writer is None:
            logger.error(
                "Tidak ada codec video yang bisa dipakai (%s) — rekaman %s dibatalkan",
                ", ".join(_CODEC),
                self._line_code,
            )
            with self._lock:
                self._merekam = False
                self._alasan_berhenti = "codec_tidak_ada"
            return
        self._codec = tag

        sejak_periksa = 0
        try:
            while not self._berhenti.is_set():
                if self._jeda_uji is not None and not self._jeda_uji.is_set():
                    time.sleep(0.01)
                    continue

                antrean = self._antrean
                if antrean is None:
                    break
                try:
                    frame = antrean.get(timeout=0.2)
                except queue.Empty:
                    continue

                if frame.shape[0] != tinggi or frame.shape[1] != lebar:
                    frame = cv2.resize(
                        frame, (lebar, tinggi), interpolation=cv2.INTER_AREA
                    )
                writer.write(np.ascontiguousarray(frame))
                self._frame_ditulis += 1

                sejak_periksa += 1
                if sejak_periksa >= _PERIKSA_DISK_TIAP:
                    sejak_periksa = 0
                    if (
                        self._disk_min_free_gb > 0
                        and self._sisa_disk_gb() < self._disk_min_free_gb
                    ):
                        logger.error(
                            "Rekam video %s BERHENTI SENDIRI: sisa disk di bawah %.1f GB",
                            self._line_code,
                            self._disk_min_free_gb,
                        )
                        with self._lock:
                            self._alasan_berhenti = "disk_mepet"
                            self._merekam = False
                        break
        finally:
            writer.release()
