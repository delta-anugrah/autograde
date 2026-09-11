"""Otak konsol operator offline (§4 rencana PalmOS).

Konsol adalah instance ke-4 dari image yang sama (`APP_MODE=console`), berdiri
di port 8000 tanpa kamera. Tiga line kamera menulis ke disk-nya masing-masing,
jadi konsol TIDAK bisa "membaca disknya sendiri" — yang dipakai justru kontrak
event beku §5: tiap line di-set `BACKEND_URL=http://localhost:8000`, lalu
`OutboxRetryWorker` yang sudah ada mengirim event ke sini persis seperti ke
palmgrade-api (idempoten lewat uuid5, retry + backoff kalau konsol mati). Nol
perubahan di kode line, dan `palmgrade_api` lokal tidak perlu hidup lagi —
inilah pengurangan 7 → 4 container yang diminta rencana.

Gambar tetap di disk line, di-mount read-only ke konsol dan di-serve statis.
Tidak ada pemindaian direktori di mana pun (§6.2).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint, Settings
from ..domain.plat import normalisasi_plat, truck_id_for
from ..domain.sumber_tbs import label_sumber
from ..domain.tanggal_kerja import tanggal_kerja_for
from ..integrations.notifications.line_client import LineClient
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

MASTER_CURSOR_KEY = "master_data_cursor"

# Selisih neto yang masih dimaafkan sebelum kiriman ditolak. Timbangan
# membulatkan, kita tidak boleh diam saja kalau selisihnya lebih dari itu:
# neto adalah angka yang dibayar ke petani.
TOLERANSI_NETO_KG = 1.0


class ConsoleService:
    def __init__(self, settings: Settings, store: ConsoleStore, line_client: LineClient) -> None:
        self.settings = settings
        self.store = store
        self.lines = settings.console_lines
        self._line_client = line_client
        # Sengaja resolve di konstruktor: FACTORY_TZ ngawur harus membunuh
        # startup, bukan diam-diam menaruh tonase di tanggal yang salah.
        self.tz = ZoneInfo(settings.factory_tz)
        self._by_machine = {ln.machine_id: ln for ln in self.lines}
        self._by_code = {ln.line_code: ln for ln in self.lines}

    # ------------------------------------------------------------ ingest

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def ingest(self, payload: dict[str, Any]) -> str:
        """Terima satu event grading dari line. Return `tanggal_kerja`-nya.

        ValueError untuk payload cacat → route membalas 400 → outbox line
        menahan event itu dan menandainya `outbox_failed`. Lebih baik terlihat
        sebagai kegagalan daripada hilang atau mendarat di hari yang salah.
        """
        event_id = str(payload.get("event_id") or "").strip()
        machine_id = str(payload.get("machine_id") or "").strip()
        timestamp = str(payload.get("timestamp") or "").strip()
        if not (event_id and machine_id and timestamp):
            raise ValueError("event_id, machine_id, dan timestamp wajib diisi")

        # §6.1: dihitung DI SINI dari timestamp event, sekali, lalu disimpan.
        tanggal = tanggal_kerja_for(timestamp, self.tz)

        line = self._by_machine.get(machine_id)
        self.store.add_inspection(
            {
                "event_id": event_id,
                "machine_id": machine_id,
                # machine tak dikenal tetap disimpan apa adanya: barisnya muncul
                # di layar sebagai line asing, jauh lebih cepat ketahuan
                # daripada event yang ditelan diam-diam.
                "line_code": line.line_code if line else machine_id,
                "tanggal_kerja": tanggal,
                "timestamp": timestamp,
                "ripeness_status": str(payload.get("ripeness_status") or "").upper(),
                "ripeness_confidence": payload.get("ripeness_confidence"),
                "capture_type": str(payload.get("capture_type") or "auto"),
                "image_path": payload.get("image_path"),
                "truck_id": payload.get("truck_id"),
                "assignment_id": payload.get("assignment_id"),
                # Diteruskan apa adanya — ERP mewajibkannya dan menolak nilai di
                # luar {Acc, Rej}. Line yang menghitungnya (`vision_event.py`),
                # konsol cuma membawa.
                "prediction": payload.get("prediction"),
                "tp_status": payload.get("tp_status"),
                "tp_confidence": payload.get("tp_confidence"),
            }
        )
        return tanggal

    # ------------------------------------------------------------- baca

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
        # Line asing (machine_id tak cocok registry) ikut ditampilkan.
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
            _label_sumber_in_place(row)
        return rows

    def trucks(self) -> list[dict[str, Any]]:
        return [_label_sumber_in_place(row) for row in self.store.trucks()]

    def weighings(self, tanggal_kerja: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return [_label_sumber_in_place(row) for row in self.store.weighings(tanggal_kerja, limit=limit)]

    # ------------------------------------------------- truk daftar manual

    def daftar_truk_manual(
        self, plate_number: str, *, supplier_id: str | None = None, capacity: float | None = None
    ) -> dict[str, Any]:
        """Truk pinjaman / belum terdaftar, diketik operator di konsol.

        Id-nya uuid5 dari plat ternormalisasi, jadi plat yang sama diketik ulang
        besok mendarat di truk yang sama. `status='manual'` membedakannya dari
        truk hasil sinkron master — id master datang dari cloud, jadi keduanya
        tidak akan pernah bertabrakan kunci.

        Sengaja BELUM didorong ke ERP: DocType `Truck` belum ada di site mana
        pun (docs/PERTANYAAN-TERBUKA.md S3). Barisnya hidup lokal dulu.
        """
        plat = (plate_number or "").strip()
        truck_id = truck_id_for(plat)  # ValueError kalau plat kosong → route balas 400
        self.store.upsert_truck(
            {
                "id": truck_id,
                "plate_number": plat,
                "supplier_id": supplier_id,
                "capacity": capacity,
                "status": "manual",
            }
        )
        return {"id": truck_id, "plate_number": plat, "status": "manual"}

    # ----------------------------------------------------- timbangan (§3.5c)

    def catat_timbangan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Satu kiriman dari program timbangan. Return baris hasil gabungnya.

        Bentuk yang diminta bos: berat sebelum proses (bruto), berat sesudah
        (tara), dan selisihnya (neto). Formatnya sendiri belum diketahui (X1) —
        yang dibekukan di sini bentuk KITA, jadi begitu formatnya turun cukup
        tambah adapter, bukan bongkar tabel.

        `neto_kg` SELALU dihitung, tidak pernah dipercaya mentah-mentah. Kalau
        pengirim menyertakannya dan bedanya lewat toleransi → ValueError → 400.
        Angka yang dibayar tidak boleh berasal dari dua sumber yang beda diam-diam.
        """
        plat = str(payload.get("plate_number") or "").strip()
        plat_norm = normalisasi_plat(plat)
        ref = str(payload.get("ref") or "").strip() or None
        waktu_masuk = str(payload.get("waktu_masuk") or "").strip() or None
        waktu_keluar = str(payload.get("waktu_keluar") or "").strip() or None

        if not (ref or waktu_masuk):
            # Tanpa salah satunya, timbang-keluar tidak punya cara menemukan
            # baris timbang-masuknya dan satu tiket pecah jadi dua.
            raise ValueError("ref atau waktu_masuk wajib diisi")
        acuan = waktu_masuk or waktu_keluar
        if acuan is None:
            raise ValueError("waktu_masuk atau waktu_keluar wajib diisi")
        tanggal = tanggal_kerja_for(acuan, self.tz)

        kunci = f"timbangan:{ref}" if ref else f"timbangan:{plat_norm}:{waktu_masuk}"
        weighing_id = str(uuid.uuid5(uuid.NAMESPACE_URL, kunci))

        # ponytail: baca-lalu-tulis tanpa transaksi. Kiriman timbangan sepi
        # (dua per truk), satu proses uvicorn — pindahkan ke UPDATE...RETURNING
        # kalau nanti ada pengirim kedua.
        lama = self.store.weighing(weighing_id) or {}
        bruto = _kg(payload.get("bruto_kg"), "bruto_kg", lama.get("bruto_kg"))
        tara = _kg(payload.get("tara_kg"), "tara_kg", lama.get("tara_kg"))
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
        return self.store.weighing(weighing_id) or {}

    # ------------------------------------------------------ perintah line

    async def assign_truck(self, line_code: str, truck_id: str) -> dict[str, Any]:
        line = self._require_line(line_code)
        assignment_id = str(uuid.uuid4())
        # Line dulu, baru simpan. Kalau line tidak menjawab, JANGAN dicatat:
        # layar yang menampilkan truk terpasang padahal line tidak tahu apa-apa
        # membuat operator mengira sudah beres, dan event berikutnya terkirim
        # tanpa truk. Gagal harus kelihatan sebagai gagal.
        await self._line_client.assign_truck(
            line,
            assignment_id=assignment_id,
            truck_id=truck_id,
            assigned_at=datetime.now(self.tz).isoformat(),
        )
        # Disimpan, bukan ditaruh di memori (§6.4): truk yang sedang dibongkar
        # harus tetap nempel di line-nya setelah konsol restart di tengah shift.
        self.store.set_assignment(line_code, assignment_id, truck_id)
        return {"assignment_id": assignment_id, "truck_id": truck_id, "line_code": line_code}

    async def lepas_truk(self, line_code: str) -> dict[str, Any]:
        """Truk selesai bongkar dan pergi. Line dulu, baru dicatat (§13, sama dengan assign).

        Tanpa ini penugasan tidak pernah berakhir: line terus menempelkan truk
        yang sudah pulang ke tandan berikutnya, dan tonasenya mendarat di truk
        yang salah tanpa satu pun tanda di layar. Kosong dikirim sebagai string
        kosong karena kontrak `/internal/assignment` beku — line yang mengubahnya
        jadi `None` (`schemas/internal_schema.py`).
        """
        line = self._require_line(line_code)
        await self._line_client.assign_truck(
            line, assignment_id="", truck_id="", assigned_at=datetime.now(self.tz).isoformat()
        )
        self.store.set_assignment(line_code, "", None)
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
            raise ValueError(f"line tidak dikenal: {line_code}")
        return line


def _kg(nilai: Any, nama: str, bawaan: float | None) -> float | None:
    """Angka kilogram, atau `bawaan` kalau tidak dikirim. ValueError kalau ngawur."""
    if nilai is None or nilai == "":
        return bawaan
    try:
        angka = float(nilai)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nama} bukan angka: {nilai!r}") from exc
    if angka < 0:
        raise ValueError(f"{nama} tidak boleh negatif: {angka}")
    return angka


def _neto(bruto: float | None, tara: float | None, dikirim: float | None) -> float | None:
    if bruto is None or tara is None:
        if dikirim is not None:
            raise ValueError("neto_kg dikirim tanpa bruto_kg + tara_kg")
        return None
    if tara > bruto:
        raise ValueError(f"tara_kg ({tara}) lebih besar dari bruto_kg ({bruto})")
    hitung = round(bruto - tara, 3)
    if dikirim is not None and abs(dikirim - hitung) > TOLERANSI_NETO_KG:
        raise ValueError(f"neto_kg tidak cocok: dikirim {dikirim}, bruto-tara {hitung}")
    return hitung


def _label_sumber_in_place(row: dict[str, Any]) -> dict[str, Any]:
    """Tukar `sumber` mentah dengan labelnya saja (§3.5b).

    Pop DULU, baru assign. `{**row, "sumber_label": label(row.pop(...))}` pernah
    membocorkan nilai mentahnya ke respons API karena `**row` dievaluasi lebih
    dulu daripada `pop` — bug yang cuma ketahuan lewat test.
    """
    row["sumber_label"] = label_sumber(row.pop("sumber", None))
    return row


def _assignment_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    # Baris dengan truck_id kosong = truk sudah dilepas. Barisnya sengaja tetap
    # ada (riwayat penugasan line), tapi layar harus bilang "belum ada".
    if not row or not row.get("truck_id"):
        return None
    return {
        "assignment_id": row["assignment_id"],
        "truck_id": row["truck_id"],
        "plate_number": row.get("plate_number"),
        "supplier_name": row.get("supplier_name"),
        "sumber_label": label_sumber(row.get("sumber")),
    }


def _capture_url(line_code: str | None, image_path: str | None) -> str | None:
    """Cermin `resolveCaptureUrl` di palmgrade-api — bentuknya harus sama.

    URL absolut (R2, dari jalur batch upload) diteruskan apa adanya.
    """
    if image_path and image_path.lower().startswith(("http://", "https://")):
        return image_path
    if not image_path or not line_code:
        return None
    rel = image_path.lstrip("/").removeprefix("captures/").lstrip("/")
    return f"/captures/{line_code}/{rel}"
