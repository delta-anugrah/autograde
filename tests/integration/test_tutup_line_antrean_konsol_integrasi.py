"""Tutup line saat konsol mati, lalu boot ulang: antrean SUNGGUHAN, tiap janjang sampai sekali.

Final review line M4: keputusan R11 (worker antrean konsol bukan langkah tutup)
bertumpu pada "SQLite tahan lama + kirim ulang idempoten", tapi test tutup line
memakai outbox tiruan berbasis list. Di sini dirangkai `CaptureSaveWorker` +
disk sungguhan lewat `tulis_atomik` asli (gambar diganti byte tetap dan diperlambat
supaya antrean terisi, jadi jalan di CI tanpa cv2), `OutboxStore` +
`OutboxRetryWorker` asli di thread-nya sendiri, dan `PenutupLine` +
`langkah_tutup_line` yang dipakai `main.py`. Boot berikutnya mengirim ke lane ingest
konsol yang ASLI (`ConsoleService`, `INSERT OR IGNORE` per `event_id`).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import httpx
import pytest
from antrean_line_rakit import KabelKonsol, app_ingest

import palmgrade.plc as plc
from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.integrations.storage.tulis_atomik import tulis_atomik
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.langkah_tutup_line import langkah_tutup_line
from palmgrade.services.penutup_line import PenutupLine
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob
from palmgrade.workers.outbox_retry_worker import OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState

FRAME = object()
SECRET = "kunci-tutup-palsu"


class _DiskLambat:
    """Irisan `LocalFileStorage` yang dipakai penulis bukti, tanpa encode cv2."""

    def write_json(self, path, payload: dict) -> None:
        tulis_atomik(path, json.dumps(payload).encode("utf-8"))

    def write_image(self, path, frame, quality: int = 80) -> None:
        time.sleep(0.1)
        tulis_atomik(path, b"webp-palsu")

    def write_thumbnail(self, path, frame, *, max_width: int, quality: int) -> None:
        tulis_atomik(path, b"thumb-palsu")


class _Kamera:
    def disconnect(self) -> None: ...


class _Penjadwal:
    def stop(self, *, tunggu: bool = True) -> None: ...


def _janjang(i: int) -> SaveJob:
    return SaveJob(
        timestamp=f"2026-09-29_1015{i:02d}_000001", date_folder="2026-09-29",
        truck_folder="_belum-assign", annotated_frame=FRAME, clean_frame=FRAME,
        ripeness_status="acc", ripeness_conf=0.9, grade_class="Ripe",
        bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        truck_id=None, assignment_id=None, ffb_source=None,
        event_ts=f"2026-09-29T03:15:{i:02d}+00:00",
    )


def _konsol_mati(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused", request=request)


@pytest.fixture(autouse=True)
def _tanpa_plc(monkeypatch):
    monkeypatch.setattr(plc, "_worker", None)


def test_tutup_saat_konsol_mati_lalu_boot_ulang_mengirim_tiap_janjang_sekali(tmp_path, caplog):
    settings = replace(
        Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", enable_webhook=True,
        webhook_secret=SECRET, backend_url="http://konsol", machine_id="11111111-1111-1111-1111-111111111111",
    )
    jalur = settings.state_dir / "outbox.db"
    store = OutboxStore(jalur)
    state = RuntimeState()
    penulis = CaptureSaveWorker(settings=settings, storage=_DiskLambat(), outbox_store=store)
    pengirim = OutboxRetryWorker(store, settings, state, client=httpx.Client(transport=httpx.MockTransport(_konsol_mati)))
    for nama, worker in (("capture_save", penulis), ("outbox_retry", pengirim)):
        benang = threading.Thread(target=worker.run_loop, daemon=True, name=nama)
        benang.start()
        state.worker_threads.append((nama, benang, worker))
    keluar = threading.Event()
    penutup = PenutupLine(keluar=lambda _kode: keluar.set())
    penutup.pasang(langkah_tutup_line(
        worker_threads=state.worker_threads, penulis=penulis, kamera=_Kamera(), penjadwal=_Penjadwal(),
    ))

    for i in range(8):
        assert penulis.submit(_janjang(i))
    penutup.keluar_nanti(0.0)
    assert keluar.wait(15)
    with caplog.at_level("ERROR"):
        terlambat = penulis.submit(_janjang(20))

    # Proses "mati" di sini. Semua janjang yang antre ada di antrean konsol di disk.
    assert terlambat is False
    assert any("2026-09-29_101520" in r.getMessage() for r in caplog.records)
    assert store.pending_count() == 8
    assert pengirim.status()["tersambung"] is False
    store._db.close()

    # Boot berikutnya, konsol hidup: lane ingest ASLI.
    konsol = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta", webhook_secret=SECRET),
        ConsoleStore(tmp_path / "console.db"), None,
    )
    kabel = KabelKonsol(app_ingest(konsol))
    store_baru = OutboxStore(jalur)
    pengirim_baru = OutboxRetryWorker(store_baru, settings, RuntimeState(), client=kabel.klien())
    pengirim_baru._flush_pending()

    assert store_baru.pending_count() == 0
    assert konsol.store._db.execute("SELECT COUNT(*) FROM inspections").fetchone()[0] == 8
    assert kabel.permintaan == 8
