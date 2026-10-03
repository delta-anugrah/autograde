"""Truk yang dibongkar di dua line sampai ke AutoERP, halaman detail, dan tab Log UTUH."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import erp_messages
from palmgrade.domain.plate import normalisasi_plat
from palmgrade.domain.working_day import JENDELA_KUNJUNGAN_DETIK
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import _konteks
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

WIB = ZoneInfo("Asia/Jakarta")
PLAT = "BE 1 AA"


class FakeLine:
    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None):
        return None


class FakeUploader:
    def put_bytes(self, body, r2_key, *, content_type):
        return None


def _konsol(tmp_path, *, line=None, manifest_queue=None, store_cls=ConsoleStore):
    store = store_cls(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"), store, line or FakeLine(),
        erp_queue=ErpQueue(store, outbox), manifest_queue=manifest_queue,
    )
    return service, store, outbox


@pytest.fixture
def pabrik(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck = service.register_manual_truck(PLAT)
    # The ticket is found through the truck's newest weigh-in, so it is weighed in now.
    row = asyncio.run(service.record_weighing(
        {"plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat()}
    ))
    return service, store, outbox, truck["id"], row["id"]


def _janjang(service, line_code: str, n: int, *, awal: int = 0) -> None:
    assignment_id = service.store.assignments()[line_code]["assignment_id"]
    for i in range(awal, awal + n):
        service.store.add_inspection({
            "event_id": f"{line_code}-{i}", "machine_id": f"m-{line_code}", "line_code": line_code,
            "work_date": service.today(), "timestamp": f"{service.today()}T01:{i:02d}:00+07:00",
            "ripeness_status": "ACC", "ripeness_confidence": 0.9, "capture_type": "auto",
            "image_path": None, "truck_id": None, "assignment_id": assignment_id,
            "prediction": "Acc", "tp_status": None, "tp_confidence": None,
        })


def _kiriman_terakhir(outbox, weighing_id):
    pesan = [m for m in outbox.due(50) if m.kind == erp_messages.VISIT and m.key == weighing_id]
    return pesan[-1].payload


def _bongkar_dua_line(service, truck_id):
    for line in ("line-1", "line-2"):
        asyncio.run(service.assign_truck(line, truck_id))
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    for line in ("line-1", "line-2"):
        asyncio.run(service.release_truck(line))


def test_truk_di_dua_line_terkirim_utuh_ke_autoerp(pabrik):
    service, _, outbox, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    grading = _kiriman_terakhir(outbox, wid)["grading"]
    assert grading["counts"]["total"] == 5, "cuma satu line yang terkirim ke AutoERP"


def test_janjang_susulan_line_pertama_ikut_terkirim(pabrik):
    """Janjang yang tiba sesudah line-1 dilepas mengantre ulang kunjungannya. Dulu cuma
    penugasan line yang dilepas TERAKHIR yang menemukan tiketnya."""
    service, store, outbox, truck_id, wid = pabrik
    for line in ("line-1", "line-2"):
        asyncio.run(service.assign_truck(line, truck_id))
    aid_line1 = store.assignments()["line-1"]["assignment_id"]
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    for line in ("line-1", "line-2"):
        asyncio.run(service.release_truck(line))

    # Lewat jalur ingest sungguhan: dia yang memanggil `_kunjungan_susulan`.
    service.ingest({
        "event_id": "susulan-1", "machine_id": service.lines[0].machine_id,
        "timestamp": datetime.now(WIB).isoformat(), "ripeness_status": "REJ",
        "assignment_id": aid_line1, "truck_id": truck_id,
    })

    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 6


def _penugasan(store, weighing_id):
    with store._lock:  # noqa: SLF001 (test reads the link table directly)
        rows = store._db.execute(  # noqa: SLF001
            "SELECT assignment_id FROM visit_assignments WHERE weighing_id = ? ORDER BY linked_at",
            (weighing_id,),
        ).fetchall()
    return [r["assignment_id"] for r in rows]


def test_line_tercatat_di_tautan(pabrik):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    assert len(_penugasan(store, wid)) == 2
    with store._lock:  # noqa: SLF001 (test reads the link table directly)
        lines = store._db.execute(  # noqa: SLF001
            "SELECT line_code FROM visit_assignments WHERE weighing_id = ? ORDER BY line_code", (wid,)
        ).fetchall()
    assert [r["line_code"] for r in lines] == ["line-1", "line-2"]
    assert store.grading_counts_for_visit(wid)["line_code"] == "line-1, line-2"


def test_halaman_detail_memuat_janjang_dua_line(pabrik, tmp_path):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html></html>")
    worker = VisitManifestWorker(
        store, ErpOutboxStore(tmp_path / "m.db"), FakeUploader(),
        public_url="https://captures.example", viewer_html=viewer, clock=lambda: "2026-10-01T09:00:00+07:00",
    )
    manifest = json.loads(worker._build(wid, {"assignment_id": "apa-saja"}))
    assert manifest["counts"]["total"] == 5
    assert len(manifest["bunches"]) == 5


def test_baris_log_menyebut_semua_line(pabrik):
    service, store, _, truck_id, wid = pabrik
    _bongkar_dua_line(service, truck_id)
    konteks = _konteks(store, wid, {}, WIB)
    assert konteks.janjang == 5
    assert konteks.line == "line-1, line-2"


# ---- Tiket ditemukan lewat jendela waktu, bukan hari kerja (lintas tengah malam) ----

def _tiket_lampau(store, truck_id: str, jam_lalu: float, *, wid: str) -> str:
    """A ticket weighed in `jam_lalu` hours ago, filed under YESTERDAY's work date, as one
    weighed in at 23:30 is once the clock passes midnight."""
    sekarang = datetime.now(WIB)
    masuk = sekarang - timedelta(hours=jam_lalu)
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": PLAT, "plate_norm": normalisasi_plat(PLAT),
        "truck_id": truck_id, "work_date": (sekarang - timedelta(days=1)).strftime("%Y-%m-%d"),
        "gross_kg": 14000.0, "tare_kg": None, "net_kg": None,
        "entered_at": masuk.isoformat(), "exited_at": None,
    })
    with store._lock, store._db:  # noqa: SLF001 (the clock the window reads is not settable)
        store._db.execute(  # noqa: SLF001
            "UPDATE weighings SET received_at = ? WHERE id = ?", (time.time() - jam_lalu * 3600, wid)
        )
    return wid


def test_jendela_kunjungan_dua_belas_jam():
    assert JENDELA_KUNJUNGAN_DETIK == 12 * 60 * 60


def test_tiket_sebelum_tengah_malam_tertaut_saat_dilepas_sesudahnya(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    wid = _tiket_lampau(store, truck_id, 1.0, wid="w-semalam")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    asyncio.run(service.release_truck("line-1"))

    assert len(_penugasan(store, wid)) == 1
    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 3


def test_tiket_tiga_belas_jam_lalu_tidak_ditautkan(tmp_path):
    service, store, outbox = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    wid = _tiket_lampau(store, truck_id, 13.0, wid="w-kemarin")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    asyncio.run(service.release_truck("line-1"))

    assert _penugasan(store, wid) == []
    assert [m for m in outbox.due(50) if m.kind == erp_messages.VISIT] == []


def test_dua_tiket_dalam_jendela_tertaut_ke_yang_terbaru(tmp_path):
    service, store, _ = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    lama = _tiket_lampau(store, truck_id, 3.0, wid="w-lama")
    baru = _tiket_lampau(store, truck_id, 1.0, wid="w-baru")
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 2)

    asyncio.run(service.release_truck("line-1"))

    assert len(_penugasan(store, baru)) == 1
    assert _penugasan(store, lama) == []


# ---- Dilepas tanpa tiket: janjangnya tidak boleh hilang tanpa satu kalimat pun ----

LOGGER = "palmgrade.services.console_service"


def test_lepas_dengan_janjang_tanpa_tiket_dalam_jendela_mencatat_peringatan(tmp_path, caplog):
    service, store, _ = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    _tiket_lampau(store, truck_id, 13.0, wid="w-kemarin")
    asyncio.run(service.assign_truck("line-1", truck_id))
    penugasan = store.assignments()["line-1"]["assignment_id"]
    _janjang(service, "line-1", 3)

    with caplog.at_level("WARNING", logger=LOGGER):
        asyncio.run(service.release_truck("line-1"))

    [catatan] = [r for r in caplog.records if r.levelname == "WARNING"]
    pesan = catatan.getMessage()
    assert PLAT in pesan and "line-1" in pesan and penugasan in pesan
    assert "3 janjang" in pesan and "12 jam" in pesan


def test_lepas_tanpa_janjang_dan_tanpa_tiket_tidak_mencatat_peringatan(tmp_path, caplog):
    """Nothing was graded, so nothing is lost: a warning here would only teach the operator
    to ignore the Log tab."""
    service, _, _ = _konsol(tmp_path)
    truck_id = service.register_manual_truck(PLAT)["id"]
    asyncio.run(service.assign_truck("line-1", truck_id))

    with caplog.at_level("WARNING", logger=LOGGER):
        asyncio.run(service.release_truck("line-1"))

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


def test_lepas_dengan_tiket_tidak_mencatat_peringatan(pabrik, caplog):
    service, _, _, truck_id, _ = pabrik
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 2)

    with caplog.at_level("WARNING", logger=LOGGER):
        asyncio.run(service.release_truck("line-1"))

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


# ---- Timbang keluar: AutoERP menerima kunjungan SEKALI, sesudah semua line dilepas ----

class _LineMengintip(FakeLine):
    """A line that looks at the AutoERP queue each time it is told to let a truck go: what the
    outbox worker would find if it woke up between two releases of the same weigh-out."""

    def __init__(self) -> None:
        self.lihat = lambda: []
        self.potret: list[list[dict]] = []
        #: (which release, what happens during it): runs just before that release is looked at,
        #: like a bunch or an operator's click landing while the weigh-out awaits its line.
        self.selama = None
        self._pelepasan = 0

    async def assign_truck(self, line, *, assignment_id, **kw):
        if assignment_id == "":
            self._pelepasan += 1
            if self.selama is not None and self._pelepasan == self.selama[0]:
                kerja, self.selama = self.selama[1], None
                await kerja()
            self.potret.append(self.lihat())


class _CatatHalaman:
    def __init__(self) -> None:
        self.dipanggil: list[tuple[str, str]] = []

    def enqueue(self, weighing_id: str, assignment_id: str) -> None:
        self.dipanggil.append((weighing_id, assignment_id))


def _timbang_keluar_tiga_line(tmp_path, *, manifest_queue=None, selama=None):
    """Weigh in, three lines take the truck (3 + 2 + 4 bunches), weigh out with the tare.

    `selama=(n, kerja)`: `await kerja(service, truck_id, penugasan)` while the n-th release is
    awaiting its line, `penugasan` being each line's assignment id before the weigh-out."""
    line = _LineMengintip()
    service, store, outbox = _konsol(tmp_path, line=line, manifest_queue=manifest_queue)
    line.lihat = lambda: [m.payload for m in outbox.due(50) if m.kind == erp_messages.VISIT]
    truck_id = service.register_manual_truck(PLAT)["id"]
    tiket = asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat(),
    }))
    for kode in ("line-1", "line-2", "line-3"):
        asyncio.run(service.assign_truck(kode, truck_id))
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    _janjang(service, "line-3", 4)
    line.potret.clear()
    if selama is not None:
        penugasan = {k: v["assignment_id"] for k, v in store.assignments().items()}
        urutan, kerja = selama
        line.selama = (urutan, lambda: kerja(service, truck_id, penugasan))
    asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "tare_kg": 5000, "exited_at": datetime.now(WIB).isoformat(),
    }))
    return service, store, outbox, line, tiket["id"]


def test_timbang_keluar_tidak_mengantre_kunjungan_setengah_jadi(tmp_path):
    """The weigh-out stores the tare, then lets the lines go one by one, and each release
    awaits its line. A drain of the AutoERP queue in between would send the tare with only
    the lines released so far, and AutoERP finalises a ticket at once (a deduction taken
    from one line). So no queued visit may carry the tare before every line is released."""
    _, _, outbox, line, wid = _timbang_keluar_tiga_line(tmp_path)

    assert len(line.potret) == 3, "ketiga line harus dilepas"
    for urutan, antrean in enumerate(line.potret, start=1):
        assert [p for p in antrean if "tare_kg" in p["weighing"]] == [], (
            f"kunjungan dengan tara sudah di antrean saat line ke-{urutan} dilepas"
        )
    akhir = _kiriman_terakhir(outbox, wid)
    assert akhir["weighing"]["tare_kg"] == 5000
    assert akhir["grading"]["counts"]["total"] == 9


def test_timbang_keluar_mengantre_halaman_detail_sekali_sesudah_semua_line(tmp_path):
    halaman = _CatatHalaman()

    _, store, _, _, wid = _timbang_keluar_tiga_line(tmp_path, manifest_queue=halaman)

    assert [w for w, _ in halaman.dipanggil] == [wid]
    assert halaman.dipanggil[0][1] == store.grading_counts_for_visit(wid)["assignment_id"]


def test_lepas_manual_satu_line_tetap_mengantre_kunjungannya_langsung(tmp_path):
    """The operator's Lepas is one line, nothing else follows it: it queues at once."""
    halaman = _CatatHalaman()
    line = _LineMengintip()
    service, _, outbox = _konsol(tmp_path, line=line, manifest_queue=halaman)
    truck_id = service.register_manual_truck(PLAT)["id"]
    tiket = asyncio.run(service.record_weighing({
        "plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat(),
    }))
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    asyncio.run(service.release_truck("line-1"))

    assert _kiriman_terakhir(outbox, tiket["id"])["grading"]["counts"]["total"] == 3
    assert [w for w, _ in halaman.dipanggil] == [tiket["id"]]


async def _janjang_susulan_line_1(service, truck_id, penugasan):
    """One more bunch of line-1, which the weigh-out has just released: the ingest route is a
    plain `def`, so on the factory PC it runs on a worker thread at exactly this point."""
    service.ingest({
        "event_id": "susulan-selama-timbang-keluar", "machine_id": service.lines[0].machine_id,
        "timestamp": datetime.now(WIB).isoformat(), "ripeness_status": "REJ",
        "assignment_id": penugasan["line-1"], "truck_id": truck_id,
    })


async def _janjang_susulan_line_1_dari_thread_lain(service, truck_id, penugasan):
    """The same bunch, ingested on another thread as the real route does."""
    benang = threading.Thread(target=lambda: asyncio.run(_janjang_susulan_line_1(service, truck_id, penugasan)))
    benang.start()
    benang.join(10)
    assert not benang.is_alive()


async def _lepas_manual_line_3(service, truck_id, penugasan):
    """The operator presses Lepas on another line of the same truck while it is being weighed out."""
    await service.release_truck("line-3")


def _tak_ada_tara_di_antrean(line):
    for urutan, antrean in enumerate(line.potret, start=1):
        assert [p for p in antrean if "tare_kg" in p["weighing"]] == [], (
            f"kunjungan dengan tara sudah di antrean pada pelepasan ke-{urutan}"
        )


def test_janjang_susulan_selama_timbang_keluar_tidak_mengantre_kunjungan_setengah_jadi(tmp_path):
    """A late bunch of the line released first finds its ticket (the link was just written) and
    re-queues the visit, which now carries the stored tare and only the lines released so far.
    It must wait for the weigh-out to finish; its bunch is stored, so the one queued after the
    last release counts it."""
    _, _, outbox, line, wid = _timbang_keluar_tiga_line(tmp_path, selama=(2, _janjang_susulan_line_1))

    assert len(line.potret) == 3
    _tak_ada_tara_di_antrean(line)
    akhir = _kiriman_terakhir(outbox, wid)
    assert akhir["weighing"]["tare_kg"] == 5000
    assert akhir["grading"]["counts"]["total"] == 10


def test_janjang_susulan_dari_thread_lain_selama_timbang_keluar_masuk_kunjungan_utuh(tmp_path):
    _, _, outbox, line, wid = _timbang_keluar_tiga_line(
        tmp_path, selama=(2, _janjang_susulan_line_1_dari_thread_lain)
    )

    _tak_ada_tara_di_antrean(line)
    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 10


def test_lepas_manual_selama_timbang_keluar_tidak_mengantre_kunjungan_setengah_jadi(tmp_path):
    _, _, outbox, line, wid = _timbang_keluar_tiga_line(tmp_path, selama=(2, _lepas_manual_line_3))

    _tak_ada_tara_di_antrean(line)
    akhir = _kiriman_terakhir(outbox, wid)
    assert akhir["weighing"]["tare_kg"] == 5000
    assert akhir["grading"]["counts"]["total"] == 9


def test_janjang_susulan_sesudah_timbang_keluar_tetap_mengantre_kunjungan_utuh(tmp_path):
    """The guard lasts only while the weigh-out runs: a bunch that arrives afterwards queues the
    whole visit itself, as before."""
    service, _, outbox, _, wid = _timbang_keluar_tiga_line(tmp_path)
    penugasan = {}
    with service.store._lock:  # noqa: SLF001 (the release emptied `assignments`; read the link)
        penugasan["line-1"] = service.store._db.execute(  # noqa: SLF001
            "SELECT assignment_id FROM visit_assignments WHERE line_code = 'line-1'"
        ).fetchone()["assignment_id"]
    truck_id = service.register_manual_truck(PLAT)["id"]

    asyncio.run(_janjang_susulan_line_1(service, truck_id, penugasan))

    assert _kiriman_terakhir(outbox, wid)["grading"]["counts"]["total"] == 10


class _HalamanRusak:
    """A detail-page queue that cannot be written (full disk, locked file)."""

    def enqueue(self, weighing_id: str, assignment_id: str) -> None:
        raise OSError("antrean halaman tidak bisa ditulis")


def test_halaman_yang_gagal_diantre_tidak_menggagalkan_timbang_keluar(tmp_path, caplog):
    """The weighing is stored and the scale must be answered; the visit goes to AutoERP whole
    even though its page could not be queued, and the failure is in the Log tab."""
    with caplog.at_level("ERROR", logger=LOGGER):
        _, _, outbox, _, wid = _timbang_keluar_tiga_line(tmp_path, manifest_queue=_HalamanRusak())

    akhir = _kiriman_terakhir(outbox, wid)
    assert akhir["weighing"]["tare_kg"] == 5000 and akhir["grading"]["counts"]["total"] == 9
    assert [r for r in caplog.records if "Halaman detail tiket" in r.getMessage()]


def test_halaman_yang_gagal_diantre_tidak_menggagalkan_lepas_manual(tmp_path, caplog):
    service, _, outbox = _konsol(tmp_path, manifest_queue=_HalamanRusak())
    truck_id = service.register_manual_truck(PLAT)["id"]
    tiket = asyncio.run(service.record_weighing({
        "plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat(),
    }))
    asyncio.run(service.assign_truck("line-1", truck_id))
    _janjang(service, "line-1", 3)

    with caplog.at_level("ERROR", logger=LOGGER):
        asyncio.run(service.release_truck("line-1"))

    assert _kiriman_terakhir(outbox, tiket["id"])["grading"]["counts"]["total"] == 3
    assert [r for r in caplog.records if "Halaman detail tiket" in r.getMessage()]


# ---- Dua celah terakhir: tara ditulis sebelum penjaga, dan kiriman yang dilewati ----

class _TokoJeda(ConsoleStore):
    """Holds the thread named `susulan` inside the visit read the queue makes, after its guard
    check and before it reads the stored tare: the interleaving that matters."""

    def __init__(self, path) -> None:
        super().__init__(path)
        self.parado = threading.Event()
        self.lanjut = threading.Event()

    def visit(self, weighing_id: str):
        if threading.current_thread().name == "susulan":
            self.parado.set()
            self.lanjut.wait(1.0)
        return super().visit(weighing_id)


def test_janjang_susulan_yang_lolos_penjaga_tidak_membaca_tara_setengah_jadi(tmp_path):
    """Line-1 was released by the operator before the weigh-out, so its late bunch finds the
    ticket. If it checks the guard just BEFORE the weigh-out raises it, it must not then read
    the freshly written tare with only line-1 linked: the check and the queue are one step
    that the weigh-out cannot interleave with, and the guard goes up before the tare is written."""
    line = _LineMengintip()
    service, store, outbox = _konsol(tmp_path, line=line, store_cls=_TokoJeda)
    line.lihat = lambda: [m.payload for m in outbox.due(50) if m.kind == erp_messages.VISIT]
    truck_id = service.register_manual_truck(PLAT)["id"]
    tiket = asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat(),
    }))
    for kode in ("line-1", "line-2", "line-3"):
        asyncio.run(service.assign_truck(kode, truck_id))
    _janjang(service, "line-1", 3)
    _janjang(service, "line-2", 2)
    _janjang(service, "line-3", 4)
    penugasan_1 = store.assignments()["line-1"]["assignment_id"]
    asyncio.run(service.release_truck("line-1"))
    benang = threading.Thread(
        name="susulan",
        target=service.ingest,
        args=({
            "event_id": "susulan-g", "machine_id": service.lines[0].machine_id,
            "timestamp": datetime.now(WIB).isoformat(), "ripeness_status": "REJ",
            "assignment_id": penugasan_1, "truck_id": truck_id,
        },),
    )
    benang.start()
    assert store.parado.wait(5)
    line.potret.clear()

    async def lanjutkan():
        store.lanjut.set()
        benang.join(5)

    line._pelepasan = 0  # noqa: SLF001 (count the weigh-out's releases only)
    line.selama = (1, lanjutkan)
    asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "tare_kg": 5000, "exited_at": datetime.now(WIB).isoformat(),
    }))

    assert not benang.is_alive()
    _tak_ada_tara_di_antrean(line)
    akhir = _kiriman_terakhir(outbox, tiket["id"])
    assert akhir["weighing"]["tare_kg"] == 5000 and akhir["grading"]["counts"]["total"] == 10


async def _janjang_susulan_tiket_lama(service, truck_id, penugasan):
    service.ingest({
        "event_id": "susulan-tiket-lama", "machine_id": service.lines[0].machine_id,
        "timestamp": datetime.now(WIB).isoformat(), "ripeness_status": "REJ",
        "assignment_id": penugasan["lama"], "truck_id": truck_id,
    })


def test_kiriman_yang_dilewati_selama_timbang_keluar_dikejar_untuk_tiket_lama(tmp_path):
    """Line-1 unloaded the truck for an OLDER ticket of the previous work date (still inside the
    window), the weigh-out is for a new ticket, and a late bunch of line-1 arrives during it. Its
    visit and page are skipped while the guard is up and are not among the tickets the weigh-out
    links, so they must be made up for when it ends."""
    halaman = _CatatHalaman()
    line = _LineMengintip()
    service, store, outbox = _konsol(tmp_path, line=line, manifest_queue=halaman)
    truck_id = service.register_manual_truck(PLAT)["id"]
    lama = _tiket_lampau(store, truck_id, 3.0, wid="w-lama")
    asyncio.run(service.assign_truck("line-1", truck_id))
    penugasan_lama = store.assignments()["line-1"]["assignment_id"]
    _janjang(service, "line-1", 3)
    asyncio.run(service.release_truck("line-1"))
    asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "gross_kg": 14000, "entered_at": datetime.now(WIB).isoformat(),
    }))
    asyncio.run(service.assign_truck("line-2", truck_id))
    _janjang(service, "line-2", 2)
    halaman.dipanggil.clear()
    line._pelepasan = 0  # noqa: SLF001 (count the weigh-out's releases only)
    line.selama = (1, lambda: _janjang_susulan_tiket_lama(service, truck_id, {"lama": penugasan_lama}))

    asyncio.run(service.record_weighing({
        "ref": "SCL-9", "plate_number": PLAT, "tare_kg": 5000, "exited_at": datetime.now(WIB).isoformat(),
    }))

    assert _kiriman_terakhir(outbox, lama)["grading"]["counts"]["total"] == 4
    assert lama in [w for w, _ in halaman.dipanggil]
