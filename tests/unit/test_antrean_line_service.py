"""`AntreanLine` (sisi line, batch 2.4): ringkasan untuk layar konsol dan Kirim Ulang."""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from antrean_line_rakit import klien_konsol_mati

from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.services.antrean_line import AntreanLine
from palmgrade.workers.outbox_retry_worker import NAMA_WORKER, STATUS_TIDAK_DIKETAHUI, OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState


@pytest.fixture
def line(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, backend_url="http://konsol", enable_webhook=True)
    settings.artifacts_dir.mkdir(parents=True)
    store = OutboxStore(settings.state_dir / "outbox.db")
    state = RuntimeState()
    worker = OutboxRetryWorker(store, settings, state, client=klien_konsol_mati())
    return AntreanLine(store, settings, state, settings.state_dir), worker


def test_ringkasan_tanpa_worker_semua_tidak_diketahui(line):
    antrean, _ = line

    isi = antrean.ringkasan()

    assert (isi["menunggu"], isi["tertua_at"], isi["aktif"], isi["lama_tertinggal"]) == (0, None, True, False)
    assert isi["line_code"] == antrean.settings.line_code
    assert {k: isi[k] for k in STATUS_TIDAK_DIKETAHUI} == STATUS_TIDAK_DIKETAHUI


def test_ringkasan_membawa_keadaan_worker(line):
    antrean, worker = line
    antrean.state.worker_threads.append((NAMA_WORKER, None, worker))
    antrean.outbox.add_event("e1", "m-1", {"event_id": "e1"})
    worker._flush_pending()

    isi = antrean.ringkasan()

    assert (isi["menunggu"], isi["tersambung"], isi["sebab_putus"]) == (1, False, "tak_terjangkau")
    assert "ConnectError" in isi["galat"]


def test_pengiriman_dimatikan_terbaca(line):
    antrean, _ = line
    antrean.settings = replace(antrean.settings, enable_webhook=False)

    assert antrean.ringkasan()["aktif"] is False


def test_sisa_antrean_lama_terbaca(line):
    antrean, _ = line
    (antrean.settings.artifacts_dir / "outbox.db").write_bytes(b"sisa")

    assert antrean.ringkasan()["lama_tertinggal"] is True


def test_kirim_ulang_menjadwalkan_dan_membangunkan_worker(line):
    antrean, worker = line
    antrean.state.worker_threads.append((NAMA_WORKER, None, worker))
    antrean.outbox.add_event("e1", "m-1", {"event_id": "e1"})
    worker._flush_pending()  # konsol mati: baris mundur, jeda sambungan jalan
    assert antrean.outbox.get_pending() == []
    assert worker.status()["coba_lagi_at"] is not None

    assert antrean.kirim_ulang() == 1

    assert [r["event_id"] for r in antrean.outbox.get_pending()] == ["e1"]
    assert worker.status()["coba_lagi_at"] is None


def test_kirim_ulang_tanpa_worker_tetap_menjadwalkan(line):
    antrean, _ = line
    antrean.outbox.add_event("e1", "m-1", {"event_id": "e1"})

    assert antrean.kirim_ulang() == 1


@pytest.mark.parametrize("isi,tingkat", [(1, logging.WARNING), (0, logging.INFO)])
def test_kirim_ulang_antrean_kosong_bukan_warning(line, caplog, isi, tingkat):
    """Parkiran Task 4: Kirim Ulang pada antrean kosong tidak menjadwalkan apa pun, jadi
    bukan kejadian yang perlu dicari di log sebagai peringatan."""
    antrean, _ = line
    for i in range(isi):
        antrean.outbox.add_event(f"e{i}", "m-1", {"event_id": f"e{i}"})

    with caplog.at_level(logging.DEBUG, logger="palmgrade.services.antrean_line"):
        antrean.kirim_ulang()

    [catatan] = [r for r in caplog.records if "Kirim Ulang" in r.getMessage()]
    assert catatan.levelno == tingkat
