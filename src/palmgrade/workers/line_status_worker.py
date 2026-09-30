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

from ..domain.line_tak_terbaca import SEBAB_KUNCI_DITOLAK, SEBAB_LAIN, sebab_tak_terbaca
from ..domain.operator_error import OperatorError
from ..domain.transisi import PelacakTransisi, teks_lama

logger = logging.getLogger(__name__)

#: Poll gagal berturut-turut sebelum line dicatat tidak terbaca di tab Log. Satu poll yang
#: lewat timeout `status()` 1,5 detik (line yang sedang sibuk inferensi) bukan kejadian:
#: tanpa ambang ini tiap kedip menulis dua WARNING. Pola kamera (5 grab gagal, aturan 33).
#: Layar tidak menunggu: `reachable: False` dan `sebab_kode` sudah tampil sejak poll pertama.
TAK_TERBACA_POLL_BERTURUT = 3


class LineStatusWorker:
    def __init__(self, lines, line_client, *, interval_s: float = 1.0) -> None:
        self._lines = list(lines)
        self._client = line_client
        self._interval_s = interval_s
        self._state: dict[str, dict[str, Any]] = {}
        # Sejak kapan upload foto tiap line gagal, menurut putaran terakhir. Hanya
        # untuk mencatat putus/pulih sekali masing-masing ke tab Log.
        self._unggah_putus: dict[str, float | None] = {}
        # Line yang tidak terbaca konsol: satu pelacak per line, supaya awal kejadian,
        # sebabnya yang berganti, dan pulihnya masing-masing SATU WARNING, bukan tiap
        # poll (aturan 21: satu galat per detik mendorong keluar galat lain yang lebih
        # tua dari `event_log`). Alasan mentahnya cuma tampil di sini, di tab Log: layar
        # menulis kalimat ramah dari `sebab_kode` (keputusan user 2026-10-01).
        self._tak_terbaca: dict[str, PelacakTransisi] = {}
        self._gagal_beruntun: dict[str, int] = {}
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
                status = exc.params.get("status")
                sebab = sebab_tak_terbaca(exc.code, status)
                self._state[line.line_code] = {
                    "reachable": False,
                    "kode": exc.code,
                    "status": status,
                    "sebab_kode": sebab,
                }
                self._catat_tak_terbaca(line.line_code, sebab, str(exc))
                continue
            except Exception as exc:                      # line mati bukan alasan berhenti
                self._state[line.line_code] = {"reachable": False, "sebab_kode": SEBAB_LAIN}
                self._catat_tak_terbaca(line.line_code, SEBAB_LAIN, f"{type(exc).__name__}: {exc}")
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
            self._catat_terbaca_lagi(line.line_code)

    def _catat_tak_terbaca(self, line_code: str, sebab: str, mentah: str) -> None:
        """Satu WARNING saat konsol mulai tidak bisa membaca line itu (sesudah
        `TAK_TERBACA_POLL_BERTURUT` poll gagal berturut), dan satu lagi kalau sebabnya
        berganti di tengah kejadian (mati lalu menolak kunci adalah dua masalah), bukan
        tiap poll. Ini fakta KONSOL, bukan fakta line: line yang mati tidak bisa
        menceritakannya sendiri lewat tarikan log line (aturan 34).

        Yang menolak kunci adalah LINE: kunci yang dikirim konsol (`INTERNAL_SECRET`
        konsol) tidak sama dengan yang dipegang line itu.
        """
        beruntun = self._gagal_beruntun.get(line_code, 0) + 1
        self._gagal_beruntun[line_code] = beruntun
        if beruntun < TAK_TERBACA_POLL_BERTURUT:
            return
        pelacak = self._tak_terbaca.setdefault(line_code, PelacakTransisi())
        if not pelacak.gagal(sebab):
            return
        if sebab == SEBAB_KUNCI_DITOLAK:
            logger.warning(
                "%s menolak kunci konsol: INTERNAL_SECRET di line itu beda dari yang dipakai konsol (%s)",
                line_code, mentah,
            )
        else:
            logger.warning("%s tidak terbaca oleh konsol (%s): %s", line_code, sebab, mentah)

    def _catat_terbaca_lagi(self, line_code: str) -> None:
        """Satu WARNING saat line yang tadinya dicatat tidak terbaca menjawab lagi, dengan
        lamanya. Kedip di bawah ambang tidak pernah dicatat mulai, jadi tidak pulih juga."""
        self._gagal_beruntun[line_code] = 0
        pelacak = self._tak_terbaca.get(line_code)
        lama = pelacak.pulih() if pelacak is not None else None
        if lama is not None:
            logger.warning("%s terbaca lagi oleh konsol sesudah %s, sudah pulih", line_code, teks_lama(lama))

    def _catat_ai(self, kode: str, ai: dict[str, Any] | None) -> None:
        """AI line mati / tidak lagi mati → satu baris di `docker logs` konsol.

        Sejak batch 3.2 line menyimpan log-nya sendiri (`log_line.db`) dan itu
        yang sampai ke tab Log lewat tarikan log line (aturan 34): baris ERROR/
        WARNING sungguhan sudah dicatat di `PenjagaAi` pada line itu. Cermin di
        sini cuma INFO supaya satu kejadian tidak muncul dua kali di tab Log
        atau dua kali di kelompok Discord (aturan 35).
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
            keadaan = (ai or {}).get("keadaan")
            if keadaan == "sehat":
                logger.info("%s: AI memproses lagi", kode)
            else:
                # Keluar ke frame_berhenti, kamera_putus, lisensi, atau sumber_selesai:
                # AI tetap tidak memproses, jadi bukan "memproses lagi".
                logger.info("%s: AI tidak lagi dinilai mati (keadaan %s)", kode, keadaan or "tidak diketahui")
            self._ai_mati.discard(kode)

    def _catat_frame(self, kode: str, ai: dict[str, Any] | None) -> None:
        """Kamera line tersambung tapi berhenti mengirim (batch 3.6) → satu baris
        di `docker logs` konsol saat masuk dan satu saat keluar, pola `_catat_ai`.

        INFO saja (aturan 35): baris ERROR/WARNING sungguhan sudah dicatat di
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

        INFO saja (aturan 35): baris ERROR/WARNING sungguhan sudah dicatat di
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
        """Upload foto line putus/pulih → satu WARNING konsol per transisi.

        Ringkasan keadaan unggah per line untuk konsol (sama dengan Last Sync), dengan
        alasan dari status line. Rincian per item (item diantre ulang, item racun) tetap
        baris milik line itu sendiri, yang sampai tab Log lewat tarikan log line (aturan
        34). Pulih baru dicatat kalau jam unggah melewati awal putus: line yang restart
        melupakan status gagalnya sampai batch berikutnya, dan itu bukan bukti fotonya
        sudah naik.
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
