"""OutboxRetryWorker (batch 2.4): tanpa batas nyerah, tapi tidak menghajar konsol yang mati.

Konsol palsu = `httpx.MockTransport`. Jam worker palsu (jeda sambungan), jam store
asli (jadwal per baris). Tanpa thread: satu `_flush_pending()` = satu putaran
`run_loop`.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.kirim_antrean_line import (
    GAGAL_BERUNTUN_PUTUS,
    JEDA_SAMBUNGAN_DASAR_S,
    JEDA_SAMBUNGAN_MAKS_S,
    SEBAB_ALAMAT_SALAH,
    SEBAB_KUNCI_DITOLAK,
    SEBAB_TAK_TERJANGKAU,
)
from palmgrade.integrations.outbox import outbox_store as modul_outbox_store
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.workers import outbox_retry_worker
from palmgrade.workers.outbox_retry_worker import STATUS_TIDAK_DIKETAHUI, OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-line-palsu"
MAIN = (Path(__file__).resolve().parents[2] / "src/palmgrade/main.py").read_text()


class _Jam:
    def __init__(self) -> None:
        self.sekarang = 1_000.0

    def __call__(self) -> float:
        return self.sekarang

    def maju(self, detik: float) -> None:
        self.sekarang += detik


class _Konsol:
    """Konsol palsu: mati (ConnectError), atau menjawab status per event_id."""

    def __init__(self) -> None:
        self.mati = False
        self.jawab: dict[str, int] = {}
        self.bawaan = 201
        self.diterima: list[str] = []
        self.diminta: list[str] = []
        self.permintaan = 0
        self.terakhir: httpx.Request | None = None
        #: Dipanggil di awal tiap permintaan: meniru hal yang terjadi SELAMA percobaan.
        self.saat_diminta: Callable[[], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.permintaan += 1
        self.terakhir = request
        if self.saat_diminta is not None:
            self.saat_diminta()
        event_id = json.loads(request.content)["event_id"]
        self.diminta.append(event_id)
        if self.mati:
            raise httpx.ConnectError("Connection refused", request=request)
        status = self.jawab.get(event_id, self.bawaan)
        if 200 <= status < 300:
            self.diterima.append(event_id)
        return httpx.Response(status, text="ok" if status < 300 else f"ditolak {status}")


@pytest.fixture
def rakit(tmp_path):
    def _rakit(*, enable_webhook: bool = True):
        settings = replace(
            Settings(), repo_root=tmp_path, backend_url="http://konsol",
            webhook_secret=SECRET, enable_webhook=enable_webhook,
        )
        store = OutboxStore(tmp_path / "outbox.db")
        konsol = _Konsol()
        jam = _Jam()
        worker = OutboxRetryWorker(
            store, settings, RuntimeState(), client=httpx.Client(transport=httpx.MockTransport(konsol)), jam=jam
        )
        return worker, store, konsol, jam

    return _rakit


def _isi(store: OutboxStore, n: int) -> None:
    for i in range(n):
        store.add_event(f"e{i}", "m-1", {"event_id": f"e{i}", "timestamp": "2026-09-20T03:00:00+00:00"})


def test_konsol_sehat_semua_terkirim_dalam_satu_putaran(rakit):
    """Antrean yang menumpuk habis dalam satu putaran, bukan 20 baris per detik."""
    worker, store, konsol, _ = rakit()
    _isi(store, 45)

    worker._flush_pending()

    assert store.pending_count() == 0
    assert len(konsol.diterima) == 45
    assert worker.state.last_successful_api_push is not None


def test_alamat_dan_header_kontrak_s5_tetap(rakit):
    worker, store, konsol, _ = rakit()
    _isi(store, 1)

    worker._flush_pending()

    assert str(konsol.terakhir.url) == "http://konsol/api/v1/internal/vision/events"
    assert konsol.terakhir.headers["x-webhook-secret"] == SECRET


def test_konsol_mati_satu_percobaan_per_jeda_bukan_dua_puluh_per_detik(rakit):
    """Review focus 2. Dulu: 20 POST tiap detik selamanya begitu antrean lewat
    beberapa ribu baris (terukur saat menulis rencana ini), tiap POST satu WARNING."""
    worker, store, konsol, jam = rakit()
    _isi(store, 500)
    konsol.mati = True

    for _ in range(600):  # 10 menit, satu putaran per detik seperti run_loop
        worker._flush_pending()
        jam.maju(1)

    assert konsol.permintaan <= 600 / JEDA_SAMBUNGAN_MAKS_S + 5
    assert store.pending_count() == 500


def test_konsol_mati_satu_warning_lalu_satu_saat_pulih(rakit, caplog):
    worker, store, konsol, jam = rakit()
    _isi(store, 30)
    konsol.mati = True

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        for _ in range(300):
            worker._flush_pending()
            jam.maju(1)
        konsol.mati = False
        jam.maju(JEDA_SAMBUNGAN_MAKS_S)
        worker._flush_pending()

    peringatan = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(peringatan) == 2, peringatan
    assert "tidak bisa dikirimi" in peringatan[0]
    assert "tersambung lagi" in peringatan[1]
    assert store.pending_count() == 0


def test_pulih_terdeteksi_walau_semua_baris_sedang_mundur(rakit):
    """Pabrik yang diam semalam: tidak ada janjang baru yang jatuh tempo. Tanpa
    percobaan sambungan yang mengabaikan jadwal, pulihnya konsol baru ketahuan
    sesudah jadwal mundur baris, sampai 10 menit."""
    worker, store, konsol, jam = rakit()
    _isi(store, 3)
    for row in store.get_pending():
        for _ in range(6):
            store.mark_failed_attempt(row["id"], "putus")
    konsol.mati = True
    worker._flush_pending()
    assert worker.status()["tersambung"] is False

    konsol.mati = False
    jam.maju(JEDA_SAMBUNGAN_MAKS_S)
    worker._flush_pending()

    assert store.pending_count() == 0
    assert sorted(konsol.diterima) == ["e0", "e1", "e2"]


def test_boot_pertama_mengirim_semua_tanpa_menunggu_jadwal(rakit):
    worker, store, _, _ = rakit()
    _isi(store, 3)
    for row in store.get_pending():
        store.mark_failed_attempt(row["id"], "HTTP 503")

    worker._flush_pending()

    assert store.pending_count() == 0


def test_baris_ditolak_400_tidak_menahan_yang_lain(rakit):
    worker, store, konsol, _ = rakit()
    _isi(store, 3)
    konsol.jawab["e1"] = 400

    worker._flush_pending()

    assert sorted(konsol.diterima) == ["e0", "e2"]
    sisa = store._db.execute("SELECT event_id, retry_count, last_error FROM outbox_events").fetchall()
    assert [(r["event_id"], r["retry_count"]) for r in sisa] == [("e1", 1)]
    assert sisa[0]["last_error"].startswith("HTTP 400")
    assert worker.status()["tersambung"] is True


def test_baris_racun_500_mundur_sendiri_tanpa_memutus_sambungan(rakit, monkeypatch, caplog):
    """Satu janjang yang selalu dijawab 500 di tengah konsol yang sehat. Dulu (review
    Task 3): 500 memutus sambungan, janjang baru berikutnya menyambung lagi, dan
    sambung lagi menjadwalkan si racun sekarang juga. Terukur 511 POST dan 601
    WARNING per jam, `tersambung` berkedip. Sekarang 500 sesudah konsol menerima
    janjang lain di sambungan yang sama = baris itu yang bermasalah."""
    worker, store, konsol, jam = rakit()
    monkeypatch.setattr(modul_outbox_store, "time", SimpleNamespace(time=jam))
    store.add_event("racun", "m-1", {"event_id": "racun", "timestamp": "2026-09-20T03:00:00+00:00"})
    konsol.jawab["racun"] = 500
    janjang = []

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        for detik in range(3600):  # satu jam, satu janjang tiap 12 detik
            if detik % 12 == 0:
                janjang.append(f"b{len(janjang)}")
                store.add_event(janjang[-1], "m-1", {"event_id": janjang[-1], "timestamp": "2026-09-20T03:00:00+00:00"})
            worker._flush_pending()
            jam.maju(1)

    sambungan = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING and ("tidak bisa dikirimi" in r.getMessage() or "tersambung lagi" in r.getMessage())
    ]
    assert len(sambungan) <= 2, sambungan
    assert konsol.diminta.count("racun") <= 15
    assert sorted(konsol.diterima) == sorted(janjang)
    assert store.pending_count() == 1
    assert worker.status()["tersambung"] is True


def _warning_sambungan(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING and ("tidak bisa dikirimi" in r.getMessage() or "tersambung lagi" in r.getMessage())
    ]


def test_dua_baris_racun_berturut_turut_tidak_membuat_sambungan_berkedip(rakit, monkeypatch, caplog):
    """Dua janjang racun yang selalu berurutan di pengurasan: di bawah batas beruntun,
    jadi tetap masalah baris, bukan putus-sambung tiap janjang baru."""
    worker, store, konsol, jam = rakit()
    monkeypatch.setattr(modul_outbox_store, "time", SimpleNamespace(time=jam))
    for racun in ("racun1", "racun2"):
        store.add_event(racun, "m-1", {"event_id": racun, "timestamp": "2026-09-20T03:00:00+00:00"})
        konsol.jawab[racun] = 500
    janjang = []

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        for detik in range(3600):
            if detik % 12 == 0:
                janjang.append(f"b{len(janjang)}")
                store.add_event(janjang[-1], "m-1", {"event_id": janjang[-1], "timestamp": "2026-09-20T03:00:00+00:00"})
            worker._flush_pending()
            jam.maju(1)

    assert len(_warning_sambungan(caplog)) <= 2, _warning_sambungan(caplog)
    assert konsol.diminta.count("racun1") <= 15
    assert konsol.diminta.count("racun2") <= 15
    assert sorted(konsol.diterima) == sorted(janjang)
    assert store.pending_count() == 2
    assert worker.status()["tersambung"] is True


def test_konsol_500_untuk_semua_sesudah_satu_2xx_putus_setelah_tiga(rakit, monkeypatch, caplog):
    """Konsol menerima satu janjang lalu menjawab 500 untuk semuanya (disk penuh).
    Tanpa pemutus beruntun ini menguras 2000 baris sekaligus, satu WARNING per baris
    (terukur di fix round 1: 2000 POST dan 1995 WARNING di putaran pertama)."""
    worker, store, konsol, jam = rakit()
    monkeypatch.setattr(modul_outbox_store, "time", SimpleNamespace(time=jam))
    _isi(store, 2000)
    konsol.bawaan = 500
    konsol.jawab["e0"] = 201

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        worker._flush_pending()
        putaran_pertama = konsol.permintaan
        for _ in range(3600):
            jam.maju(1)
            worker._flush_pending()

    assert putaran_pertama == 1 + GAGAL_BERUNTUN_PUTUS
    assert worker.status()["tersambung"] is False
    assert konsol.permintaan < 1000
    assert len(_warning_sambungan(caplog)) <= 2, _warning_sambungan(caplog)
    baris = [r for r in caplog.records if r.levelno >= logging.WARNING and "menolak janjang" in r.getMessage()]
    assert len(baris) <= 3
    assert store.pending_count() == 1999


def test_baris_ditolak_dicatat_warning_sekali_saja(rakit, caplog):
    worker, store, konsol, _ = rakit()
    _isi(store, 1)
    konsol.jawab["e0"] = 400

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        worker._flush_pending()
        store.kirim_ulang_sekarang()
        worker._flush_pending()

    ditolak = [r for r in caplog.records if "menolak janjang" in r.getMessage()]
    assert [r.levelno for r in ditolak] == [logging.WARNING, logging.DEBUG]


@pytest.mark.parametrize("status,sebab", [(401, SEBAB_KUNCI_DITOLAK), (404, SEBAB_ALAMAT_SALAH)])
def test_kunci_atau_alamat_salah_menjeda_dan_menyebut_sebab(rakit, status, sebab):
    worker, store, konsol, jam = rakit()
    _isi(store, 10)
    konsol.bawaan = status

    worker._flush_pending()
    worker._flush_pending()

    assert konsol.permintaan == 1
    s = worker.status()
    assert (s["tersambung"], s["sebab_putus"], s["putus_sejak"]) == (False, sebab, jam.sekarang)
    assert s["galat"].startswith(f"HTTP {status}")
    assert store.pending_count() == 10


def test_konsol_tak_terjangkau_status_lengkap(rakit):
    worker, store, konsol, jam = rakit()
    _isi(store, 1)
    konsol.mati = True

    worker._flush_pending()

    s = worker.status()
    assert set(s) == set(STATUS_TIDAK_DIKETAHUI)
    assert s["sebab_putus"] == SEBAB_TAK_TERJANGKAU
    assert "ConnectError" in s["galat"]
    assert s["galat_at"] == jam.sekarang
    assert s["coba_lagi_at"] == jam.sekarang + JEDA_SAMBUNGAN_DASAR_S


def test_status_awal_tidak_diketahui(rakit):
    worker, *_ = rakit()
    assert worker.status() == STATUS_TIDAK_DIKETAHUI


def test_bangunkan_membatalkan_jeda(rakit):
    worker, store, konsol, _ = rakit()
    _isi(store, 1)
    konsol.mati = True
    worker._flush_pending()
    konsol.mati = False

    worker._flush_pending()
    assert store.pending_count() == 1  # masih dalam jeda sambungan

    worker.bangunkan()
    worker._flush_pending()
    assert store.pending_count() == 0


def test_enable_webhook_false_tidak_mengirim_dan_tidak_membuang(rakit):
    worker, store, konsol, _ = rakit(enable_webhook=False)
    _isi(store, 2)

    worker._flush_pending()

    assert konsol.permintaan == 0
    assert store.pending_count() == 2


def test_payload_rusak_ditolak_barisnya_bukan_konsolnya(rakit):
    worker, store, konsol, _ = rakit()
    _isi(store, 1)
    with store._db:
        store._db.execute(
            "INSERT INTO outbox_events (event_id, machine_id, payload, dibuat_at) "
            "VALUES ('rusak', 'm-1', '{bukan json', 1.0)"
        )

    worker._flush_pending()

    assert konsol.diterima == ["e0"]
    baris = store._db.execute("SELECT retry_count, last_error FROM outbox_events WHERE event_id = 'rusak'").fetchone()
    assert baris["retry_count"] == 1
    assert "payload rusak" in baris["last_error"]
    assert worker.status()["tersambung"] is True


def test_nama_worker_sama_dengan_yang_didaftarkan_main():
    """Layar Antrean mencari worker lewat nama ini di `RuntimeState.worker_threads`."""
    nama = outbox_retry_worker.NAMA_WORKER
    assert f'_start_worker("{nama}"' in MAIN
    assert f'("{nama}", outbox_thread, outbox_worker)' in MAIN


def test_baris_hidup_lagi_ditolak_400_warning_sekali(rakit, caplog):
    """Baris Lampung yang dulu menyerah (percobaan 50) dan dihidupkan lagi: penolakan
    pertamanya di proses ini tetap satu WARNING, bukan DEBUG karena hitungannya tinggi."""
    worker, store, konsol, _ = rakit()
    _isi(store, 1)
    with store._db:
        store._db.execute("UPDATE outbox_events SET retry_count = 50")
    konsol.jawab["e0"] = 400

    with caplog.at_level(logging.DEBUG, logger=outbox_retry_worker.__name__):
        worker._flush_pending()
        store.kirim_ulang_sekarang()
        worker._flush_pending()

    ditolak = [r for r in caplog.records if "menolak janjang" in r.getMessage()]
    assert [r.levelno for r in ditolak] == [logging.WARNING, logging.DEBUG]


def test_bangunkan_saat_percobaan_gagal_tidak_hilang(rakit):
    """Kirim Ulang ditekan tepat saat percobaan yang akan gagal sedang berjalan: jeda
    yang dipasang kegagalan itu tidak boleh menelan tombolnya."""
    worker, store, konsol, jam = rakit()
    _isi(store, 1)
    konsol.mati = True
    konsol.saat_diminta = worker.bangunkan

    worker._flush_pending()
    konsol.saat_diminta = None
    jam.maju(1)
    worker._flush_pending()

    assert konsol.permintaan == 2


def test_gagal_menulis_store_tetap_menjeda(rakit, monkeypatch):
    """Disk penuh saat mencatat percobaan gagal: jeda sambungan sudah terpasang, jadi
    putaran berikutnya tidak mencoba lagi (dan tidak mencetak traceback) tiap detik."""
    worker, store, konsol, jam = rakit()
    _isi(store, 1)
    konsol.mati = True

    def disk_penuh(*_args, **_kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(store, "mark_failed_attempt", disk_penuh)
    with pytest.raises(sqlite3.OperationalError):
        worker._flush_pending()
    jam.maju(1)
    worker._flush_pending()

    assert konsol.permintaan == 1
    assert worker.status()["tersambung"] is False
