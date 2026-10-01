"""`rakit_lapor_discord` + `pasang_handler_lapor` + perakitan di `console_main.py` (batch 3.5)."""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.lapor_discord_repository import LaporDiscordStore
from palmgrade.services.lapor_discord import pasang_handler_lapor, rakit_lapor_discord

URL = "https://discord.com/api/webhooks/1/token-palsu"
CONSOLE_MAIN = (Path(__file__).resolve().parents[2] / "src/palmgrade/console_main.py").read_text()
LIFESPAN = CONSOLE_MAIN.split("async def lifespan(app: FastAPI):", 1)[1].split("def create_console_app", 1)[0]
LOGGER_SERVICE = "palmgrade.services.lapor_discord"


def _settings(tmp_path, url: str) -> Settings:
    return replace(Settings(), discord_webhook_url=url, repo_root=tmp_path)


def test_bawaan_mati_tanpa_berkas(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("STATE_DIR", raising=False)
    settings = replace(Settings(), repo_root=tmp_path)

    lapor = rakit_lapor_discord(settings)

    assert (lapor.store, settings.discord_webhook_url) == (None, "")
    assert lapor.ringkasan() == {"keadaan": "mati"}
    assert not (tmp_path / "state" / "lapor_discord.db").exists()


def test_env_dibaca_dan_dipangkas(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", f"  {URL}\n")
    assert Settings().discord_webhook_url == URL


def test_alamat_bukan_https_mati_dan_disebut_url_salah(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("STATE_DIR", raising=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER_SERVICE):
        lapor = rakit_lapor_discord(_settings(tmp_path, "discord.com/api/webhooks/1/x"))
    assert lapor.store is None
    assert lapor.ringkasan() == {"keadaan": "url_salah"}
    assert [r.getMessage() for r in caplog.records] == [
        "DISCORD_WEBHOOK_URL bukan alamat https:// yang bisa dipakai, lapor ke Discord MATI. "
        "Salin ulang alamat webhook dari Discord ke .env PC ini lalu autograde restart."
    ]


def test_alamat_sah_membuka_antrean_dan_ringkasan_tanpa_alamat(tmp_path, monkeypatch):
    monkeypatch.delenv("STATE_DIR", raising=False)
    lapor = rakit_lapor_discord(_settings(tmp_path, URL))

    ringkasan = lapor.ringkasan()

    assert lapor.store is not None
    assert (tmp_path / "state" / "lapor_discord.db").exists()
    assert ringkasan["keadaan"] == "aktif"
    assert ringkasan["kiriman"] == 0
    assert URL not in str(ringkasan)


def test_berkas_antrean_rusak_fitur_mati_satu_warning_tanpa_melempar(tmp_path, monkeypatch, caplog):
    """Carry B-T7 no. 1: `lapor_discord.db` rusak tidak boleh menahan konsol menyala."""
    monkeypatch.delenv("STATE_DIR", raising=False)
    settings = _settings(tmp_path, URL)
    settings.lapor_discord_db_path.parent.mkdir(parents=True)
    settings.lapor_discord_db_path.write_bytes(b"bukan basis data sqlite " * 64)

    with caplog.at_level(logging.WARNING, logger=LOGGER_SERVICE):
        lapor = rakit_lapor_discord(settings)

    assert lapor.store is None
    assert lapor.ringkasan() == {"keadaan": "rusak", "galat": "lapor_discord.db tidak bisa dibuka (DatabaseError)"}
    (pesan,) = [r.getMessage() for r in caplog.records]
    assert str(settings.lapor_discord_db_path) in pesan and "DatabaseError" in pesan
    assert URL not in pesan


def test_handler_lapor_cuma_menangkap_error(tmp_path, monkeypatch):
    monkeypatch.delenv("STATE_DIR", raising=False)
    lapor = rakit_lapor_discord(_settings(tmp_path, URL))
    handler = pasang_handler_lapor(lapor.store)
    log = logging.getLogger("uji.lapor.handler")
    try:
        log.warning("peringatan tidak ikut")
        log.error("galat ikut")
        log.critical("kritis ikut")
    finally:
        logging.getLogger().removeHandler(handler)

    r = lapor.store.ringkasan()
    assert (r["menunggu_jenis"], r["menunggu_kejadian"]) == (2, 2)


class _PenandaMasuk:
    """Meneruskan ke store asli, dan memberi tanda saat thread `penulis-lain` sudah di
    dalam `emit` (jadi, dengan handler biasa, sudah memegang kunci handler)."""

    def __init__(self, store: LaporDiscordStore) -> None:
        self.store = store
        self.masuk = threading.Event()

    def write(self, *args, **kwargs) -> None:
        if threading.current_thread().name == "penulis-lain":
            self.masuk.set()
        self.store.write(*args, **kwargs)


def test_handler_lapor_tanpa_kunci_handler_tidak_deadlock_dua_thread(tmp_path):
    """Carry B-T7 no. 5 (ABBA): thread lain sudah di dalam `handle()` handler lapor dan
    menunggu kunci store (dipegang `susun`), lalu `susun_pesan` mencatat ERROR. Dengan
    kunci handler bawaan logging, yang kedua menunggu kunci handler yang dipegang yang
    pertama: dua thread menggantung selamanya. Handler lapor tidak punya kunci handler."""
    store = LaporDiscordStore(tmp_path / "lapor.db")
    store.write("ERROR", "a", "sebelum susun", None, now=1.0)
    penanda = _PenandaMasuk(store)
    handler = pasang_handler_lapor(penanda)
    log = logging.getLogger("uji.lapor.abba")
    di_susun = threading.Event()

    def _susun_yang_mencatat(kelompok):
        di_susun.set()
        assert penanda.masuk.wait(5.0), "thread lain tidak pernah masuk emit"
        log.error("galat dari dalam susun_pesan")
        return ["pesan jadi"]

    def _penulis_lain():
        assert di_susun.wait(5.0)
        log.error("galat dari thread lain")

    penyusun = threading.Thread(target=lambda: store.susun(_susun_yang_mencatat, now=5.0), daemon=True)
    penulis = threading.Thread(target=_penulis_lain, name="penulis-lain", daemon=True)
    try:
        penyusun.start()
        penulis.start()
        penyusun.join(timeout=5.0)
        penulis.join(timeout=5.0)
        if penyusun.is_alive() or penulis.is_alive():
            # Kunci yang dipegang thread yang menggantung akan ditunggu `logging.shutdown()`
            # saat interpreter keluar: lepaskan rujukannya supaya test GAGAL, bukan pytest macet.
            handler.lock = None
            pytest.fail("handler lapor dan susun saling menunggu (ABBA)")
    finally:
        logging.getLogger().removeHandler(handler)

    r = store.ringkasan()
    assert (r["kiriman"], r["menunggu_kejadian"]) == (1, 1)  # galat thread lain menunggu ringkasan berikutnya
    store.close()


def test_console_main_memasang_lapor_dan_tarikan_log_line():
    assert "lapor = get_lapor_discord()" in LIFESPAN
    assert "handler_lapor = pasang_handler_lapor(lapor.store)" in LIFESPAN
    assert "LaporDiscordWorker.dari_settings(lapor.store, service.settings).run_loop()" in LIFESPAN
    assert "TarikLogLineWorker(service.lines, service.line_client, log_store, digest=lapor.store)" in LIFESPAN
    # Sink log dipasang lebih dulu: galat saat boot ikut ke tab Log dan ke ringkasan.
    # Dua bentuk (R3b): Stream A mengganti `install_log_sink(log_store)` dengan
    # `configure_logging(..., handler_tambahan=(SqliteLogHandler(log_store),))`.
    sink = re.search(r"install_log_sink\(log_store\)|SqliteLogHandler\(log_store\)", LIFESPAN)
    assert sink is not None
    assert sink.start() < LIFESPAN.index("pasang_handler_lapor(")
    assert "app.include_router(lapor_discord_router)" in CONSOLE_MAIN


def test_console_main_melepas_handler_lapor_sesudah_worker_dihentikan():
    """R3c: handler lapor dilepas sesudah task dibatalkan (Stream A menaruh
    `pemasangan_log.lepas()` sesudahnya, sebagai baris terakhir)."""
    sesudah_yield = LIFESPAN.split("yield", 1)[1]
    assert sesudah_yield.index("task.cancel()") < sesudah_yield.index(
        "if handler_lapor is not None:\n        logging.getLogger().removeHandler(handler_lapor)"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com:99999/api/webhooks/1/rahasia",   # port di luar jangkauan
        "https://exa\x01mple.com/api/webhooks/1/rahasia",     # lolos urllib, ditolak httpx
        "https://xn--a.com/api/webhooks/1/rahasia",           # host IDNA rusak: ValueError
    ],
)
def test_alamat_https_yang_tidak_bisa_dikirimi_mati_dan_disebut_url_salah(tmp_path, monkeypatch, caplog, url):
    monkeypatch.delenv("STATE_DIR", raising=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER_SERVICE):
        lapor = rakit_lapor_discord(_settings(tmp_path, url))
    assert lapor.store is None
    assert lapor.ringkasan() == {"keadaan": "url_salah"}
    (pesan,) = [r.getMessage() for r in caplog.records]
    assert "DISCORD_WEBHOOK_URL" in pesan and "rahasia" not in pesan
    assert not (tmp_path / "state" / "lapor_discord.db").exists()


def test_berkas_rusak_menyebut_jalur_host_dan_tindakan_yang_bisa_dilakukan(tmp_path, monkeypatch, caplog):
    """Review akhir 1, M1: Setelan tidak punya restart konsol, dan jalur host berkasnya
    `state/console/lapor_discord.db`. Layar dan WARNING menyebut satu tindakan yang sama."""
    monkeypatch.delenv("STATE_DIR", raising=False)
    settings = _settings(tmp_path, URL)
    settings.lapor_discord_db_path.parent.mkdir(parents=True)
    settings.lapor_discord_db_path.write_bytes(b"bukan basis data sqlite " * 64)
    with caplog.at_level(logging.WARNING, logger=LOGGER_SERVICE):
        rakit_lapor_discord(settings)
    (pesan,) = [r.getMessage() for r in caplog.records]
    assert "Pindahkan berkas state/console/lapor_discord.db di folder autograde PC ini, lalu autograde restart" in pesan


def test_handler_lapor_mengeluh_dengan_kalimatnya_sendiri(tmp_path, monkeypatch, capsys):
    """Keluhan warisan `SqliteLogHandler` ("the Log screen will stay empty") salah untuk
    antrean Discord: tab Log tetap terisi, yang berhenti ringkasan Discord."""
    monkeypatch.delenv("STATE_DIR", raising=False)
    lapor = rakit_lapor_discord(_settings(tmp_path, URL))
    lapor.store.close()                                   # tiap tulis sesudah ini gagal
    handler = pasang_handler_lapor(lapor.store)
    log = logging.getLogger("uji.lapor.keluhan")
    try:
        log.error("galat pertama")
        log.error("galat kedua")
    finally:
        logging.getLogger().removeHandler(handler)
    keluaran = capsys.readouterr().err
    assert keluaran.count("\n") == 1
    assert "Discord" in keluaran and "Log screen will stay empty" not in keluaran
