"""Cache status ketiga line untuk layar operator.

`/api/console/state` dipanggil tiap 2 detik oleh layar, sementara satu line yang
sekarat bisa menggantung sampai timeout. Kalau state memanggil line langsung,
satu line mati membekukan seluruh konsol. Jadi yang memanggil line adalah worker
ini, di latar, dan state cuma membaca hasil terakhirnya.

Hidup terlepas dari AutoERP: konsol tanpa `ERP_URL` tetap butuh tombol piston.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..domain.operator_error import LINE_MENOLAK, OperatorError

logger = logging.getLogger(__name__)


class LineStatusWorker:
    def __init__(self, lines, line_client, *, interval_s: float = 1.0) -> None:
        self._lines = list(lines)
        self._client = line_client
        self._interval_s = interval_s
        self._state: dict[str, dict[str, Any]] = {}
        # Sejak kapan upload foto tiap line gagal, menurut putaran terakhir. Hanya
        # untuk mencatat putus/pulih sekali masing-masing ke tab Log.
        self._unggah_putus: dict[str, float | None] = {}
        # Kunci ditolak (401/403) putus/pulih sekali masing-masing per line,
        # sama alasannya dengan `_unggah_putus`: tanpa ini satu kunci yang
        # salah menulis WARNING tiap detik dan mendorong keluar galat lain
        # yang lebih tua dari tabel `event_log` (aturan 21).
        self._kunci_ditolak: set[str] = set()
        # Line yang AI-nya sedang mati (batch 2.1), untuk satu ERROR saat masuk
        # dan satu WARNING saat pulih di tab Log, bukan satu per detik.
        self._ai_mati: set[str] = set()
        # Batch 3.6 / 3.7: line yang kameranya berhenti mengirim, dan tingkat disk
        # terakhir tiap line. Pola yang sama: satu baris per transisi.
        self._frame_berhenti: set[str] = set()
        self._tingkat_disk: dict[str, str] = {}

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    async def run_once(self) -> None:
        for line in self._lines:
            try:
                jawab = await self._client.status(line)
            except OperatorError as exc:
                # Kunci ditolak (INTERNAL_SECRET beda antara konsol dan line)
                # BUKAN line mati: line itu bisa saja tetap menggrading dan
                # mengirim event lewat WEBHOOK_SECRET. `kode` dibawa ke
                # `/api/console/state` (lewat `plc` di console_service) supaya
                # layar bisa membedakannya dari OFFLINE sungguhan.
                self._state[line.line_code] = {
                    "reachable": False,
                    "kode": exc.code,
                    "status": exc.params.get("status"),
                }
                self._catat_kunci(line.line_code, ditolak=exc.code == LINE_MENOLAK)
                continue
            except Exception as exc:                      # line mati bukan alasan berhenti
                logger.debug("Status %s tidak terbaca: %s", line.line_code, exc)
                self._state[line.line_code] = {"reachable": False}
                self._catat_kunci(line.line_code, ditolak=False)
                continue
            piston = jawab.get("piston") or {}
            self._state[line.line_code] = {
                "reachable": True,
                "ffb_source": jawab.get("ffb_source"),
                "piston_requested": piston.get("requested"),
                "piston_open": piston.get("confirmed_open"),
                # `or []`: line versi lama tidak mengirim field ini, dan None
                # di layar akan membuat pita alarm gagal merender.
                "alarms": jawab.get("alarms") or [],
                # Cloud Photo di Last Sync. None dari line versi lama: konsol
                # menulisnya "tidak terbaca", bukan menganggapnya putus.
                "unggah": jawab.get("unggah"),
                # Penjaga AI mati (batch 2.1). None dari line versi lama: kartu
                # tidak menggambar apa pun, bukan menebak.
                "ai": jawab.get("ai"),
                # Pemantau disk (batch 3.7). None dari line versi lama: layar
                # tidak menggambar alert disk, bukan menebak.
                "disk": jawab.get("disk"),
            }
            self._catat_unggah(line.line_code, jawab.get("unggah"))
            self._catat_ai(line.line_code, jawab.get("ai"))
            self._catat_frame(line.line_code, jawab.get("ai"))
            self._catat_disk(line.line_code, jawab.get("disk"))
            self._catat_kunci(line.line_code, ditolak=False)

    def _catat_kunci(self, line_code: str, *, ditolak: bool) -> None:
        """Satu WARNING per transisi masuk/keluar kunci ditolak, bukan tiap poll
        (poll ini jalan tiap detik). Sama pola dengan `_catat_unggah`.

        Yang menolak adalah LINE: kunci yang dikirim konsol (`INTERNAL_SECRET`
        konsol) tidak sama dengan yang dipegang line itu.
        """
        sudah_ditolak = line_code in self._kunci_ditolak
        if ditolak and not sudah_ditolak:
            logger.warning(
                "%s menolak kunci konsol: INTERNAL_SECRET di line itu beda dari yang dipakai konsol",
                line_code,
            )
            self._kunci_ditolak.add(line_code)
        elif sudah_ditolak and not ditolak:
            logger.warning("%s menerima kunci konsol lagi, sudah pulih", line_code)
            self._kunci_ditolak.discard(line_code)

    def _catat_ai(self, kode: str, ai: dict[str, Any] | None) -> None:
        """AI line berhenti/kembali memproses → satu baris di `docker logs` konsol.

        Sejak batch 3.2 line menyimpan log-nya sendiri (`log_line.db`) dan itu
        yang sampai ke tab Log lewat tarikan log line (aturan 34): baris ERROR/
        WARNING sungguhan sudah dicatat di `PenjagaAi` pada line itu. Cermin di
        sini cuma INFO supaya satu kejadian tidak muncul dua kali di tab Log
        atau dua kali di kelompok Discord (aturan 35 / ruling R5).
        """
        mati = bool(ai and ai.get("mati"))
        if mati and kode not in self._ai_mati:
            logger.info(
                "%s: AI berhenti memproses (kode %s): lebih dari %s detik kamera mengirim "
                "gambar tapi tidak ada yang digrading, buah lewat tanpa disortir. Restart "
                "line lewat Setelan, Danger Zone, lalu periksa log line itu.",
                kode, ai.get("kode") or "AI_MATI", ai.get("ambang_detik") or "?",
            )
            self._ai_mati.add(kode)
        elif not mati and kode in self._ai_mati:
            logger.info("%s: AI memproses lagi", kode)
            self._ai_mati.discard(kode)

    def _catat_frame(self, kode: str, ai: dict[str, Any] | None) -> None:
        """Kamera line tersambung tapi berhenti mengirim (batch 3.6) → satu baris
        di `docker logs` konsol saat masuk dan satu saat keluar, pola `_catat_ai`.

        INFO saja (ruling R5): baris ERROR/WARNING sungguhan sudah dicatat di
        `PenjagaAi` pada line itu dan sampai tab Log lewat tarikan log line.
        """
        berhenti = bool(ai) and ai.get("keadaan") == "frame_berhenti"
        if berhenti and kode not in self._frame_berhenti:
            logger.info(
                "%s: kamera tersambung tapi tidak mengirim gambar (kode %s) lebih dari %s detik, "
                "buah lewat tanpa disortir. Periksa kabel data dan switch kamera, lalu restart "
                "line lewat Setelan, Danger Zone.",
                kode, ai.get("kode") or "FRAME_BERHENTI", ai.get("ambang_detik") or "?",
            )
            self._frame_berhenti.add(kode)
        elif not berhenti and kode in self._frame_berhenti:
            logger.info("%s: kamera mengirim gambar lagi", kode)
            self._frame_berhenti.discard(kode)

    def _catat_disk(self, kode: str, disk: dict[str, Any] | None) -> None:
        """Disk line hampir penuh / kritis / lega lagi (batch 3.7) → satu baris di
        `docker logs` konsol per transisi. Line versi lama (None) dan disk tak
        terbaca tidak mengubah apa pun.

        INFO saja (ruling R5): baris ERROR/WARNING sungguhan sudah dicatat di
        `PemantauDisk` pada line itu dan sampai tab Log lewat tarikan log line.
        """
        if not disk or disk.get("tingkat") not in ("aman", "peringatan", "kritis"):
            return
        tingkat = disk["tingkat"]
        lama = self._tingkat_disk.get(kode, "aman")
        if tingkat == lama:
            return
        self._tingkat_disk[kode] = tingkat
        sisa = f"sisa {disk.get('bebas_gb')} GB dari {disk.get('total_gb')} GB"
        if tingkat == "kritis":
            logger.info(
                "%s: disk hampir habis (kode %s), %s. Grading berhenti tersimpan begitu disk "
                "habis: kosongkan sekarang (docker system prune, rekaman video, unggah R2).",
                kode, disk.get("kode") or "DISK_KRITIS", sisa,
            )
        elif tingkat == "peringatan":
            logger.info(
                "%s: disk hampir penuh (kode %s), %s. Jadwalkan pengosongan.",
                kode, disk.get("kode") or "DISK_HAMPIR_PENUH", sisa,
            )
        else:
            logger.info("%s: disk kembali lega, %s", kode, sisa)

    def _catat_unggah(self, kode: str, unggah: dict[str, Any] | None) -> None:
        """Upload foto line putus/pulih → satu WARNING, supaya masuk tab Log.

        Line tidak memasang log_sink, jadi tanpa ini alasan gagalnya cuma ada di
        `docker logs` line. Pulih baru dicatat kalau jam unggah melewati awal putus:
        line yang restart melupakan status gagalnya sampai batch berikutnya, dan itu
        bukan bukti fotonya sudah naik.
        """
        if not unggah:
            return
        sejak = unggah.get("gagal_sejak")
        lama = self._unggah_putus.get(kode)
        if sejak and not lama:
            logger.warning("Cloud Photo %s terputus: %s", kode, unggah.get("pesan") or "tanpa keterangan")
            self._unggah_putus[kode] = sejak
        elif lama and not sejak and (unggah.get("terakhir") or 0) >= lama:
            logger.warning("Cloud Photo %s tersambung lagi", kode)
            self._unggah_putus[kode] = None

    async def run_loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_s)
