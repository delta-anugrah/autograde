"""Offline operator console core (plan §4).

The console is a 4th instance of the same image (`APP_MODE=console`) on port
8000, no camera. Each line writes to its own disk, so the console cannot read
its own disk — it uses the frozen event contract §5 instead: every line gets
`BACKEND_URL=http://localhost:8000` and the existing `OutboxRetryWorker` posts
events here exactly like it does to palmgrade-api (idempotent via uuid5, retry
+ backoff while the console is down). Zero changes in line code, and the local
`palmgrade_api` no longer has to run — the 7 → 4 container cut the plan wants.

Images stay on the line's disk, mounted read-only and served statically. No
directory scanning anywhere (§6.2).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint, Settings
from ..domain.bahaya import HapusBerjalan
from ..domain.ffb_source import ffb_source_label
from ..domain.gerbang import durasi_kunjungan, tahap_tiket
from ..domain.grade_class import grade_class_or_none
from ..domain.jawaban_kunjungan import golongkan
from ..domain.operator_error import (
    BUKAN_ANGKA,
    DI_BAWAH_MINIMUM,
    LINE_TIDAK_DIKENAL,
    NEGATIF,
    TARA_LEBIH_BESAR,
    InvalidInput,
)
from ..domain.plate import normalisasi_plat, truck_id_for
from ..domain.setelan_grading import KUNCI_SETELAN, OPSIONAL, bersihkan_setelan
from ..domain.sinkron import gabung_cloud
from ..domain.vision_event import prediction_for, verdict_of
from ..domain.working_day import JENDELA_KUNJUNGAN_DETIK, awal_kunjungan, work_date_for
from ..integrations.notifications.line_client import LineClient
from ..repositories.console_repository import ConsoleStore
from ..workers.visit_manifest_worker import VisitManifestWorker
from .erp_queue import ErpQueue
from .gerbang_konsol import GerbangKonsol
from .layar_line_support import LayarLineSupport
from .lepas_paksa import LepasPaksa
from .penugasan_otomatis import PenugasanOtomatis
from .status_sinkron import StatusSinkron

logger = logging.getLogger(__name__)

# Net difference still forgiven before a payload is rejected. Scales round;
# anything past this must not pass quietly — net is what the farmer is paid.
NET_TOLERANCE_KG = 1.0

# Below this a figure is not a truck, it is a typo. "14.820" typed for fourteen
# tonnes parses as 14.82 kg, and nothing else in the payload contradicts it.
#
# One tonne, not 100 kg: the old floor let a literal `100` through (the comparison is
# `<`), and that landed on a mill screen as a real ticket — seen 2026-09-15. The
# lightest truck that actually arrives is a Colt Diesel at roughly 2.5 t empty, so one
# tonne still clears every real weighing while catching a thousand-separator slip.
MINIMUM_WEIGHT_KG = 1000.0


class ConsoleService(LayarLineSupport, PenugasanOtomatis, GerbangKonsol, LepasPaksa):
    def __init__(
        self,
        settings: Settings,
        store: ConsoleStore,
        line_client: LineClient,
        *,
        erp_queue: ErpQueue | None = None,
        manifest_queue: VisitManifestWorker | None = None,
        status_sinkron: StatusSinkron | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.lines = settings.console_lines
        self.line_client = line_client
        # None when the console runs without the AutoERP link: everything at the
        # mill still happens, it simply goes nowhere.
        self.erp_queue = erp_queue
        # None when R2 is not configured: no per-truck detail pages, no
        # `detail_url` in what erp_queue sends — but the AutoERP link (if any)
        # still works. See _queue_grading: the two are independent.
        self.manifest_queue = manifest_queue
        # Last Sync (2026-09-27). Dibuat di sini kalau pemanggil tidak memberi, supaya
        # test lama yang merakit ConsoleService sendiri tetap mendapat bagian ini.
        self.status_sinkron = status_sinkron or StatusSinkron(
            store, erp_aktif=bool(settings.erp_url), r2_aktif=bool(settings.r2_bucket)
        )
        # Wired to `LineStatusWorker.snapshot` by console_main.py's lifespan.
        # Default (empty dict) keeps old tests, which never touch the worker,
        # working — every line just shows unreachable instead of crashing.
        self.line_status: Callable[[], dict] = dict
        # Resolved in the constructor on purpose: a bad FACTORY_TZ must kill
        # startup, not quietly file tonnage under the wrong date.
        self.tz = ZoneInfo(settings.factory_tz)
        self._by_machine = {ln.machine_id: ln for ln in self.lines}
        self._by_code = {ln.line_code: ln for ln in self.lines}
        # event_id yang penolakannya sudah di-WARNING di proses ini. Ingest jalan di
        # thread pool (`def` route), jadi dijaga kunci sendiri.
        self._ditolak_diperingatkan: set[str] = set()
        self._kunci_ditolak = threading.Lock()
        # Truk yang sedang ditimbang keluar (id truk -> jumlah timbang keluarnya yang jalan).
        # Selama itu, janjang susulan dan Lepas manual tidak mengantre kunjungan truk itu: tara
        # sudah tersimpan tapi baru sebagian line yang tertaut. Kiriman yang dilewati dicatat
        # (id truk -> {id tiket: penugasan}) dan dikejar sesudahnya. Ingest jalan di thread
        # pool, jadi dijaga kunci sendiri. Urutan kunci: `_kunci_ditutup` lalu kunci
        # `ErpQueue` lalu kunci store; tidak ada yang memegang kunci store atau `ErpQueue`
        # lalu meminta `_kunci_ditutup`.
        self._truk_ditutup: dict[str, int] = {}
        self._tertunda: dict[str, dict[str, str]] = {}
        self._kunci_ditutup = threading.Lock()
        # One automatic assignment at a time (2026-10-01): two weighings landing together
        # would both see the lines free and the second would overwrite the first.
        self._kunci_penugasan = asyncio.Lock()
        # Tickets going onto the lines right now: Lewati refuses them (route runs in a thread).
        self._tiket_dipasang: set[str] = set()
        self._kunci_antrean = threading.Lock()

    # ------------------------------------------------------------ ingest

    def today(self) -> str:
        return self.sekarang().astimezone(self.tz).strftime("%Y-%m-%d")

    def ingest(self, payload: dict[str, Any]) -> str:
        """Take one grading event from a line. Returns its `work_date`.

        ValueError on a malformed payload → route replies 400 → the line's
        outbox keeps the event and retries it every 10 minutes, forever. Rows are
        never dead-lettered, so a line on this image always reports
        `outbox_failed` 0; a line still on an older image may report more than 0.
        Support sees the held event in tab Status → Antrean line ("DITOLAK
        konsol") and, once per event per process, in tab Log. Better held than
        lost, or landed on the wrong day.
        """
        try:
            return self._ingest(payload)
        except ValueError as exc:
            self._catat_ditolak(payload, exc)
            raise

    def _catat_ditolak(self, payload: dict[str, Any], alasan: ValueError) -> None:
        """Satu WARNING per janjang yang ditolak per proses (tab Log), sesudahnya DEBUG.

        Line mencobanya lagi tiap 10 menit selamanya; WARNING tiap kali akan mengulang
        masalah yang sama sepanjang hari. Line sendiri tidak punya log_sink, jadi tanpa
        baris ini penolakannya cuma ada di `docker logs` line.
        """
        event_id = str(payload.get("event_id") or "?")
        line = self._by_machine.get(str(payload.get("machine_id") or "").strip())
        with self._kunci_ditolak:
            baru = event_id not in self._ditolak_diperingatkan
            self._ditolak_diperingatkan.add(event_id)
        logger.log(
            logging.WARNING if baru else logging.DEBUG,
            "Janjang %s dari %s (jam %s) DITOLAK konsol: %s. Line menyimpannya dan mencoba "
            "lagi tiap 10 menit, tapi tidak akan sampai sebelum penyebabnya dibereskan; "
            "selama itu hapus data ditahan (MANUAL §7)",
            event_id, line.line_code if line else payload.get("machine_id"), payload.get("timestamp"), alasan,
        )

    def _ingest(self, payload: dict[str, Any]) -> str:
        event_id = str(payload.get("event_id") or "").strip()
        machine_id = str(payload.get("machine_id") or "").strip()
        timestamp = str(payload.get("timestamp") or "").strip()
        if not (event_id and machine_id and timestamp):
            raise ValueError("event_id, machine_id, dan timestamp wajib diisi")

        # The one figure the mill is paid on is summed out of this field, so an
        # unknown value must stop here rather than land in `total` and in
        # neither `acc` nor `rej`.
        verdict = verdict_of(payload.get("ripeness_status"))
        prediction = payload.get("prediction")
        if prediction and prediction != prediction_for(verdict):
            raise ValueError(
                f"prediction {prediction!r} bertentangan dengan ripeness_status {verdict!r}"
            )

        # §6.1: computed HERE from the event timestamp, once, then stored.
        work_date = work_date_for(timestamp, self.tz)

        line = self._by_machine.get(machine_id)
        baru = self.store.add_inspection(
            {
                "event_id": event_id,
                "machine_id": machine_id,
                # Unknown machine is stored as-is: the row shows up as a
                # foreign line, far quicker to spot than a swallowed event.
                "line_code": line.line_code if line else machine_id,
                "work_date": work_date,
                "timestamp": timestamp,
                "ripeness_status": verdict,
                "ripeness_confidence": payload.get("ripeness_confidence"),
                "capture_type": str(payload.get("capture_type") or "auto"),
                "image_path": payload.get("image_path"),
                "truck_id": payload.get("truck_id"),
                "assignment_id": payload.get("assignment_id"),
                # Passed through as the line sent it — ERP requires it, and
                # deriving it here too would be a second rule that can drift.
                # Checked against the verdict above, never rebuilt from it.
                "prediction": prediction,
                # Detail 4 kelas di samping verdict biner. Kelas asing di sini
                # TIDAK menolak event — beda dengan `ripeness_status`, yang
                # dijumlah jadi angka bayaran. Ini cuma label buat layar, dan
                # menjatuhkan satu janjang gara-gara label baru dari model yang
                # dilatih ulang jauh lebih mahal daripada menyimpannya NULL.
                "grade_class": grade_class_or_none(payload.get("grade_class")),
                "tp_status": payload.get("tp_status"),
                "tp_confidence": payload.get("tp_confidence"),
            }
        )
        if baru:
            self._kunjungan_susulan(payload.get("assignment_id"))
        return work_date

    # ------------------------------------------------------------- read

    def state(self) -> dict[str, Any]:
        work_date = self.today()
        summary = {row["line_code"]: row for row in self.store.summary(work_date)}
        assignments = self.store.assignments()
        status_line = self.line_status()
        lines = [
            {
                "line_code": ln.line_code,
                "name": ln.name,
                "port": ln.port,
                "total": summary.get(ln.line_code, {}).get("total", 0),
                "acc": summary.get(ln.line_code, {}).get("acc", 0) or 0,
                "rej": summary.get(ln.line_code, {}).get("rej", 0) or 0,
                # Rincian 4 kelas di samping verdict biner di atas. `acc`/`rej`
                # sengaja tetap dikirim: rasio dan warna kartu dihitung darinya,
                # dan baris lama (grade_class NULL) cuma punya itu.
                **{
                    k: summary.get(ln.line_code, {}).get(k, 0) or 0
                    for k in ("ripe", "unripe", "jk", "tp", "tanpa_kelas")
                },
                "assignment": _assignment_view(assignments.get(ln.line_code)),
                # Tanpa `unggah`: kartu tidak memakainya, dan blok itu membawa `pesan`
                # galat mentah. Ringkasannya sampai ke layar lewat `sinkron`.
                "plc": {
                    k: v for k, v in status_line.get(ln.line_code, {"reachable": False}).items()
                    if k != "unggah"
                },
            }
            for ln in self.lines
        ]
        # Foreign lines (machine_id not in the registry) are shown too.
        lines += [
            {"line_code": code, "name": f"? {code}", "port": None,
             "total": row["total"], "acc": row["acc"] or 0, "rej": row["rej"] or 0,
             "assignment": None}
            for code, row in summary.items() if code not in self._by_code
        ]
        return {
            "work_date": work_date,
            "timezone": self.settings.factory_tz,
            "lines": lines,
            # Ringkasan timbangan hari kerja ini untuk strip "Hari ini". Dari
            # tabel yang sama dengan tab Timbangan, jadi begitu program timbangan
            # tersambung angkanya ikut tanpa perubahan layar.
            "timbangan": self.store.ringkasan_timbangan(work_date),
            # Line yang dilepas oleh timbang keluar, bukan oleh operator (G5).
            # Ditampilkan supaya pelepasannya terlihat: kalau bongkar ternyata
            # belum habis, operator masih bisa meng-assign ulang.
            "auto_releases": self.store.auto_releases_terbaru(),
            # Antrean bongkar di atas kartu line (2026-10-01), di polling 2 detik yang sama:
            # yang perlu melihatnya operator yang sedang memegang tombol line.
            "antrean_bongkar": self.antrean_bongkar(),
            "penugasan_otomatis": {
                k: v for k, v in self.penugasan_otomatis().items() if k != "lines_tersedia"
            },
            # Menumpang polling 2 detik ini, bukan endpoint sendiri: yang melihat
            # sambungan putus itu operator biasa (alasan sama dengan banner lisensi).
            "sinkron": self._sinkron_aman(),
        }

    def _sinkron_aman(self) -> dict[str, Any] | None:
        """Last Sync yang gagal dibaca cukup kosong di layar (`isiSinkron` melewatinya):
        polling ini melayani seluruh layar operator, bukan cuma bagian itu."""
        try:
            return self.sinkron()
        except Exception:
            logger.exception("Last Sync tidak terbaca; bagian itu dikosongkan di layar")
            return None

    def sinkron(self) -> dict[str, Any]:
        """Last Sync: AutoERP dan Cloud Photo, siap digambar layar (`domain/sinkron.py`).

        Antrean AutoERP = pesan yang belum terkirim + yang gagal dan menunggu giliran
        ulang. Cloud Photo menggabungkan cek R2 dan manifest dari konsol dengan blok
        `unggah` yang dilaporkan tiap line lewat `/internal/status`.
        """
        antre_erp = 0
        if self.settings.erp_url and self.erp_queue is not None:
            antre_erp = self.erp_queue.outbox.pending_count() + self.erp_queue.outbox.failed_count()
        antre_manifest = 0
        if self.manifest_queue is not None:
            antre_manifest = (
                self.manifest_queue.outbox.pending_count() + self.manifest_queue.outbox.failed_count()
            )
        lines = {
            ln.line_code: (st.get("unggah") if st.get("reachable") else None)
            for ln in self.lines
            for st in [self.line_status().get(ln.line_code) or {}]
        }
        return {
            "autoerp": self.status_sinkron.ringkas("erp", antre=antre_erp),
            "cloud": gabung_cloud(self.status_sinkron.ringkas("r2", antre=antre_manifest), lines),
        }

    def history(
        self,
        work_date: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self.store.inspections(
            work_date, line_code=line_code, truck_id=truck_id,
            limit=min(limit, 200), offset=offset,
        )
        for row in rows:
            row["image_url"] = _capture_url(row.get("line_code"), row.get("image_path"))
            _with_source_label(row)
        return rows

    def history_halaman(
        self,
        work_date: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """One page of grading plus how many rows the filter matches in total.

        The total is what lets the screen say "51-75 of 812" and know whether there is a
        next page at all. Without it the only honest thing a page can show is "more",
        and the operator cannot tell a full last page from a list that keeps going.
        """
        return {
            "items": self.history(
                work_date, line_code=line_code, truck_id=truck_id,
                limit=limit, offset=offset,
            ),
            "total": self.store.inspection_count(
                work_date, line_code=line_code, truck_id=truck_id
            ),
        }

    def trucks(self) -> list[dict[str, Any]]:
        # `di_lokasi` (batch 5.6): weighed in, not yet out. The screen lists those first.
        di_lokasi = self.store.trucks_with_open_ticket(awal_kunjungan(self.sekarang()))
        return [{**_with_source_label(r), "di_lokasi": r["id"] in di_lokasi} for r in self.store.trucks()]

    def weighings(self, work_date: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.tandai_tanpa_scan_4(self.store.weighings(work_date, limit=limit)) + self.kunjungan_terbawa(work_date)
        return [_tiket_view(row) for row in rows]

    def recap(self, work_date: str) -> list[dict[str, Any]]:
        """Per-truck tally with the weighbridge neto folded in.

        Neto is summed here rather than joined in SQL: a truck can hold more
        than one ticket in a day, and joining that to the grading rows would
        multiply the bunch count by the ticket count.
        """
        net_by_truck: dict[str, float] = {}
        for ticket in self.store.weighings(work_date, limit=500):
            truck, amount = ticket.get("truck_id"), ticket.get("net_kg")
            if truck and amount is not None:
                net_by_truck[truck] = round(net_by_truck.get(truck, 0.0) + amount, 3)
        rows = self.store.truck_recap(work_date)
        for row in rows:
            row["net_kg"] = net_by_truck.get(row.get("truck_id"))
            _with_source_label(row)
        return rows

    # --------------------------------------------------- manual truck entry

    def register_manual_truck(
        self, plate_number: str, *, supplier_id: str | None = None, capacity: float | None = None
    ) -> dict[str, Any]:
        """Borrowed or unregistered truck, typed in by the operator.

        The id is uuid5 of the normalised plate, so the same plate typed again
        tomorrow lands on the same truck. `status='manual'` marks a row the ERP
        has not confirmed yet.

        Since the master pull moved to AutoERP the two id spaces deliberately
        MEET: AutoERP normalises a plate the same way, so a pulled truck lands
        on this exact row and adopts it instead of creating a twin that would
        split the day's tonnage. The pull never clears `erp_name` either, so an
        operator retyping a linked plate cannot unlink it.

        A truck AutoERP already owns is read-only here (contract §4, FE-1):
        retyping its plate returns the row untouched. Overwriting it wiped the
        supplier, and with it the source label on every grading row of that
        truck — the label is read from the truck, never copied onto the row.

        A truck AutoERP has not got goes up through the outbox (interface B).
        """
        plate = (plate_number or "").strip()
        truck_id = truck_id_for(plate)  # ValueError on an empty plate → route replies 400
        owned_by_erp = self.store.truck(truck_id) or {}
        if owned_by_erp.get("erp_name"):
            return {
                "id": truck_id,
                "plate_number": owned_by_erp["plate_number"],
                "status": owned_by_erp["status"],
            }

        self.store.upsert_truck(
            {
                "id": truck_id,
                "plate_number": plate,
                "supplier_id": supplier_id,
                "capacity": capacity,
                "status": "manual",
            }
        )
        if self.erp_queue is not None:
            self.erp_queue.truck(plate)
        return {"id": truck_id, "plate_number": plate, "status": "manual"}

    # --------------------------------------------------------- scale (§3.5c)

    async def record_weighing(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One payload from the scale program. Returns the merged row.

        The shape the boss asked for: weight before unloading (gross), weight
        after (tare), and the difference (net). The scale's own format is not
        known yet (X1) — what is frozen here is OUR shape, so once the format
        arrives it needs an adapter, not a table rewrite.

        `net_kg` is ALWAYS computed, never trusted as sent. If the sender
        includes it and it differs past the tolerance → ValueError → 400. The
        number that gets paid must not quietly come from two sources.
        """
        plate = str(payload.get("plate_number") or "").strip()
        plate_norm = normalisasi_plat(plate)
        ref = str(payload.get("ref") or "").strip() or None
        entered_at = str(payload.get("entered_at") or "").strip() or None
        exited_at = str(payload.get("exited_at") or "").strip() or None

        if not (ref or entered_at):
            # Without one of them, weigh-out cannot find its weigh-in row and
            # one ticket splits into two.
            raise ValueError("ref atau entered_at wajib diisi")
        reference_time = entered_at or exited_at
        if reference_time is None:
            raise ValueError("entered_at atau exited_at wajib diisi")
        work_date = work_date_for(reference_time, self.tz)

        cache_key = f"timbangan:{ref}" if ref else f"timbangan:{plate_norm}:{entered_at}"
        weighing_id = str(uuid.uuid5(uuid.NAMESPACE_URL, cache_key))

        # ponytail: read-then-write, no transaction. Scale payloads are sparse
        # (two per truck) and uvicorn runs one process — move to
        # UPDATE...RETURNING if a second sender ever appears.
        existing = self.store.weighing(weighing_id) or {}
        gross = _kg(payload.get("gross_kg"), "gross_kg", existing.get("gross_kg"))
        tare = _kg(payload.get("tare_kg"), "tare_kg", existing.get("tare_kg"))
        for field_name, number in (("gross_kg", gross), ("tare_kg", tare)):
            if number is not None and number < MINIMUM_WEIGHT_KG:
                raise InvalidInput(
                    DI_BAWAH_MINIMUM,
                    f"{field_name} ({number}) di bawah {MINIMUM_WEIGHT_KG} kg - "
                    "cek pemisah ribuan, mis. 14.820 terbaca jadi 14,82",
                    field=field_name,
                    value=number,
                    minimum=MINIMUM_WEIGHT_KG,
                )
        net = _neto(gross, tare, _kg(payload.get("net_kg"), "net_kg", None))

        truck_id = truck_id_for(plate)
        menutup = tare is not None or bool(exited_at)
        bertaut: dict[str, str] = {}
        tertunda: dict[str, str] = {}
        # The guard goes up BEFORE the tare is written: from that write on, a visit queued
        # for this truck would carry a tare that not every line is linked to yet.
        if menutup:
            self._mulai_tutup(truck_id)
        try:
            self.store.upsert_weighing(
                {
                    "id": weighing_id,
                    "ref": ref,
                    "plate_number": plate,
                    "plate_norm": plate_norm,
                    "truck_id": truck_id,
                    "work_date": work_date,
                    "gross_kg": gross,
                    "tare_kg": tare,
                    "net_kg": net,
                    "entered_at": entered_at,
                    "exited_at": exited_at,
                }
            )
            # Scan 1: a NEW ticket claims its truck's arrival (never fails the weighing).
            self._klaim_kedatangan(not existing and gross is not None, truck_id, entered_at, weighing_id)
            # Timbang keluar = truk sudah pergi. Line yang masih memegangnya akan
            # menstempel janjang truk BERIKUTNYA dengan truk ini (G5), jadi dilepas
            # di sini alih-alih menunggu operator ingat.
            if menutup:
                bertaut = await self._lepas_line_truk_yang_keluar(truck_id)
        finally:
            if menutup:
                # Before the queue below: a bunch that saw the guard is stored by now, so the
                # message built from the store counts it; one that comes later queues it itself.
                tertunda = self._selesai_tutup(truck_id)
        # ONE message, after every line is released and linked: the tare is stored already,
        # so a message queued between two releases would carry it with only the lines
        # released so far, and AutoERP finalises a ticket the moment it has both. Plus every
        # visit that was held back meanwhile, whichever ticket it belongs to.
        halaman = {**tertunda, **bertaut}
        for tiket in {weighing_id, *halaman}:
            self._queue_visit(tiket)
        # The pages last: the visit never depends on the page.
        for tiket, assignment_id in halaman.items():
            self._antre_halaman(tiket, assignment_id)
        # Automatic line assignment (2026-10-01), only after everything above is queued and
        # outside the weigh-out guard: a new ticket may go straight onto the lines, and a
        # weigh-out just freed them for the next truck in the unloading queue.
        dipasang = await self.isi_line_otomatis()
        return {**(self.store.weighing(weighing_id) or {}), "dipasang": dipasang}

    # ------------------------------------------------------ send to AutoERP

    async def _lepas_line_truk_yang_keluar(self, truck_id: str) -> dict[str, str]:
        """Truk sudah timbang keluar: lepaskan setiap line yang masih memegangnya.

        Mengembalikan tiket yang tertaut ke line yang berhasil dilepas (id tiket ke
        penugasan pertamanya), dan TIDAK mengantre apa pun ke AutoERP: tiap line dilepas
        dengan `kirim=False`, dan pemanggil mengantre sekali sesudah semuanya.

        Tanpa ini, `Release` yang terlewat membuat line terus menstempel truk yang
        sudah pulang ke janjang truk berikutnya — tonase yang dibayar ke petani,
        mendarat di baris yang salah, tanpa apa pun di layar. Timeout 6 jam di
        AutoERP tetap memfinalisasi tiketnya, jadi kegagalannya tidak pernah
        terlihat sebagai kegagalan: angkanya saja yang salah.

        Semua line, bukan yang pertama: satu truk boleh dibongkar paralel.
        """
        bertaut: dict[str, str] = {}
        for pegangan in self.store.assignments_for_truck(truck_id):
            line_code = pegangan["line_code"]
            try:
                await self.release_truck(line_code, kirim=False)
            except Exception:
                # Line tidak menjawab. Jangan gagalkan penimbangannya — berat itu
                # angka yang dibayar dan harus tetap tersimpan. Yang hilang hanya
                # pelepasan otomatisnya; operator masih bisa menekan Release, dan
                # barisnya sengaja tidak ditulis supaya layar tidak menjanjikan
                # sesuatu yang tidak terjadi.
                logger.exception("Auto-release gagal untuk %s", line_code)
                continue
            self.store.record_auto_release(
                line_code=line_code,
                truck_id=truck_id,
                plate_number=pegangan.get("plate_number"),
                assignment_id=pegangan.get("assignment_id"),
            )
            tiket = self.store.weighing_for_assignment(pegangan["assignment_id"])
            if tiket:
                bertaut.setdefault(tiket, pegangan["assignment_id"])
        return bertaut

    def _mulai_tutup(self, truck_id: str) -> None:
        with self._kunci_ditutup:
            self._truk_ditutup[truck_id] = self._truk_ditutup.get(truck_id, 0) + 1

    def _selesai_tutup(self, truck_id: str) -> dict[str, str]:
        """Turunkan penjaga; kalau ini timbang keluar terakhir truk itu, kembalikan kiriman
        yang dilewati selama penjaga naik (id tiket -> penugasan) supaya pemanggil mengantrenya."""
        with self._kunci_ditutup:
            sisa = self._truk_ditutup.get(truck_id, 0) - 1
            if sisa > 0:
                self._truk_ditutup[truck_id] = sisa
                return {}
            self._truk_ditutup.pop(truck_id, None)
            return self._tertunda.pop(truck_id, {})

    def _tunda_kalau_ditutup(self, weighing_id: str, assignment_id: str) -> bool:
        """Truk tiket ini sedang ditimbang keluar: catat kiriman ini untuk sesudahnya dan
        jawab True. Dipanggil dengan `_kunci_ditutup` dipegang."""
        if not self._truk_ditutup:
            return False
        truck_id = (self.store.weighing(weighing_id) or {}).get("truck_id")
        if truck_id not in self._truk_ditutup:
            return False
        self._tertunda.setdefault(truck_id, {})[weighing_id] = assignment_id
        return True

    def _queue_visit(self, weighing_id: str) -> None:
        """A weighbridge row moved: AutoERP gets the whole visit as it stands."""
        if self.erp_queue is not None:
            self.erp_queue.visit(weighing_id, tz=self.tz)

    def _queue_grading(self, closing: dict[str, Any], *, kirim: bool = True) -> None:
        """The line assignment just closed, so its bunches belong to that truck's
        visit — the link is written here, once, and never guessed at send time.

        `kirim=False` writes the link and queues nothing: the weigh-out releases every
        line of the truck, and its caller queues the visit once when the last one is done.
        """
        truck_id, assignment_id = closing.get("truck_id"), closing.get("assignment_id")
        if not (truck_id and assignment_id):
            return
        # A window, not today's work date: the date flips at midnight, a visit does not.
        weighing_id = self.store.latest_weighing_for_truck_since(
            truck_id, time.time() - JENDELA_KUNJUNGAN_DETIK
        )
        if not weighing_id:
            # No ticket for this truck in the window. Nothing links this assignment later
            # (the weigh-in and the daily resend only read links that exist), so whatever
            # it graded reaches no visit: say so in the Log tab instead of losing it quietly.
            hitungan = self.store.grading_counts(assignment_id)
            if hitungan:
                logger.warning(
                    "Penugasan %s di %s (truk %s) dilepas dengan %s janjang, tapi tidak ada tiket "
                    "timbangan truk itu dalam %s jam terakhir: janjangnya TIDAK masuk kunjungan "
                    "mana pun dan tidak terkirim ke AutoERP",
                    assignment_id, closing.get("line_code"),
                    closing.get("plate_number") or truck_id, hitungan["total"],
                    JENDELA_KUNJUNGAN_DETIK // 3600,
                )
            return
        self.store.link_weighing_to_assignment(weighing_id, assignment_id, closing.get("line_code"))
        if kirim:
            self._kirim_kunjungan(weighing_id, assignment_id)

    def _antre_halaman(self, weighing_id: str, assignment_id: str) -> None:
        """Halaman detail kunjungan ini ke antrean R2 (diganti kalau barisnya masih menunggu).

        The detail page does not depend on the AutoERP link: a mill with R2 but no
        ERP_URL still gets its per-truck pages. The reverse holds too: the visit is
        queued before the page, and a page that cannot be queued is logged, never raised.
        """
        if self.manifest_queue is None:
            return
        try:
            self.manifest_queue.enqueue(weighing_id, assignment_id)
        except Exception:
            logger.exception(
                "Halaman detail tiket %s (penugasan %s) TIDAK diantre ke R2; kunjungannya ke "
                "AutoERP tetap diantre, halaman detailnya belum terbentuk",
                weighing_id, assignment_id,
            )

    def _kirim_kunjungan(self, weighing_id: str, assignment_id: str) -> None:
        """Pesan kunjungan dan halaman detail untuk tiket yang sudah bertaut ke penugasannya.

        Dilewati selama truk tiket ini sedang ditimbang keluar: janjang dan tautannya sudah
        tersimpan, dan timbang keluar mengantre kunjungan utuh sesudah line terakhir lepas.
        Pengecekan penjaga dan pembacaan store untuk pesan itu satu langkah di bawah
        `_kunci_ditutup`: timbang keluar tidak bisa menaikkan penjaga dan menulis tara di antaranya.
        """
        with self._kunci_ditutup:
            if self._tunda_kalau_ditutup(weighing_id, assignment_id):
                return
            if self.erp_queue is not None:
                self.erp_queue.visit(weighing_id, tz=self.tz)
        self._antre_halaman(weighing_id, assignment_id)

    def _kunjungan_susulan(self, assignment_id: str | None) -> None:
        """Janjang yang tiba SESUDAH truknya dilepas (batch 2.3): kirim ulang kunjungannya.

        Pesannya dibangun ulang dari store (`ErpQueue.visit`), jadi hitungannya ikut
        janjang yang baru masuk. Selama kiriman sebelumnya belum berangkat, baris
        antrean yang sama diganti dan AutoERP hanya menerima angka yang lengkap. Kalau
        tiketnya sudah final, AutoERP tidak menulis ulang apa pun; jawabannya ditandai
        di tab Timbangan dan tab Log (`domain/jawaban_kunjungan.py`).
        """
        if not assignment_id:
            return
        weighing_id = self.store.weighing_for_assignment(assignment_id)
        if not weighing_id:
            return
        try:
            self._kirim_kunjungan(weighing_id, assignment_id)
        except Exception:
            # Janjangnya SUDAH tersimpan. Menjawab 500 cuma membuat line mengirim ulang,
            # kiriman ulang itu duplikat (tidak mengantre apa pun), dan kunjungan ini
            # tidak pernah diantre ulang tanpa satu kalimat pun yang menyebutnya.
            logger.exception(
                "Janjang susulan tersimpan, tapi kunjungan tiket %s (penugasan %s) TIDAK "
                "diantre ulang ke AutoERP. Tiket hari kerja ini dibawa kirim ulang harian "
                "besok; tiket yang lebih lama tidak, rekapnya di AutoERP kurang janjang ini",
                weighing_id, assignment_id,
            )

    # ------------------------------------------------------- line commands

    def _ffb_source(self, truck_id: str) -> str | None:
        """AutoERP label for this truck, or None while it cannot be determined yet."""
        truck = self.store.truck(truck_id) or {}
        return ffb_source_label(
            has_supplier=bool(truck.get("supplier_id")),
            in_erp=bool(truck.get("erp_name")),
        )

    def _plate(self, truck_id: str) -> str | None:
        """Display label for the line's capture folders, or None if unknown.

        Never an identifier: `truck_id` carries every number that matters, so a
        truck the store cannot read costs readability and nothing more.
        """
        truck = self.store.truck(truck_id) or {}
        return truck.get("plate_number") or None

    async def assign_truck(self, line_code: str, truck_id: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        if self.store.hapus_berjalan:
            # Danger Zone sedang mengosongkan data: penugasan yang dicatat sekarang
            # ikut terhapus, dan janjangnya tidak pernah tertaut ke tiket.
            raise HapusBerjalan()
        assignment_id = str(uuid.uuid4())
        # Line first, then store. If the line does not answer, DO NOT record:
        # a screen showing a truck assigned while the line knows nothing makes
        # the operator think it is done, and the next event ships with no
        # truck. A failure has to look like one. The line lock spans both steps (Lepas paksa).
        async with self.kunci_line(line_code):
            await self.line_client.assign_truck(
                line,
                assignment_id=assignment_id,
                truck_id=truck_id,
                assigned_at=datetime.now(self.tz).isoformat(),
                ffb_source=self._ffb_source(truck_id),
                plate=self._plate(truck_id),
            )
            # Stored, not kept in memory (§6.4): the truck being unloaded must stay
            # on its line after a console restart mid-shift.
            self.store.set_assignment(line_code, assignment_id, truck_id)
        return {"assignment_id": assignment_id, "truck_id": truck_id, "line_code": line_code}

    async def release_truck(self, line_code: str, *, kirim: bool = True) -> dict[str, Any]:
        """Truck done unloading and gone. Line first, then record (§13, like assign).

        `kirim=True` (the operator's Lepas, one line): the visit and its detail page are
        queued at once. `kirim=False` links the grading and queues nothing, for the
        weigh-out, which releases all of the truck's lines and queues the visit once after.

        Without this an assignment never ends: the line keeps stamping the truck
        that already left onto the next bunches, and that tonnage lands on the
        wrong truck with nothing on screen to show it. Empty goes out as an
        empty string because the `/internal/assignment` contract is frozen — the
        line turns it into `None` (`schemas/internal_schema.py`).
        """
        line = self._require_line(line_code)
        closing = self.store.assignments().get(line_code) or {}
        await self.line_client.assign_truck(
            line,
            assignment_id="",
            truck_id="",
            assigned_at=datetime.now(self.tz).isoformat(),
            ffb_source=None,
        )
        self._catat_lepas(line_code, closing, kirim=kirim)  # shared with Lepas paksa
        return {"line_code": line_code, "truck_id": None}

    def penugasan_untuk_mesin(self, machine_id: str) -> dict[str, Any]:
        """Penugasan yang tersimpan untuk satu line, supaya LINE bisa menariknya
        saat dia start.

        Pasangan `assign_truck`, arah sebaliknya. `assign_truck` mendorong saat
        operator menekan tombol; ini menjawab saat line yang bertanya. Dua-duanya
        perlu: konsol tidak tahu kapan sebuah line selesai boot, dan line tidak
        tahu truk mana yang sedang dibongkar.

        Tanpa ini, container line yang dibuat ulang di tengah shift kehilangan
        truknya diam-diam — layar tetap menampilkan platnya (konsol membaca DB),
        tapi janjang berikutnya tersimpan dengan `assignment_id` kosong dan tidak
        pernah masuk rekap yang dibayar. Terbukti di Lampung 2026-09-23.

        Line yang tidak dikenal dan line yang truknya sudah Lepas sama-sama
        menjawab penugasan kosong, bukan error: "tidak ada truk" itu jawaban yang
        sah, dan line yang menolak start gara-gara belum ditugaskan akan membuat
        pabrik berhenti karena keadaan yang normal.
        """
        line = self._by_machine.get(machine_id)
        kosong = {"assignment_id": "", "truck_id": "", "ffb_source": None, "plate": None}
        if line is None:
            return kosong
        row = self.store.assignments().get(line.line_code) or {}
        assignment_id = str(row.get("assignment_id") or "")
        truck_id = str(row.get("truck_id") or "")
        if not (assignment_id and truck_id):
            return kosong
        return {
            "assignment_id": assignment_id,
            "truck_id": truck_id,
            "ffb_source": self._ffb_source(truck_id),
            "plate": self._plate(truck_id),
            # Jam penugasan ASLI, bukan jam line start: folder capture dinamai
            # sekali per truk, jadi menyegarkannya akan memecah satu truk jadi
            # dua folder di tengah pembongkaran.
            "assigned_at": datetime.fromtimestamp(
                float(row.get("started_at") or 0), self.tz
            ).isoformat() if row.get("started_at") else None,
        }

    # ------------------------------------------------------ setelan grading

    def setelan_grading(self) -> dict[str, Any]:
        """Setelan yang tersimpan di konsol, atau nilai `.env` kalau belum pernah
        diubah. Konsol yang memegang kebenarannya — line cuma menerima salinan."""
        tersimpan = self.store.get_state(KUNCI_SETELAN)
        if tersimpan:
            nilai = json.loads(tersimpan)
            # Baris yang disimpan SEBELUM `garis_capture` ada tidak punya field
            # itu. Dilengkapi di sini, bukan dibiarkan hilang: layar yang
            # menerima `undefined` akan mengirim balik payload cacat saat
            # operator menyimpan setelan lain.
            return {**OPSIONAL, **nilai, "sumber": "konsol"}
        return {
            **OPSIONAL,
            "conf_threshold": self.settings.conf_threshold,
            "minimum_size": self.settings.minimum_size,
            "garis_capture": self.settings.garis_capture,
            "sumbu_garis": self.settings.sumbu_garis,
            "mode_dev": self.settings.mode_dev,
            "sumber": "env",
        }

    async def simpan_setelan_grading(
        self, payload: dict[str, Any], *, diubah_oleh: str
    ) -> dict[str, Any]:
        """Simpan dulu, baru sebar. Urutannya sengaja begini.

        Kalau disebar dulu lalu disimpan, line yang sempat menerima nilai baru
        akan memakainya sementara konsol masih memegang nilai lama — dan saat
        line itu restart, konsol mengirim balik nilai lama tanpa ada yang sadar.
        Menyimpan lebih dulu membuat konsol selalu jadi sumber kebenaran.

        Line yang tidak menjawab TIDAK membatalkan penyimpanan: nilainya sudah
        sah, tinggal line itu yang belum menerimanya. Hasil per line dikembalikan
        apa adanya supaya layar bisa bilang line mana yang belum kena.
        """
        bersih = bersihkan_setelan(payload, stream=(self.settings.stream_width, self.settings.stream_height))
        self.store.set_state(KUNCI_SETELAN, json.dumps(bersih))
        logger.warning(
            "Setelan grading diubah oleh %s: conf=%s minimum_size=%s garis=%s sumbu=%s",
            diubah_oleh, bersih["conf_threshold"], bersih["minimum_size"],
            bersih["garis_capture"], bersih["sumbu_garis"],
        )

        hasil = []
        for line in self.lines:
            try:
                await self.line_client.kirim_setelan(line, **bersih)
                hasil.append({"line_code": line.line_code, "terkirim": True})
            except Exception as exc:  # LineUnavailable / LinePlcTolak / apa pun
                logger.warning("Setelan belum sampai ke %s: %s", line.line_code, exc)
                hasil.append(
                    {"line_code": line.line_code, "terkirim": False, "alasan": str(exc)[:200]}
                )
        return {**bersih, "sumber": "konsol", "lines": hasil}

    async def manual_reject(self, line_code: str, requested_by: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        current = self.store.assignments().get(line_code) or {}
        await self.line_client.manual_reject(
            line,
            assignment_id=current.get("assignment_id") or "",
            requested_by=requested_by,
            requested_at=datetime.now(self.tz).isoformat(),
        )
        return {"accepted": True, "line_code": line_code}

    async def piston(self, line_code: str, open: bool, *, requested_by: str) -> dict[str, Any]:
        """Forward the piston request to the line, in the name of whoever pressed it.

        Logged BEFORE the call: this moves hardware, and a press on a line that
        does not answer is exactly the one somebody asks about later.
        """
        line = self._require_line(line_code)
        logger.warning(
            "Piston %s %s oleh %s", line_code, "dibuka" if open else "ditutup", requested_by
        )
        await self.line_client.set_piston(
            line, open=open, requested_by=requested_by,
            requested_at=datetime.now(self.tz).isoformat(),
        )
        return {"line_code": line_code, "open": open}

    def _require_line(self, line_code: str) -> LineEndpoint:
        line = self._by_code.get(line_code)
        if line is None:
            raise InvalidInput(
                LINE_TIDAK_DIKENAL, f"line tidak dikenal: {line_code}", line=line_code
            )
        return line


def _kg(value: Any, field_name: str, default: float | None) -> float | None:
    """Kilogram figure, or `default` when not sent. ValueError if malformed."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        # A comma is the decimal point on an Indonesian keypad, and the scale
        # program may well send one. Only one separator is ever accepted, so a
        # thousands-grouped "14.820,5" still fails loudly instead of silently
        # becoming 14.82.
        value = value.strip().replace(",", ".")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(
            BUKAN_ANGKA, f"{field_name} bukan angka: {value!r}", field=field_name, value=str(value)
        ) from exc
    if number < 0:
        raise InvalidInput(
            NEGATIF, f"{field_name} tidak boleh negatif: {number}", field=field_name, value=number
        )
    return number


def _neto(gross: float | None, tare: float | None, sent: float | None) -> float | None:
    if gross is None or tare is None:
        if sent is not None:
            raise ValueError("net_kg dikirim tanpa gross_kg + tare_kg")
        return None
    if tare > gross:
        raise InvalidInput(
            TARA_LEBIH_BESAR,
            f"tare_kg ({tare}) lebih besar dari gross_kg ({gross})",
            tara=tare,
            bruto=gross,
        )
    computed = round(gross - tare, 3)
    if sent is not None and abs(sent - computed) > NET_TOLERANCE_KG:
        raise ValueError(f"net_kg tidak cocok: dikirim {sent}, gross-tare {computed}")
    return computed


def _source_label(row: dict[str, Any]) -> str | None:
    """Label from the store's source facts, popped so they never reach the API."""
    return ffb_source_label(
        has_supplier=bool(row.pop("has_supplier", 0)),
        in_erp=bool(row.pop("in_erp", 0)),
    )


def _with_source_label(row: dict[str, Any]) -> dict[str, Any]:
    """Replace the source facts with the display label (§3.5b).

    Pop first, then assign: `{**row, ...}` evaluates before `pop`, and that
    once leaked raw columns into the API response.
    """
    row["source_label"] = _source_label(row)
    return row


def _tiket_view(row: dict[str, Any]) -> dict[str, Any]:
    """One Timbangan row: the source label, and whether AutoERP's last answer for this
    visit needs a human (batch 2.3), the queue and total minutes and the stage (standard L4).
    Computed here so the screen never parses AutoERP's sentences or adds up clocks."""
    row["erp_perlu_dicek"] = golongkan(row.get("erp_note"))
    row.update(durasi_kunjungan(row), tahap=tahap_tiket(row))
    return _with_source_label(row)


def _assignment_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    # A row with an empty truck_id = truck already released. The row stays on
    # purpose (the line's assignment history), but the screen must say "none".
    if not row or not row.get("truck_id"):
        return None
    return {
        "assignment_id": row["assignment_id"],
        "truck_id": row["truck_id"],
        "plate_number": row.get("plate_number"),
        "supplier_name": row.get("supplier_name"),
        "source_label": _source_label(row),
    }


def _capture_url(line_code: str | None, image_path: str | None) -> str | None:
    """Mirrors `resolveCaptureUrl` in palmgrade-api — the shape must match.

    Absolute URLs (R2, from the batch upload lane) pass through as-is.
    """
    if image_path and image_path.lower().startswith(("http://", "https://")):
        return image_path
    if not image_path or not line_code:
        return None
    rel = image_path.lstrip("/").removeprefix("captures/").lstrip("/")
    return f"/captures/{line_code}/{rel}"
