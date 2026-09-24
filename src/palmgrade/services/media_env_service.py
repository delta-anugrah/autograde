"""Baca & tulis `media.env` — setelan sumber kamera dan model deteksi per line.

Berkas TERPISAH dari `.env`, sengaja. `.env` memuat `LICENSE_TOKEN`,
`R2_SECRET_ACCESS_KEY`, dan `WEBHOOK_SECRET`; me-mount berkas itu writable ke
konsol berarti satu bug penulisan bisa merusak kredensial produksi. `media.env`
paling jauh rusak berarti ketiga line kembali ke bawaan `hikrobot`.

Bentuk berkasnya cuma diketahui modul ini, dengan satu pengecualian sadar:
proses line membacanya sendiri di `Settings.__post_init__` (environment
container beku sejak dibuat, jadi restart saja tidak pernah melihat setelan
baru). Compose membacanya lewat `--env-file`, BUKAN `env_file:` — lihat kepala
`docker-compose.yml`.

**Dua layar, satu berkas.** Sumber Kamera menulis `CAMERA_TYPE`/`MEDIA_FILE`/
`VIDEO_LOOP`, Model Deteksi menulis `MODEL_FILE`. Masing-masing WAJIB
mempertahankan kunci milik yang lain: `tulis()` dulu menulis ulang berkas
dengan kunci kamera saja, dan menyimpan Sumber Kamera akan diam-diam
mengembalikan ketiga line ke model bawaan.

`baca()` MEMAAFKAN, `tulis()` tidak. Baris tak dikenal dan nilai ngawur jatuh ke
bawaan, karena berkas yang disunting tangan atau ditulis versi lebih baru tidak
boleh membuat line gagal boot. Yang rewel adalah gerbang simpan di
`domain/sumber_kamera`, sebelum nilainya sampai ke sini.
"""

from __future__ import annotations

import errno
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Tiga line, dalam urutan tampil. Prefix env-nya `LINE_1_` dst.
LINE_CODES: tuple[str, ...] = ("line-1", "line-2", "line-3")

#: Setelan satu line yang belum pernah diatur. `hikrobot` supaya PC pabrik yang
#: belum punya berkas ini tetap memakai kamera sungguhan.
BAWAAN: dict[str, Any] = {"sumber": "hikrobot", "berkas": "", "ulang": False}

_NOMOR = {kode: str(i + 1) for i, kode in enumerate(LINE_CODES)}

_KEPALA = (
    "# Sumber kamera + model deteksi per line — ditulis layar Support di konsol.\n"
    "# JANGAN disunting tangan saat konsol jalan: simpan berikutnya menimpanya.\n"
    "# Rahasia (lisensi, R2, webhook) TIDAK ada di sini; itu di .env.\n"
)


def _sumber_dari(camera_type: str, berkas: str) -> str:
    """`CAMERA_TYPE` + ada-tidaknya berkas -> pilihan layar.

    Kebalikan dari `CAMERA_TYPE_UNTUK`: `opencv` memetakan ke dua pilihan, dan
    berkaslah yang membedakannya.
    """
    if camera_type == "photo":
        return "foto"
    if camera_type == "opencv":
        return "video" if berkas else "webcam"
    return "hikrobot"


class MediaEnvService:
    """Satu-satunya pembaca dan penulis `media.env`."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # ------------------------------------------------------------------ baca

    def baca(self) -> dict[str, dict[str, Any]]:
        """Setelan ketiga line, dilengkapi bawaan untuk apa pun yang hilang."""
        mentah = self._baris()
        hasil: dict[str, dict[str, Any]] = {}
        for kode in LINE_CODES:
            n = _NOMOR[kode]
            camera_type = mentah.get(f"LINE_{n}_CAMERA_TYPE", "").strip().lower()
            berkas = mentah.get(f"LINE_{n}_MEDIA_FILE", "").strip()
            if camera_type not in ("hikrobot", "opencv", "photo"):
                # Disunting tangan dengan nilai ngawur. Line tetap boot memakai
                # kamera sungguhan, bukan gagal.
                hasil[kode] = dict(BAWAAN)
                continue
            hasil[kode] = {
                "sumber": _sumber_dari(camera_type, berkas),
                "berkas": berkas,
                "ulang": mentah.get(f"LINE_{n}_VIDEO_LOOP", "").strip().lower() == "true",
            }
        return hasil

    def baca_model(self) -> dict[str, str]:
        """Model pilihan ketiga line. `""` = bawaan PC (`MODEL_FILE` di `.env`).

        Nama yang tidak lolos saringan (disunting tangan) dibaca kosong, bukan
        melempar — aturan memaafkan yang sama dengan `baca()`.
        """
        from ..domain.pilihan_model import ModelTidakSah, bersihkan_nama_model

        mentah = self._baris()
        hasil: dict[str, str] = {}
        for kode in LINE_CODES:
            nilai = mentah.get(f"LINE_{_NOMOR[kode]}_MODEL_FILE", "")
            try:
                hasil[kode] = bersihkan_nama_model(nilai)
            except ModelTidakSah:
                logger.warning("media.env: model %s untuk %s diabaikan", nilai[:80], kode)
                hasil[kode] = ""
        return hasil

    def _baris(self) -> dict[str, str]:
        """`KUNCI=nilai` dari berkas. Berkas tidak ada / tak terbaca -> kosong."""
        try:
            teks = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except UnicodeDecodeError as exc:
            logger.warning("media.env tidak terbaca (%s) — memakai bawaan", exc)
            return {}
        except OSError as exc:
            logger.warning("media.env tidak terbaca (%s) — memakai bawaan", exc)
            return {}

        pasangan: dict[str, str] = {}
        for baris in teks.splitlines():
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            kunci, nilai = baris.split("=", 1)
            pasangan[kunci.strip()] = nilai.strip()
        return pasangan

    # ----------------------------------------------------------------- tulis

    def tulis(self, setelan: dict[str, dict[str, Any]]) -> None:
        """Ganti sumber kamera ketiga line; pilihan model tetap seperti adanya."""
        self._tulis_isi(setelan, self.baca_model())

    def tulis_model(self, pilihan: dict[str, str]) -> None:
        """Ganti model ketiga line; sumber kamera tetap seperti adanya.

        Nama disaring lagi di sini walau gerbang simpan konsol sudah
        menyaringnya: nama ini ditulis apa adanya sebagai satu baris, dan satu
        `\n` yang lolos menyelundupkan baris kedua ke berkas setelan.
        """
        from ..domain.pilihan_model import bersihkan_nama_model

        bersih = {kode: bersihkan_nama_model(pilihan.get(kode, "")) for kode in LINE_CODES}
        self._tulis_isi(self.baca(), bersih)

    def _tulis_isi(self, setelan: dict[str, dict[str, Any]], model: dict[str, str]) -> None:
        """Timpa seluruh berkas dengan setelan kamera + model ketiga line.

        Lewat berkas sementara di folder yang sama lalu `os.replace`, yang
        atomik di POSIX: berkas setengah tertulis akibat mati listrik akan
        membuat ketiga line gagal boot sekaligus.
        """
        from ..domain.sumber_kamera import CAMERA_TYPE_UNTUK

        bagian = [_KEPALA]
        for kode in LINE_CODES:
            n = _NOMOR[kode]
            satu = {**BAWAAN, **setelan.get(kode, {})}
            bagian.append(
                f"LINE_{n}_CAMERA_TYPE={CAMERA_TYPE_UNTUK[satu['sumber']]}\n"
                f"LINE_{n}_MEDIA_FILE={satu['berkas']}\n"
                f"LINE_{n}_VIDEO_LOOP={'true' if satu['ulang'] else 'false'}\n"
                f"LINE_{n}_MODEL_FILE={model.get(kode, '')}\n"
            )
        isi = "".join(bagian)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, sementara = tempfile.mkstemp(dir=self._path.parent, prefix=".media.env.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(isi)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(sementara, self._path)
            except OSError as e:
                # Berkas yang di-bind-mount Docker (`./media.env:/config/media.env`
                # di docker-compose) adalah MOUNT POINT, dan `os.replace` ke mount
                # point selalu gagal EBUSY -- betapapun benar izinnya. Gejalanya di
                # PC pabrik: layar Sumber Kamera menjawab HTTP 500 tiap kali
                # disimpan, sementara `touch` ke berkas yang sama berhasil, jadi
                # tidak ada pemeriksaan izin yang bisa menemukannya.
                #
                # Di situ berkasnya ditulis di tempat. Itu MELEPAS atomisitas, yang
                # memang tidak bisa didapat pada mount point: menukar nama berkas
                # yang menjadi mount point bukan operasi yang diizinkan kernel.
                # Jendela kerusakannya (mati listrik tepat saat menulis ~200 byte)
                # jauh lebih kecil daripada kerugian pasti "sumber kamera tidak
                # bisa diubah sama sekali di setiap pemasangan Docker".
                if e.errno not in (errno.EBUSY, errno.EXDEV, errno.EINVAL):
                    raise
                with open(self._path, "w", encoding="utf-8") as f:
                    f.write(isi)
                    f.flush()
                    os.fsync(f.fileno())
                Path(sementara).unlink(missing_ok=True)
        except BaseException:
            Path(sementara).unlink(missing_ok=True)
            raise
