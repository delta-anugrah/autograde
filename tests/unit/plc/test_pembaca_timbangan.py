"""Live scale reader + worker: PLC words -> reading -> tile state (2026-10-06)."""
from __future__ import annotations

import asyncio
import logging

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import timbangan_live as tl
from palmgrade.plc.pembaca_timbangan import PembacaTimbangan, build_pembaca_timbangan
from palmgrade.services.timbangan_live import TimbanganLive
from palmgrade.workers.timbangan_live_worker import TimbanganLiveWorker, build_timbangan_live


class _Klien:
    def __init__(self, kata=(24310, 0), bits=None):
        self.kata = list(kata) if kata is not None else None
        self.bits = bits or {}
        self.dibaca: list[tuple[str, int]] = []
        self.closed = False

    def read_words(self, headdevice, count):
        self.dibaca.append((headdevice, count))
        return self.kata

    def read_bits(self, headdevice, count):
        self.dibaca.append((headdevice, count))
        nilai = self.bits.get(headdevice)
        return None if nilai is None else [nilai]

    def close(self):
        self.closed = True


def test_baca_32_bit_dengan_bit_stabil():
    klien = _Klien(kata=(24310, 0), bits={"M2000": True, "M2001": False})
    bacaan = PembacaTimbangan(klien, register="D100", bit_stabil="M2000", bit_error="M2001").baca()
    assert bacaan == tl.Bacaan(kg=24310, stabil=True, error=False)
    assert klien.dibaca[0] == ("D100", 2)


def test_baca_16_bit_dengan_desimal():
    bacaan = PembacaTimbangan(_Klien(kata=(12345,)), register="D100", kata=1, desimal=1).baca()
    assert bacaan == tl.Bacaan(kg=1234.5)


def test_register_tidak_menjawab_jadi_none():
    assert PembacaTimbangan(_Klien(kata=None), register="D100").baca() is None


def test_bit_stabil_yang_dipasang_tapi_gagal_menggagalkan_seluruh_bacaan():
    # Angka "stabil" yang tidak dikonfirmasi siapa pun lebih buruk dari strip.
    klien = _Klien(bits={})
    assert PembacaTimbangan(klien, register="D100", bit_stabil="M2000").baca() is None


def test_bit_error_menyala():
    klien = _Klien(bits={"M2001": True})
    assert PembacaTimbangan(klien, register="D100", bit_error="M2001").baca().error is True


# ── setelan .env -> pembaca ──────────────────────────────────────────────────


def _settings(monkeypatch, **env) -> Settings:
    for nama in ("SCALE_PLC_HOST", "PLC_HOST", "SCALE_PLC_REGISTER", "SCALE_PLC_WORDS",
                 "SCALE_PLC_DECIMALS", "SCALE_PLC_STABLE_BIT", "SCALE_PLC_ERROR_BIT", "SCALE_PLC_PORT"):
        monkeypatch.delenv(nama, raising=False)
    for nama, nilai in env.items():
        monkeypatch.setenv(nama, nilai)
    return Settings()


def test_register_kosong_berarti_mati(monkeypatch):
    assert build_pembaca_timbangan(_settings(monkeypatch, PLC_HOST="192.168.0.14")) is None


def test_register_ngawur_mati_dengan_satu_peringatan(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    s = _settings(monkeypatch, PLC_HOST="192.168.0.14", SCALE_PLC_REGISTER="M100")
    assert build_pembaca_timbangan(s) is None
    assert "SCALE_PLC_REGISTER" in caplog.text


def test_tanpa_host_mati(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    assert build_pembaca_timbangan(_settings(monkeypatch, SCALE_PLC_REGISTER="D100")) is None
    assert "SCALE_PLC_HOST" in caplog.text


def test_host_jatuh_ke_plc_host_dan_port_bawaan_1028(monkeypatch):
    s = _settings(monkeypatch, PLC_HOST="192.168.0.14", SCALE_PLC_REGISTER="d100")
    assert (s.scale_plc_host, s.scale_plc_port, s.scale_plc_words) == ("192.168.0.14", 1028, 2)
    pembaca = build_pembaca_timbangan(s)
    assert pembaca is not None
    assert pembaca._register == "D100"


def test_kata_dan_desimal_ngawur_jatuh_ke_bawaan(monkeypatch):
    s = _settings(monkeypatch, PLC_HOST="h", SCALE_PLC_REGISTER="D100", SCALE_PLC_WORDS="3",
                  SCALE_PLC_DECIMALS="9", SCALE_PLC_STABLE_BIT="D5")
    pembaca = build_pembaca_timbangan(s)
    assert (pembaca._kata, pembaca._desimal, pembaca._bit_stabil) == (2, 0, None)


# ── worker -> keadaan yang dibaca layar ─────────────────────────────────────


class _Jam:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_worker_mencatat_bacaan_dan_putus():
    jam = _Jam()
    live = TimbanganLive(dipakai=True, jam=jam)
    klien = _Klien(kata=(24310, 0), bits={"M2000": True})
    worker = TimbanganLiveWorker(PembacaTimbangan(klien, register="D100", bit_stabil="M2000"), live, interval_s=0.5)

    assert live.snapshot()["keadaan"] == tl.MEMERIKSA
    asyncio.run(worker.run_once())
    assert live.snapshot() == {"keadaan": tl.STABIL, "kg": 24310, "umur_detik": 0.0}

    klien.kata = None
    jam.t += 1
    asyncio.run(worker.run_once())
    assert live.snapshot()["keadaan"] == tl.PUTUS
    assert live.snapshot()["kg"] is None


def test_build_worker_none_saat_tidak_dipasang(monkeypatch):
    live = TimbanganLive(dipakai=False)
    assert build_timbangan_live(_settings(monkeypatch), live) is None
    assert live.snapshot()["keadaan"] == tl.TIDAK_DIPAKAI


def test_build_worker_menyalakan_live(monkeypatch):
    live = TimbanganLive(dipakai=False)
    worker = build_timbangan_live(_settings(monkeypatch, PLC_HOST="h", SCALE_PLC_REGISTER="D100"), live)
    assert worker is not None
    assert live.dipakai is True


def test_run_loop_menutup_sambungan_saat_dibatalkan():
    klien = _Klien()
    live = TimbanganLive(dipakai=True)
    worker = TimbanganLiveWorker(PembacaTimbangan(klien, register="D100"), live, interval_s=10)

    async def jalan():
        tugas = asyncio.create_task(worker.run_loop())
        await asyncio.sleep(0.05)
        tugas.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tugas

    asyncio.run(jalan())
    assert klien.closed is True
