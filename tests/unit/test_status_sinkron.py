"""Last Sync: siapa yang mencatat, dan apa yang sampai ke `/api/console/state`.

Tiap jalur yang sudah bicara ke luar ikut mencatat hasilnya:

- AutoERP: tarik data master (tiap 5 menit), kirim kunjungan (antrean), dan cek
  `ping` tiap menit supaya status tetap segar saat tidak ada yang dikirim;
- R2 dari konsol: manifest kunjungan, dan cek tiap menit;
- R2 dari tiap line: upload foto per jam, dilaporkan lewat `/internal/status`.

`terakhir` (jam sinkron) disimpan di `sync_state`, jadi sesudah konsol restart
layar tetap menyebut jam sinkron terakhir, bukan "belum pernah".
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError

from palmgrade.core.config import Settings
from palmgrade.domain.bahaya import MODE_SEMUA
from palmgrade.domain.sinkron import MEMERIKSA, TERPUTUS, TERSAMBUNG, TIDAK_DIPAKAI
from palmgrade.integrations.erp.client import ErpClient, ErpRejected, ErpUnavailable
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.upload.r2_uploader import R2Uploader
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.status_sinkron import StatusSinkron
from palmgrade.workers.cek_sinkron_worker import CekSinkronWorker
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker, OutboxHandler
from palmgrade.workers.master_data_worker import MasterDataWorker

ERP = "http://erp.local"


class Jam:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _status(store, jam=None, *, erp=True, r2=True) -> StatusSinkron:
    return StatusSinkron(store, erp_aktif=erp, r2_aktif=r2, jam=jam or Jam())


# ── pencatat ──────────────────────────────────────────────────────────────


def test_jam_sinkron_selamat_dari_restart_konsol(store):
    jam = Jam(1_000.0)
    _status(store, jam).berhasil("erp", "tarik", sinkron=True)

    sesudah_restart = _status(store, Jam(5_000.0))
    r = sesudah_restart.ringkas("erp", antre=0)

    # Jamnya ingat; sambungannya belum dicek lagi sejak menyala.
    assert (r["terakhir"], r["keadaan"]) == (1_000.0, MEMERIKSA)


def test_tidak_dipakai_kalau_tanpa_konfigurasi(store):
    s = _status(store, erp=False, r2=False)

    assert s.ringkas("erp", antre=0)["keadaan"] == TIDAK_DIPAKAI
    assert s.ringkas("r2", antre=0)["keadaan"] == TIDAK_DIPAKAI


def test_putus_dan_pulih_dicatat_sekali_masing_masing_di_log(store, caplog):
    jam = Jam(1_000.0)
    s = _status(store, jam)
    s.berhasil("erp", "tarik", sinkron=True)

    with caplog.at_level(logging.WARNING, logger="palmgrade.services.status_sinkron"):
        jam.now = 1_060.0
        s.gagal("erp", "cek", "connect timeout", jaringan=True)
        jam.now = 1_120.0
        s.gagal("erp", "tarik", "connect timeout", jaringan=True)
        jam.now = 1_720.0
        s.berhasil("erp", "cek", sinkron=False)

    pesan = [r.getMessage() for r in caplog.records]
    assert len(pesan) == 2, pesan
    assert "AutoERP" in pesan[0] and "connect timeout" in pesan[0]
    assert "AutoERP" in pesan[1] and "11 menit" in pesan[1]


# ── AutoERP: tarik data, kirim kunjungan, cek ping ────────────────────────


def _erp(handler) -> ErpClient:
    return ErpClient(ERP, "k", "s", transport=httpx.MockTransport(handler))


def test_tarik_data_berhasil_menggeser_jam_sinkron(store):
    s = _status(store)
    worker = MasterDataWorker(store, _erp(lambda r: httpx.Response(200, json={"data": []})), status=s)

    asyncio.run(worker.run_once())

    r = s.ringkas("erp", antre=0)
    assert (r["keadaan"], r["terakhir"]) == (TERSAMBUNG, 1_000.0)


def test_tarik_data_gagal_mencatat_putus_tanpa_menghentikan_worker(store):
    def mati(request):
        raise httpx.ConnectError("no route to host")

    s = _status(store)
    asyncio.run(MasterDataWorker(store, _erp(mati), status=s).run_once())

    r = s.ringkas("erp", antre=0)
    assert (r["keadaan"], r["sejak"]) == (TERPUTUS, 1_000.0)


def _outbox_worker(tmp_path, handler, status):
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db", clock=Jam())
    handlers = {"truck": OutboxHandler(method="m", on_sent=lambda key, answer: None)}
    return ErpOutboxWorker(outbox, _erp(handler), handlers, status=status), outbox


def test_kunjungan_terkirim_menggeser_jam_sinkron(tmp_path, store):
    s = _status(store)
    worker, outbox = _outbox_worker(tmp_path, lambda r: httpx.Response(200, json={"message": {}}), s)
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    assert s.ringkas("erp", antre=0)["terakhir"] == 1_000.0


def test_autoerp_tak_terjangkau_saat_mengirim_berarti_putus(tmp_path, store):
    s = _status(store)
    worker, outbox = _outbox_worker(tmp_path, lambda r: httpx.Response(503, text="down"), s)
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    assert s.ringkas("erp", antre=0)["keadaan"] == TERPUTUS


def test_kiriman_ditolak_autoerp_tetap_tersambung(tmp_path, store):
    """AutoERP menjawab: sambungannya hidup. Pesan yang ditolak ada di tab
    Antrean ERP dan ikut dihitung di angka antrean, bukan membuat status merah."""
    s = _status(store)
    worker, outbox = _outbox_worker(
        tmp_path, lambda r: httpx.Response(417, json={"exc_type": "ValidationError"}), s
    )
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    asyncio.run(worker.drain_once())

    r = s.ringkas("erp", antre=0)
    assert (r["keadaan"], r["terakhir"]) == (TERSAMBUNG, None)


def test_ping_autoerp(store):
    jawaban = []

    def handler(request):
        jawaban.append(request.url.path)
        return httpx.Response(200, json={"message": "pong"})

    asyncio.run(_erp(handler).ping())
    assert jawaban == ["/api/method/ping"]

    with pytest.raises(ErpUnavailable):
        asyncio.run(_erp(lambda r: httpx.Response(502, text="bad gateway")).ping())


# ── R2 ────────────────────────────────────────────────────────────────────


def _galat_s3(kode: str, status: int) -> ClientError:
    return ClientError({"Error": {"Code": kode}, "ResponseMetadata": {"HTTPStatusCode": status}}, "HeadObject")


def test_cek_r2_objek_belum_ada_tetap_berarti_tersambung():
    """404 = R2 menjawab dan kuncinya diterima; cuma objeknya yang belum ada."""
    client = Mock()
    client.head_object.side_effect = _galat_s3("404", 404)
    R2Uploader("acc", "k", "s", "bucket", client=client).cek()


def test_cek_r2_ditolak_atau_putus_melempar():
    client = Mock()
    client.head_object.side_effect = _galat_s3("403", 403)
    with pytest.raises(ClientError):
        R2Uploader("acc", "k", "s", "bucket", client=client).cek()
    client.head_object.side_effect = ConnectionError("no route")
    with pytest.raises(ConnectionError):
        R2Uploader("acc", "k", "s", "bucket", client=client).cek()


class _ErpPalsu:
    def __init__(self, gagal=False):
        self.gagal = gagal

    async def ping(self):
        if self.gagal:
            raise ErpUnavailable("GET /api/method/ping: timeout")


class _R2Palsu:
    def __init__(self, gagal=False):
        self.gagal = gagal

    def cek(self):
        if self.gagal:
            raise ConnectionError("R2 down")


def test_cek_tiap_menit_menjaga_status_tanpa_menggeser_jam_sinkron(store):
    s = _status(store)
    asyncio.run(CekSinkronWorker(s, erp=_ErpPalsu(), r2=_R2Palsu()).run_once())

    erp, r2 = s.ringkas("erp", antre=0), s.ringkas("r2", antre=0)
    assert (erp["keadaan"], erp["terakhir"]) == (TERSAMBUNG, None)
    assert (r2["keadaan"], r2["terakhir"]) == (TERSAMBUNG, None)

    asyncio.run(CekSinkronWorker(s, erp=_ErpPalsu(gagal=True), r2=_R2Palsu(gagal=True)).run_once())
    assert s.ringkas("erp", antre=0)["keadaan"] == TERPUTUS
    assert s.ringkas("r2", antre=0)["keadaan"] == TERPUTUS


def test_cek_dilewati_untuk_sambungan_yang_tidak_dipakai(store):
    """Sambungan tanpa klien tidak disentuh: tetap memeriksa, bukan dianggap hidup."""
    s = _status(store)
    asyncio.run(CekSinkronWorker(s, erp=None, r2=_R2Palsu()).run_once())

    assert s.ringkas("erp", antre=0)["keadaan"] == MEMERIKSA
    assert s.ringkas("r2", antre=0)["keadaan"] == TERSAMBUNG


def _log_sinkron(caplog) -> list[str]:
    """Cuma catatan putus/pulih; worker menulis log galatnya sendiri di samping itu."""
    return [r.getMessage() for r in caplog.records if r.name == "palmgrade.services.status_sinkron"]


class _ErpMenolak:
    def __init__(self, status):
        self.status = status

    async def ping(self):
        raise ErpRejected(f"GET /api/method/ping: HTTP {self.status}", status=self.status)


def _kirim(outbox_worker, outbox):
    outbox.enqueue("truck", f"BE{len(outbox.due(100))}AA", {"plate_number": "BE 1 AA"})
    asyncio.run(outbox_worker.drain_once())


def test_kunci_autoerp_ditolak_merah_terus_tanpa_berkedip(tmp_path, store, caplog):
    """Secret AutoERP dirotasi: Frappe menjawab 401 untuk semuanya. Dulu kiriman 401
    dihitung "AutoERP menjawab" dan ping 401 dihitung putus, jadi titiknya berkedip tiap
    menit dan tiap kedip menulis WARNING."""
    s = _status(store)
    cek = CekSinkronWorker(s, erp=_ErpMenolak(401), r2=None)
    kirim, outbox = _outbox_worker(tmp_path, lambda r: httpx.Response(401, json={"exc_type": "AuthenticationError"}), s)

    with caplog.at_level(logging.WARNING, logger="palmgrade.services.status_sinkron"):
        keadaan = []
        for langkah in (lambda: asyncio.run(cek.run_once()), lambda: _kirim(kirim, outbox),
                        lambda: asyncio.run(cek.run_once())):
            langkah()
            keadaan.append(s.ringkas("erp", antre=0)["keadaan"])

    assert keadaan == [TERPUTUS] * 3
    assert len(_log_sinkron(caplog)) == 1


def test_tarikan_ditolak_tetap_merah_walau_ping_berhasil(store, caplog):
    """Tarikan data master yang ditolak (field DocType tidak cocok, 417) berarti data tidak
    mengalir, walau server hidup. Merah sampai tarikan itu sendiri berhasil."""
    s = _status(store)
    ditolak = MasterDataWorker(store, _erp(lambda r: httpx.Response(417, json={"exc_type": "DataError"})), status=s)
    lolos = MasterDataWorker(store, _erp(lambda r: httpx.Response(200, json={"data": []})), status=s)

    with caplog.at_level(logging.WARNING, logger="palmgrade.services.status_sinkron"):
        asyncio.run(ditolak.run_once())
        asyncio.run(CekSinkronWorker(s, erp=_ErpPalsu(), r2=None).run_once())
        sesudah_ping = s.ringkas("erp", antre=0)["keadaan"]
        asyncio.run(lolos.run_once())

    assert sesudah_ping == TERPUTUS
    assert s.ringkas("erp", antre=0)["keadaan"] == TERSAMBUNG
    assert len(_log_sinkron(caplog)) == 2


def test_satu_pesan_yang_membuat_autoerp_500_tidak_memerahkan_sambungan(tmp_path, store):
    """500 untuk satu kiriman biasanya isi pesan itu yang memicu galat di AutoERP; pesannya
    menunggu di tab Antrean ERP. Server yang benar-benar rusak ketahuan dari ping."""
    s = _status(store)
    asyncio.run(CekSinkronWorker(s, erp=_ErpPalsu(), r2=None).run_once())
    kirim, outbox = _outbox_worker(tmp_path, lambda r: httpx.Response(500, text="Traceback"), s)

    _kirim(kirim, outbox)

    assert s.ringkas("erp", antre=0)["keadaan"] == TERSAMBUNG


def test_jaringan_putus_pulih_oleh_jawaban_dari_sumber_mana_pun(tmp_path, store):
    """Kiriman yang gagal karena jaringan diulang dengan jeda sampai sejam; titiknya tidak
    boleh merah selama itu kalau ping sudah menjawab lagi."""
    s = _status(store)
    mati, outbox = _outbox_worker(tmp_path, lambda r: httpx.Response(503, text="down"), s)
    _kirim(mati, outbox)
    putus = s.ringkas("erp", antre=0)["keadaan"]

    asyncio.run(CekSinkronWorker(s, erp=_ErpPalsu(), r2=None).run_once())

    assert (putus, s.ringkas("erp", antre=0)["keadaan"]) == (TERPUTUS, TERSAMBUNG)


def test_hapus_semua_di_danger_zone_langsung_menghapus_jam_di_layar(store):
    s = _status(store)
    s.berhasil("erp", "tarik", sinkron=True)

    store.hapus_data(MODE_SEMUA)

    assert s.ringkas("erp", antre=0)["terakhir"] is None


class _Berhenti(Exception):
    pass


class _PencatatRusak:
    """Pencatat yang menulis ke SQLite bisa gagal (disk penuh, "database is locked")."""

    def berhasil(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")

    def gagal(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")


def test_loop_tarik_dan_cek_tidak_mati_kalau_pencatat_melempar(store, monkeypatch):
    """Worker yang mati diam-diam berhenti menarik truk dan akun sampai restart, sementara
    titiknya tetap hijau karena ping masih jalan (aturan 6: loop membungkus run_once)."""
    putaran = []

    async def tidur(_detik):
        putaran.append(1)
        if len(putaran) % 3 == 0:
            raise _Berhenti

    monkeypatch.setattr(asyncio, "sleep", tidur)
    tarik = MasterDataWorker(store, _erp(lambda r: httpx.Response(200, json={"data": []})), interval_s=0,
                             status=_PencatatRusak())
    cek = CekSinkronWorker(_PencatatRusak(), erp=_ErpPalsu(), r2=_R2Palsu(), interval_s=0)

    for worker in (tarik, cek):
        with pytest.raises(_Berhenti):
            asyncio.run(worker.run_loop())

    assert len(putaran) == 6


# ── gabungan di konsol ────────────────────────────────────────────────────


def test_state_konsol_membawa_last_sync_dari_semua_sumber(tmp_path, store):
    settings = replace(Settings(), factory_tz="Asia/Jakarta", erp_url=ERP, r2_bucket="palmgrade")
    s = _status(store)
    s.berhasil("erp", "tarik", sinkron=True)
    s.berhasil("r2", "cek", sinkron=False)
    service = ConsoleService(settings, store, Mock(), status_sinkron=s)
    service.line_status = lambda: {
        "line-1": {"reachable": True, "unggah": {"aktif": True, "terakhir": 900.0, "gagal_sejak": None,
                                                 "antre": 12, "rusak": 0}},
        "line-2": {"reachable": False},
    }

    sinkron = service.state()["sinkron"]

    assert (sinkron["autoerp"]["keadaan"], sinkron["autoerp"]["terakhir"]) == (TERSAMBUNG, 1_000.0)
    cloud = sinkron["cloud"]
    assert (cloud["keadaan"], cloud["terakhir"], cloud["antre"]) == (TERSAMBUNG, 900.0, 12)
    # Ketiga line terdaftar; yang belum pernah menjawab tertulis tidak terbaca.
    assert {p["line_code"]: p["terbaca"] for p in cloud["per_line"]} == {
        "line-1": True, "line-2": False, "line-3": False,
    }


def test_last_sync_yang_gagal_dibaca_tidak_menjatuhkan_polling_layar(store, caplog):
    """`/api/console/state` melayani seluruh layar operator tiap 2 detik: bagian Last
    Sync yang rusak cukup kosong, kartu line dan angka hari ini tetap tampil."""
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, store, Mock(), status_sinkron=_status(store))

    def rusak():
        raise RuntimeError("bentuk laporan tak terduga")

    service.sinkron = rusak
    with caplog.at_level(logging.ERROR):
        state = service.state()

    assert state["sinkron"] is None and len(state["lines"]) == 3
    assert any("Last Sync" in r.getMessage() for r in caplog.records)


# ── laporan line sampai ke konsol ─────────────────────────────────────────


def test_worker_status_line_membawa_blok_unggah():
    from palmgrade.workers.line_status_worker import LineStatusWorker

    unggah = {"aktif": True, "terakhir": 900.0, "gagal_sejak": None, "antre": 2, "rusak": 0}

    class _Line:
        async def status(self, line):
            return {"piston": {}, "alarms": [], "unggah": unggah}

    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    worker = LineStatusWorker(lines, _Line(), interval_s=0)
    asyncio.run(worker.run_once())

    assert worker.snapshot()[lines[0].line_code]["unggah"] == unggah


def test_line_versi_lama_tanpa_blok_unggah_terbaca_none():
    from palmgrade.workers.line_status_worker import LineStatusWorker

    class _Line:
        async def status(self, line):
            return {"piston": {}, "alarms": []}

    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    worker = LineStatusWorker(lines, _Line(), interval_s=0)
    asyncio.run(worker.run_once())

    assert worker.snapshot()[lines[0].line_code]["unggah"] is None


class _LineBerubah:
    """Line yang jawaban `unggah`-nya diganti test di antara putaran worker."""

    def __init__(self):
        self.unggah = None
        self.mati = False

    async def status(self, line):
        if self.mati:
            raise httpx.ConnectError("line mati")
        return {"piston": {}, "alarms": [], "unggah": self.unggah}


def _putaran(worker, line, unggah=None, *, mati=False):
    line.unggah, line.mati = unggah, mati
    asyncio.run(worker.run_once())


def test_upload_foto_line_putus_dan_pulih_masuk_tab_log_sekali_masing_masing(caplog):
    """Line tidak punya tab Log (cuma konsol yang memasang log_sink), jadi alasan
    upload foto gagal hanya ada di `docker logs` line. Konsol yang mencatatnya:
    sekali waktu mulai putus (dengan alasannya) dan sekali waktu pulih."""
    from palmgrade.workers.line_status_worker import LineStatusWorker

    line = _LineBerubah()
    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    worker = LineStatusWorker(lines, line, interval_s=0)
    putus = {"aktif": True, "terakhir": 900.0, "gagal_sejak": 1_000.0, "pesan": "PUT R2 gagal: timeout", "antre": 4}

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.line_status_worker"):
        _putaran(worker, line, {"aktif": True, "terakhir": 900.0, "gagal_sejak": None, "antre": 0})
        _putaran(worker, line, putus)
        _putaran(worker, line, putus)                 # masih putus: tidak dicatat lagi
        _putaran(worker, line, mati=True)             # line mati sebentar: bukan pulih
        _putaran(worker, line, putus)
        _putaran(worker, line, {"aktif": True, "terakhir": 4_600.0, "gagal_sejak": None, "antre": 0})

    pesan = [r.getMessage() for r in caplog.records]
    assert len(pesan) == 2, pesan
    assert "line-1" in pesan[0] and "PUT R2 gagal: timeout" in pesan[0]
    assert "line-1" in pesan[1] and "tersambung lagi" in pesan[1]


def test_line_restart_saat_putus_tidak_dicatat_sebagai_pulih(caplog):
    """Sesudah restart, line lupa status gagalnya sampai batch jam berikutnya. Itu
    bukan bukti foto sudah naik: pulih baru dicatat kalau jam unggah bergerak."""
    from palmgrade.workers.line_status_worker import LineStatusWorker

    line = _LineBerubah()
    lines = replace(Settings(), factory_tz="Asia/Jakarta").console_lines[:1]
    worker = LineStatusWorker(lines, line, interval_s=0)

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.line_status_worker"):
        _putaran(worker, line, {"aktif": True, "terakhir": 900.0, "gagal_sejak": 1_000.0, "pesan": "x", "antre": 4})
        _putaran(worker, line, {"aktif": True, "terakhir": 900.0, "gagal_sejak": None, "antre": 4})
        dicatat_sesudah_restart = len(caplog.records)
        _putaran(worker, line, {"aktif": True, "terakhir": 4_600.0, "gagal_sejak": None, "antre": 0})

    pesan = [r.getMessage() for r in caplog.records]
    assert dicatat_sesudah_restart == 1 and "terputus" in pesan[0], pesan
    # Pulihnya tetap tercatat begitu foto benar-benar naik, supaya tab Log tidak
    # menyisakan "terputus" tanpa akhir.
    assert len(pesan) == 2 and "tersambung lagi" in pesan[1], pesan


def test_status_line_mengambil_ringkasan_upload_dari_state():
    """Jembatan `/internal/status` → konsol, tanpa torch (controllernya menyeret cv2)."""
    from palmgrade.domain.sinkron import unggah_dari_state
    from palmgrade.workers.runtime_state import RuntimeState

    state = RuntimeState()
    assert unggah_dari_state(state) is None

    state.status_unggah = lambda: {"aktif": True, "terakhir": 5.0}
    assert unggah_dari_state(state) == {"aktif": True, "terakhir": 5.0}


def test_manifest_r2_ikut_mencatat_cloud(tmp_path, store):
    """Manifest kunjungan yang naik = data lewat ke R2 (jam Last Sync bergerak);
    yang gagal = putus."""
    from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

    class _Uploader:
        def __init__(self, gagal=False):
            self.gagal = gagal

        def put_bytes(self, body, key, *, content_type):
            if self.gagal:
                raise ConnectionError("R2 down")

    store.upsert_weighing({
        "id": "w1", "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA", "truck_id": "t1",
        "work_date": "2026-09-26", "gross_kg": 9000.0, "tare_kg": 2000.0, "net_kg": 7000.0,
        "entered_at": "2026-09-26T08:00:00+07:00", "exited_at": None,
    })
    store.add_inspection({
        "event_id": "e1", "machine_id": "m", "line_code": "line-1", "work_date": "2026-09-26",
        "timestamp": "2026-09-26T08:01:00+07:00", "ripeness_status": "ACC", "ripeness_confidence": 0.9,
        "capture_type": "auto", "image_path": "captures/results/2026-09-26/x.webp", "truck_id": "t1",
        "assignment_id": "a-1", "prediction": "Acc", "tp_status": None, "tp_confidence": None,
    })
    store.link_weighing_to_assignment("w1", "a-1")
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html></html>")

    for gagal, harap in ((True, TERPUTUS), (False, TERSAMBUNG)):
        s = _status(store)
        worker = VisitManifestWorker(
            store, ErpOutboxStore(tmp_path / f"m{gagal}.db"), _Uploader(gagal), public_url="https://x",
            viewer_html=viewer, clock=lambda: "2026-09-26T09:00:00+07:00", status=s,
        )
        worker.enqueue("w1", "a-1")
        asyncio.run(worker.drain_once())
        assert s.ringkas("r2", antre=0)["keadaan"] == harap


# ── perakitan ─────────────────────────────────────────────────────────────


def test_worker_autoerp_dirakit_dengan_pencatat_last_sync(tmp_path, store):
    from palmgrade.services.erp_queue import ErpQueue
    from palmgrade.workers.erp_link import build_erp_workers

    settings = replace(Settings(), factory_tz="Asia/Jakarta", erp_url=ERP)
    s = _status(store)
    queue = ErpQueue(store, ErpOutboxStore(tmp_path / "o.db"), site="PT X")

    workers = build_erp_workers(settings, store, queue, status=s)

    pencatat = {type(w).__name__: getattr(w, "_status", "tidak ada") for w in workers}
    assert pencatat["MasterDataWorker"] is s and pencatat["ErpOutboxWorker"] is s


def test_cek_per_menit_cuma_untuk_sambungan_yang_dipakai(store):
    from palmgrade.workers.cek_sinkron_worker import build_cek_sinkron

    kosong = replace(Settings(), factory_tz="Asia/Jakarta", erp_url="", r2_bucket="")
    assert build_cek_sinkron(kosong, _status(store, erp=False, r2=False)) is None

    lengkap = replace(kosong, erp_url=ERP, r2_bucket="palmgrade", r2_account_id="acc")
    worker = build_cek_sinkron(lengkap, _status(store))
    assert worker is not None and worker._erp is not None and worker._r2 is not None

    cuma_erp = replace(kosong, erp_url=ERP)
    worker = build_cek_sinkron(cuma_erp, _status(store, r2=False))
    assert worker._erp is not None and worker._r2 is None


def test_titik_rakit_konsol_memberi_satu_pencatat_ke_semua(monkeypatch, tmp_path):
    """Manifest R2 dan layar harus memegang pencatat yang SAMA; dua objek berarti
    worker mencatat ke satu tempat dan layar membaca tempat lain.

    `Settings` diganti supaya `state/` jatuh ke folder sementara: titik rakit yang
    asli akan membuka `state/console.db` milik developer."""
    from palmgrade.routes import console as rute

    uji = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", r2_bucket="palmgrade",
                  r2_public_url="https://x", erp_url="")
    monkeypatch.setattr(rute, "Settings", lambda: uji)
    rute.get_console_service.cache_clear()
    try:
        service = rute.get_console_service()
        assert service.manifest_queue is not None
        assert service.manifest_queue._status is service.status_sinkron
        assert service.store is not None and str(tmp_path) in str(uji.console_db_path)
    finally:
        rute.get_console_service.cache_clear()
