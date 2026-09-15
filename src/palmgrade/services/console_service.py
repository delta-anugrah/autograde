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

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint, Settings
from ..domain.ffb_source import ffb_source_label
from ..domain.operator_error import (
    BUKAN_ANGKA,
    DI_BAWAH_MINIMUM,
    LINE_TIDAK_DIKENAL,
    NEGATIF,
    TARA_LEBIH_BESAR,
    InvalidInput,
)
from ..domain.plate import normalisasi_plat, truck_id_for
from ..domain.vision_event import prediction_for, verdict_of
from ..domain.working_day import tanggal_kerja_for
from ..integrations.notifications.line_client import LineClient
from ..repositories.console_repository import ConsoleStore
from .erp_queue import ErpQueue

logger = logging.getLogger(__name__)

# Net difference still forgiven before a payload is rejected. Scales round;
# anything past this must not pass quietly — neto is what the farmer is paid.
TOLERANSI_NETO_KG = 1.0

# Below this a figure is not a truck, it is a typo. "14.820" typed for fourteen
# tonnes parses as 14.82 kg, and nothing else in the payload contradicts it.
# An empty truck already weighs tonnes, so a real bruto/tara clears this by two
# orders of magnitude.
MINIMUM_BERAT_KG = 100.0


class ConsoleService:
    def __init__(
        self,
        settings: Settings,
        store: ConsoleStore,
        line_client: LineClient,
        *,
        erp_queue: ErpQueue | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.lines = settings.console_lines
        self._line_client = line_client
        # None when the console runs without the AutoERP link: everything at the
        # mill still happens, it simply goes nowhere.
        self.erp_queue = erp_queue
        # Resolved in the constructor on purpose: a bad FACTORY_TZ must kill
        # startup, not quietly file tonnage under the wrong date.
        self.tz = ZoneInfo(settings.factory_tz)
        self._by_machine = {ln.machine_id: ln for ln in self.lines}
        self._by_code = {ln.line_code: ln for ln in self.lines}

    # ------------------------------------------------------------ ingest

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def ingest(self, payload: dict[str, Any]) -> str:
        """Take one grading event from a line. Returns its `tanggal_kerja`.

        ValueError on a malformed payload → route replies 400 → the line's
        outbox holds the event and marks it `outbox_failed`. Better visible as
        a failure than lost, or landed on the wrong day.
        """
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
        tanggal = tanggal_kerja_for(timestamp, self.tz)

        line = self._by_machine.get(machine_id)
        self.store.add_inspection(
            {
                "event_id": event_id,
                "machine_id": machine_id,
                # Unknown machine is stored as-is: the row shows up as a
                # foreign line, far quicker to spot than a swallowed event.
                "line_code": line.line_code if line else machine_id,
                "tanggal_kerja": tanggal,
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
                "tp_status": payload.get("tp_status"),
                "tp_confidence": payload.get("tp_confidence"),
            }
        )
        return tanggal

    # ------------------------------------------------------------- read

    def state(self) -> dict[str, Any]:
        tanggal = self.today()
        summary = {row["line_code"]: row for row in self.store.summary(tanggal)}
        assignments = self.store.assignments()
        lines = [
            {
                "line_code": ln.line_code,
                "name": ln.name,
                "port": ln.port,
                "total": summary.get(ln.line_code, {}).get("total", 0),
                "acc": summary.get(ln.line_code, {}).get("acc", 0) or 0,
                "rej": summary.get(ln.line_code, {}).get("rej", 0) or 0,
                "assignment": _assignment_view(assignments.get(ln.line_code)),
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
            "tanggal_kerja": tanggal,
            "timezone": self.settings.factory_tz,
            "lines": lines,
            "recent": self.history(tanggal, limit=20),
        }

    def history(
        self,
        tanggal_kerja: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self.store.inspections(
            tanggal_kerja, line_code=line_code, truck_id=truck_id,
            limit=min(limit, 200), offset=offset,
        )
        for row in rows:
            row["image_url"] = _capture_url(row.get("line_code"), row.get("image_path"))
            _with_source_label(row)
        return rows

    def trucks(self) -> list[dict[str, Any]]:
        return [_with_source_label(row) for row in self.store.trucks()]

    def weighings(self, tanggal_kerja: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return [_with_source_label(row) for row in self.store.weighings(tanggal_kerja, limit=limit)]

    def rekap(self, tanggal_kerja: str) -> list[dict[str, Any]]:
        """Per-truck tally with the weighbridge neto folded in.

        Neto is summed here rather than joined in SQL: a truck can hold more
        than one ticket in a day, and joining that to the grading rows would
        multiply the bunch count by the ticket count.
        """
        neto: dict[str, float] = {}
        for tiket in self.store.weighings(tanggal_kerja, limit=500):
            truk, angka = tiket.get("truck_id"), tiket.get("neto_kg")
            if truk and angka is not None:
                neto[truk] = round(neto.get(truk, 0.0) + angka, 3)
        rows = self.store.rekap_truk(tanggal_kerja)
        for row in rows:
            row["neto_kg"] = neto.get(row.get("truck_id"))
            _with_source_label(row)
        return rows

    # --------------------------------------------------- manual truck entry

    def daftar_truk_manual(
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
        plat = (plate_number or "").strip()
        truck_id = truck_id_for(plat)  # ValueError on an empty plate → route replies 400
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
                "plate_number": plat,
                "supplier_id": supplier_id,
                "capacity": capacity,
                "status": "manual",
            }
        )
        if self.erp_queue is not None:
            self.erp_queue.truck(plat)
        return {"id": truck_id, "plate_number": plat, "status": "manual"}

    # --------------------------------------------------------- scale (§3.5c)

    def catat_timbangan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One payload from the scale program. Returns the merged row.

        The shape the boss asked for: weight before unloading (bruto), weight
        after (tara), and the difference (neto). The scale's own format is not
        known yet (X1) — what is frozen here is OUR shape, so once the format
        arrives it needs an adapter, not a table rewrite.

        `neto_kg` is ALWAYS computed, never trusted as sent. If the sender
        includes it and it differs past the tolerance → ValueError → 400. The
        number that gets paid must not quietly come from two sources.
        """
        plat = str(payload.get("plate_number") or "").strip()
        plat_norm = normalisasi_plat(plat)
        ref = str(payload.get("ref") or "").strip() or None
        waktu_masuk = str(payload.get("waktu_masuk") or "").strip() or None
        waktu_keluar = str(payload.get("waktu_keluar") or "").strip() or None

        if not (ref or waktu_masuk):
            # Without one of them, weigh-out cannot find its weigh-in row and
            # one ticket splits into two.
            raise ValueError("ref atau waktu_masuk wajib diisi")
        acuan = waktu_masuk or waktu_keluar
        if acuan is None:
            raise ValueError("waktu_masuk atau waktu_keluar wajib diisi")
        tanggal = tanggal_kerja_for(acuan, self.tz)

        kunci = f"timbangan:{ref}" if ref else f"timbangan:{plat_norm}:{waktu_masuk}"
        weighing_id = str(uuid.uuid5(uuid.NAMESPACE_URL, kunci))

        # ponytail: read-then-write, no transaction. Scale payloads are sparse
        # (two per truck) and uvicorn runs one process — move to
        # UPDATE...RETURNING if a second sender ever appears.
        lama = self.store.weighing(weighing_id) or {}
        bruto = _kg(payload.get("bruto_kg"), "bruto_kg", lama.get("bruto_kg"))
        tara = _kg(payload.get("tara_kg"), "tara_kg", lama.get("tara_kg"))
        for nama, angka in (("bruto_kg", bruto), ("tara_kg", tara)):
            if angka is not None and angka < MINIMUM_BERAT_KG:
                raise InvalidInput(
                    DI_BAWAH_MINIMUM,
                    f"{nama} ({angka}) di bawah {MINIMUM_BERAT_KG} kg - "
                    "cek pemisah ribuan, mis. 14.820 terbaca jadi 14,82",
                    field=nama,
                    value=angka,
                    minimum=MINIMUM_BERAT_KG,
                )
        neto = _neto(bruto, tara, _kg(payload.get("neto_kg"), "neto_kg", None))

        self.store.upsert_weighing(
            {
                "id": weighing_id,
                "ref": ref,
                "plate_number": plat,
                "plate_norm": plat_norm,
                "truck_id": truck_id_for(plat),
                "tanggal_kerja": tanggal,
                "bruto_kg": bruto,
                "tara_kg": tara,
                "neto_kg": neto,
                "waktu_masuk": waktu_masuk,
                "waktu_keluar": waktu_keluar,
            }
        )
        self._queue_visit(weighing_id)
        return self.store.weighing(weighing_id) or {}

    # ------------------------------------------------------ send to AutoERP

    def _queue_visit(self, weighing_id: str) -> None:
        """A weighbridge row moved: AutoERP gets the whole visit as it stands."""
        if self.erp_queue is not None:
            self.erp_queue.visit(weighing_id, tz=self.tz)

    def _queue_grading(self, closing: dict[str, Any]) -> None:
        """The line assignment just closed, so its bunches belong to that truck's
        visit — the link is written here, once, and never guessed at send time.
        """
        if self.erp_queue is None:
            return
        truck_id, assignment_id = closing.get("truck_id"), closing.get("assignment_id")
        if not (truck_id and assignment_id):
            return
        hari = tanggal_kerja_for(datetime.now(self.tz).isoformat(), self.tz)
        weighing_id = self.store.latest_weighing_for_truck(truck_id, hari)
        if not weighing_id:
            # Nothing weighed yet. AutoERP dates a ticket from `time_in`, so this
            # visit goes up when the weighing does — or on the daily resend.
            return
        self.store.link_weighing_to_assignment(weighing_id, assignment_id)
        self.erp_queue.visit(weighing_id, tz=self.tz)

    # ------------------------------------------------------- line commands

    def _ffb_source(self, truck_id: str) -> str | None:
        """Label AutoERP untuk truk ini, atau None kalau belum bisa ditentukan."""
        truk = self.store.truck(truck_id) or {}
        return ffb_source_label(
            has_supplier=bool(truk.get("supplier_id")),
            in_erp=bool(truk.get("erp_name")),
        )

    async def assign_truck(self, line_code: str, truck_id: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        assignment_id = str(uuid.uuid4())
        # Line first, then store. If the line does not answer, DO NOT record:
        # a screen showing a truck assigned while the line knows nothing makes
        # the operator think it is done, and the next event ships with no
        # truck. A failure has to look like one.
        await self._line_client.assign_truck(
            line,
            assignment_id=assignment_id,
            truck_id=truck_id,
            assigned_at=datetime.now(self.tz).isoformat(),
            ffb_source=self._ffb_source(truck_id),
        )
        # Stored, not kept in memory (§6.4): the truck being unloaded must stay
        # on its line after a console restart mid-shift.
        self.store.set_assignment(line_code, assignment_id, truck_id)
        return {"assignment_id": assignment_id, "truck_id": truck_id, "line_code": line_code}

    async def lepas_truk(self, line_code: str) -> dict[str, Any]:
        """Truck done unloading and gone. Line first, then record (§13, like assign).

        Without this an assignment never ends: the line keeps stamping the truck
        that already left onto the next bunches, and that tonnage lands on the
        wrong truck with nothing on screen to show it. Empty goes out as an
        empty string because the `/internal/assignment` contract is frozen — the
        line turns it into `None` (`schemas/internal_schema.py`).
        """
        line = self._require_line(line_code)
        closing = self.store.assignments().get(line_code) or {}
        await self._line_client.assign_truck(
            line,
            assignment_id="",
            truck_id="",
            assigned_at=datetime.now(self.tz).isoformat(),
            ffb_source=None,
        )
        self.store.set_assignment(line_code, "", None)
        self._queue_grading(closing)
        return {"line_code": line_code, "truck_id": None}

    async def manual_reject(self, line_code: str, requested_by: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        current = self.store.assignments().get(line_code) or {}
        await self._line_client.manual_reject(
            line,
            assignment_id=current.get("assignment_id") or "",
            requested_by=requested_by,
            requested_at=datetime.now(self.tz).isoformat(),
        )
        return {"accepted": True, "line_code": line_code}

    def _require_line(self, line_code: str) -> LineEndpoint:
        line = self._by_code.get(line_code)
        if line is None:
            raise InvalidInput(
                LINE_TIDAK_DIKENAL, f"line tidak dikenal: {line_code}", line=line_code
            )
        return line


def _kg(nilai: Any, nama: str, bawaan: float | None) -> float | None:
    """Kilogram figure, or `bawaan` when not sent. ValueError if malformed."""
    if nilai is None or nilai == "":
        return bawaan
    if isinstance(nilai, str):
        # A comma is the decimal point on an Indonesian keypad, and the scale
        # program may well send one. Only one separator is ever accepted, so a
        # thousands-grouped "14.820,5" still fails loudly instead of silently
        # becoming 14.82.
        nilai = nilai.strip().replace(",", ".")
    try:
        angka = float(nilai)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(
            BUKAN_ANGKA, f"{nama} bukan angka: {nilai!r}", field=nama, value=str(nilai)
        ) from exc
    if angka < 0:
        raise InvalidInput(
            NEGATIF, f"{nama} tidak boleh negatif: {angka}", field=nama, value=angka
        )
    return angka


def _neto(bruto: float | None, tara: float | None, dikirim: float | None) -> float | None:
    if bruto is None or tara is None:
        if dikirim is not None:
            raise ValueError("neto_kg dikirim tanpa bruto_kg + tara_kg")
        return None
    if tara > bruto:
        raise InvalidInput(
            TARA_LEBIH_BESAR,
            f"tara_kg ({tara}) lebih besar dari bruto_kg ({bruto})",
            tara=tara,
            bruto=bruto,
        )
    hitung = round(bruto - tara, 3)
    if dikirim is not None and abs(dikirim - hitung) > TOLERANSI_NETO_KG:
        raise ValueError(f"neto_kg tidak cocok: dikirim {dikirim}, bruto-tara {hitung}")
    return hitung


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
    row["sumber_label"] = _source_label(row)
    return row


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
        "sumber_label": _source_label(row),
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
