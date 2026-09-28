"""Tiga layar Support di tab Line: Rekam Video, Sumber Kamera, Model Deteksi.

Dipisah dari `console_service.py` (batch 1, 2026-09-28) karena berkas itu lewat
1.000 baris. Mixin, bukan service sendiri: route, test, dan layar memanggil
method ini lewat `ConsoleService` sejak awal, dan test menimpa
`_buktikan_berkas` di instance-nya. Isi method tidak berubah.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.config import LineEndpoint, Settings
from ..domain.pilihan_model import ModelTidakSah, bersihkan_pilihan_model
from ..domain.setelan_rekam import BAWAAN as REKAM_BAWAAN
from ..domain.setelan_rekam import KUNCI_SETELAN_REKAM, bersihkan_setelan_rekam
from ..domain.sumber_kamera import SumberTidakSah, bersihkan_sumber
from ..integrations.notifications.line_client import LineClient
from ..repositories.console_repository import ConsoleStore
from .media_env_service import LINE_CODES, MediaEnvService
from .media_library import MediaLibrary
from .model_library import ModelLibrary

logger = logging.getLogger(__name__)


class LayarLineSupport:
    """Disediakan `ConsoleService`: atribut di bawah dan `_require_line`."""

    settings: Settings
    store: ConsoleStore
    lines: tuple[LineEndpoint, ...]
    line_client: LineClient
    _require_line: Callable[[str], LineEndpoint]

    # ──────────────────────────────────────── rekam video (layar Support) ───

    def setelan_rekam(self) -> dict[str, Any]:
        """Setelan rekam yang berlaku. Konsol pemegang kebenarannya; line cuma
        menerima salinannya tiap kali diminta mulai."""
        tersimpan = self.store.get_state(KUNCI_SETELAN_REKAM)
        if tersimpan:
            # Digabung dengan BAWAAN supaya baris yang disimpan sebelum sebuah
            # field ada tidak mengembalikan payload cacat ke layar — dan disaring
            # ke kunci BAWAAN supaya field yang sudah dicabut (`bitrate_kbps`,
            # 2026-09-25) tidak terus ikut dari baris lama.
            lama = json.loads(tersimpan)
            return {**REKAM_BAWAAN, **{k: v for k, v in lama.items() if k in REKAM_BAWAAN}}
        return dict(REKAM_BAWAAN)

    async def simpan_setelan_rekam(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Simpan setelan rekam.

        TIDAK menyentuh rekaman yang sedang jalan: mengubah resolusi di tengah
        berkas MP4 menghasilkan berkas rusak. Setelan baru berlaku pada rekaman
        BERIKUTNYA, dan layar mengatakan itu.
        """
        bersih = bersihkan_setelan_rekam(payload)
        self.store.set_state(KUNCI_SETELAN_REKAM, json.dumps(bersih))
        logger.warning(
            "Setelan rekam diubah oleh %s: %dx%d",
            diubah_oleh, bersih["width"], bersih["height"],
        )
        return bersih

    async def rekam_mulai(self, line_code: str, *, diubah_oleh: str) -> dict[str, Any]:
        """Suruh satu line mulai merekam dengan setelan yang tersimpan."""
        line = self._require_line(line_code)
        setelan = self.setelan_rekam()
        # Tanpa fps: yang dipakai laju kamera, dan line sendiri yang mencatatnya
        # ("Rekam video MULAI ... @ N fps"). Angka tersimpan di sini cuma cadangan
        # dan akan terbaca seperti laju berkasnya.
        logger.warning(
            "Rekam video %s dimulai oleh %s (%dx%d)",
            line_code, diubah_oleh, setelan["width"], setelan["height"],
        )
        return await self.line_client.rekam_mulai(line, setelan)

    async def rekam_stop(self, line_code: str, *, diubah_oleh: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        logger.warning("Rekam video %s dihentikan oleh %s", line_code, diubah_oleh)
        return await self.line_client.rekam_stop(line)

    async def rekam_status_semua(self) -> dict[str, Any]:
        """Status tiap line + setelan yang berlaku + sisa disk.

        Line yang tidak menjawab dilaporkan `terbaca: False`, bukan menjatuhkan
        seluruh jawaban — satu line mati tidak boleh mengosongkan layar, dan
        line yang sedang restart adalah kejadian normal.
        """
        baris = []
        for line in self.lines:
            try:
                status = await self.line_client.rekam_status(line)
                baris.append({**status, "line_code": line.line_code, "terbaca": True})
            except Exception as exc:  # LineUnavailable / LinePlcTolak / apa pun
                logger.warning(
                    "Status rekam belum terbaca dari %s: %s", line.line_code, exc
                )
                baris.append({
                    "line_code": line.line_code,
                    "terbaca": False,
                    "merekam": False,
                    "alasan": str(exc)[:200],
                })
        return {
            "lines": baris,
            "setelan": self.setelan_rekam(),
            "disk_bebas_gb": self._disk_bebas_gb(),
            # Jalur PENUH, bukan "videos/" relatif: yang membacanya membuka PC
            # pabrik lewat AnyDesk dan perlu tahu ke mana harus pergi. Jalurnya
            # juga berbeda per mesin (`/opt/palmgrade/autograde/videos` di
            # pabrik, `<repo>/videos` di jalur native), jadi layar tidak boleh
            # mengarangnya sendiri.
            "folder": self.settings.videos_dir_tampil,
        }

    def _disk_bebas_gb(self) -> float | None:
        """Sisa disk tempat rekaman ditulis, untuk ditampilkan di layar.

        `None` kalau tidak terbaca — layar menuliskan tanda hubung, bukan nol
        yang terbaca seperti disk penuh.
        """
        folder = self.settings.videos_dir
        target = folder if folder.exists() else folder.parent
        try:
            return round(shutil.disk_usage(target).free / 1e9, 1)
        except OSError:
            logger.warning("Sisa disk tidak terbaca untuk %s", target)
            return None

    # ────────────────────────────────────── sumber kamera (layar Support) ───

    def _media_env(self) -> MediaEnvService:
        return MediaEnvService(Path(self.settings.media_env_path))

    def _media_library(self) -> MediaLibrary:
        return MediaLibrary(Path(self.settings.media_dir))

    def sumber_kamera(self) -> dict[str, Any]:
        """Setelan ketiga line + daftar berkas yang boleh dipilih."""
        pustaka = self._media_library()
        return {
            "lines": self._media_env().baca(),
            "video": pustaka.daftar_video(),
            "foto": pustaka.daftar_foto(),
        }

    def _buktikan_berkas(self, sumber: str, berkas: str) -> None:
        """Buktikan berkasnya benar-benar bisa dibuka, sebelum menyimpannya.

        `OpenCVCamera` dan `PhotoCamera` sengaja `raise` saat berkasnya tidak
        terbaca. Tanpa pembuktian di sini, memilih berkas rusak berarti: line
        boot, gagal, mati, `restart: unless-stopped` menyalakannya lagi, gagal
        lagi — selamanya, dan satu-satunya jalan keluar AnyDesk.

        Ada-tidaknya berkas sudah dicek pemanggil; yang dibuktikan di sini
        isinya.
        """
        import cv2  # lokal: konsol tidak mengimpornya di jalur boot

        path = str(Path(self.settings.media_dir) / berkas)
        if sumber == "foto":
            if cv2.imread(path) is None:
                raise SumberTidakSah(f"{berkas} tidak bisa dibaca sebagai gambar")
            return

        cap = cv2.VideoCapture(path)
        try:
            terbaca, _ = cap.read() if cap.isOpened() else (False, None)
        finally:
            cap.release()
        if not terbaca:
            raise SumberTidakSah(f"{berkas} tidak bisa dibaca sebagai video")

    async def simpan_sumber_kamera(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Validasi, buktikan berkas, tulis, lalu restart line yang berubah.

        Gagal validasi atau pembuktian TIDAK menulis apa pun: setelan lama tetap
        berlaku. Gagal restart sebaliknya dibiarkan — berkasnya sudah sah, dan
        line yang tidak menjawab akan membacanya sendiri saat hidup lagi.
        Rollback berarti menulis dan merestart lagi, dua langkah yang bisa gagal
        dengan cara yang sama dan meninggalkan keadaan yang lebih sulit dibaca.
        """
        if not isinstance(payload, dict):
            raise SumberTidakSah("payload harus objek")
        asing = set(payload) - set(LINE_CODES)
        if asing:
            raise SumberTidakSah(f"line tidak dikenal: {', '.join(sorted(asing))}")
        kurang = set(LINE_CODES) - set(payload)
        if kurang:
            raise SumberTidakSah(f"line belum diisi: {', '.join(sorted(kurang))}")

        bersih = {kode: bersihkan_sumber(payload[kode]) for kode in LINE_CODES}

        pustaka = self._media_library()
        for kode, satu in bersih.items():
            if not satu["berkas"]:
                continue
            if not pustaka.ada(satu["berkas"]):
                raise SumberTidakSah(
                    f"{kode}: {satu['berkas']} tidak ada di folder media"
                )
            self._buktikan_berkas(satu["sumber"], satu["berkas"])

        env = self._media_env()
        sebelum = env.baca()
        env.tulis(bersih)
        logger.warning(
            "Sumber kamera diubah oleh %s: %s",
            diubah_oleh,
            ", ".join(f"{k}={v['sumber']}:{v['berkas'] or '-'}" for k, v in bersih.items()),
        )

        hasil = await self._restart_yang_berubah(sebelum, bersih)
        pustaka = self._media_library()
        return {"lines": hasil, "video": pustaka.daftar_video(), "foto": pustaka.daftar_foto()}

    async def _restart_yang_berubah(
        self, sebelum: dict[str, Any], sesudah: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Restart hanya line yang setelannya berubah; line diam dicatat, bukan dilempar.

        Dipakai Sumber Kamera dan Model Deteksi — dua layar, satu aturan: berkas
        sudah sah dan tersimpan, jadi line yang tidak menjawab akan membacanya
        sendiri saat hidup lagi. Tidak ada rollback (lihat `simpan_sumber_kamera`).
        """
        hasil = []
        for line in self.lines:
            kode = line.line_code
            if sebelum.get(kode) == sesudah[kode]:
                hasil.append({"line_code": kode, "direstart": False, "berubah": False})
                continue
            try:
                await self.line_client.restart(line)
                hasil.append({"line_code": kode, "direstart": True, "berubah": True})
            except Exception as exc:  # LineUnavailable / apa pun
                logger.warning("Restart %s gagal: %s", kode, exc)
                hasil.append(
                    {
                        "line_code": kode,
                        "direstart": False,
                        "berubah": True,
                        "alasan": str(exc)[:200],
                    }
                )
        return hasil

    # ────────────────────────────────────── model deteksi (layar Support) ───

    def _model_library(self) -> ModelLibrary:
        return ModelLibrary(self.settings.models_release_dir, self.settings.engines_dir)

    def model_deteksi(self) -> dict[str, Any]:
        """Pilihan model ketiga line (`""` = bawaan PC) + semua model beserta kelasnya.

        `folder.terbaca` membedakan folder kosong dari folder yang tidak bisa
        dibuka konsol (mount `./models` belum ada di compose host).
        """
        pustaka = self._model_library()
        return {
            "lines": self._media_env().baca_model(),
            "model": pustaka.daftar(),
            "folder": {
                "path": str(self.settings.models_release_dir),
                "terbaca": pustaka.terbaca(),
            },
        }

    async def model_deteksi_async(self) -> dict[str, Any]:
        """`model_deteksi()` di thread terpisah: membaca zip model memblok, dan di
        event loop konsol itu menahan semua request lain, termasuk polling
        layar operator tiap 2 detik."""
        return await asyncio.to_thread(self.model_deteksi)

    async def simpan_model_deteksi(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Validasi, pastikan model ada dan kelasnya cocok, tulis, restart yang berubah.

        Model yang kelasnya bukan tepat empat kelas yang dikenal DITOLAK di sini,
        bukan dipasang lalu gagal: line yang memuatnya tetap jalan dan tidak
        menghitung apa pun, tanpa satu pun error yang terlihat operator
        (Lampung, seminggu, 2026-09-23). Gagal validasi tidak menulis apa pun.
        """
        bersih = bersihkan_pilihan_model(payload)
        env = self._media_env()
        sebelum = env.baca_model()

        daftar = await asyncio.to_thread(self._model_library().daftar)
        semua = {m["berkas"]: m for m in daftar}
        for kode, nama in bersih.items():
            # Cuma pilihan yang BERUBAH yang diperiksa. Line yang masih menunjuk
            # model yang sudah dihapus tidak boleh menahan simpan line lain;
            # keadaannya tidak memburuk karena simpan ini.
            if not nama or nama == sebelum.get(kode):
                continue
            info = semua.get(nama)
            if info is None:
                raise ModelTidakSah(f"{kode}: {nama} tidak ada di models/release")
            if not info["cocok"]:
                raise ModelTidakSah(f"{kode}: {nama} tidak bisa dipakai ({info['alasan']})")

        env.tulis_model(bersih)
        logger.warning(
            "Model deteksi diubah oleh %s: %s",
            diubah_oleh,
            ", ".join(f"{k}={v or 'bawaan'}" for k, v in bersih.items()),
        )

        hasil = await self._restart_yang_berubah(sebelum, bersih)
        return {"lines": hasil, "model": list(semua.values())}
