"""`configure_logging` (batch 3.1 + 3.4): satu pemasangan untuk line dan konsol.

Yang dijaga di sini: tiap baris membawa konteks (kode line atau `console`) dan jam
bertanda zona; `LOG_LEVEL` bisa diatur tapi tidak pernah membuat tab Log kehilangan
WARNING; nilai yang salah jatuh ke bawaan dengan satu WARNING dan tidak pernah
menahan boot; memanggil dua kali tidak menggandakan baris; dan uvicorn ikut jalur
yang sama (galat 500 sampai handler tambahan, polling yang sukses dibisukan); httpx tidak pernah menulis alamat permintaan (webhook Discord).
"""
from __future__ import annotations

import logging
import logging.config
from datetime import UTC

import httpx
import pytest
import uvicorn.config

from palmgrade.core import logging as log_pabrik
from palmgrade.core.logging import (
    KONTEKS_KONSOL,
    FilterKonteks,
    FormatterPabrik,
    configure_logging,
    level_dari_teks,
    zona_dari_nama,
)

_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")
#: 2026-09-30 07:03:07.123 UTC
_EPOCH = 1_790_751_787.123


class _Tampung(logging.Handler):
    """Handler tambahan palsu, levelnya WARNING seperti `SqliteLogHandler`."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def pasang(monkeypatch):
    """`configure_logging` yang dilepas lagi sesudah test, termasuk logger uvicorn."""
    monkeypatch.delenv("DEBUG_MODEL_OUTPUT", raising=False)
    semula = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate,
                  logging.getLogger(n).level) for n in _UVICORN}
    dipasang = []

    def _pasang(**kwargs):
        hasil = configure_logging(**kwargs)
        dipasang.append(hasil)
        return hasil

    yield _pasang
    for p in reversed(dipasang):
        p.lepas()
    for nama, (handlers, propagate, level) in semula.items():
        lg = logging.getLogger(nama)
        lg.handlers, lg.propagate = handlers, propagate
        lg.setLevel(level)


def _baris(capsys) -> list[str]:
    return [b for b in capsys.readouterr().err.splitlines() if b.strip()]


# ── nilai env ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("teks", "hasil"),
    [
        (None, (logging.INFO, True)),
        ("", (logging.INFO, True)),
        ("  ", (logging.INFO, True)),
        ("debug", (logging.DEBUG, True)),
        (" WARNING ", (logging.WARNING, True)),
        ("warn", (logging.WARNING, True)),
        ("ERROR", (logging.ERROR, True)),
        ("CRITICAL", (logging.CRITICAL, True)),
        ("verbose", (logging.INFO, False)),
        ("10", (logging.INFO, False)),
    ],
)
def test_level_dari_teks(teks, hasil):
    assert level_dari_teks(teks) == hasil


def test_zona_sah_dipakai():
    zona, sah = zona_dari_nama("Asia/Jakarta")
    assert sah is True and str(zona) == "Asia/Jakarta"


@pytest.mark.parametrize("nama", [None, "", "   "])
def test_zona_kosong_jadi_utc_tanpa_peringatan(nama):
    assert zona_dari_nama(nama) == (UTC, True)


@pytest.mark.parametrize("nama", ["Asia/Nowhere", "WIB", "../../etc/passwd"])
def test_zona_salah_jadi_utc_ditandai_tidak_sah(nama):
    assert zona_dari_nama(nama) == (UTC, False)


def _zona_berupa_folder(nama):
    """Yang dilakukan paket `tzdata` untuk nama folder zona (`Asia`, `America`)."""
    raise IsADirectoryError(21, "Is a directory", nama)


def test_zona_berupa_folder_jadi_utc_ditandai_tidak_sah(monkeypatch):
    """`FACTORY_TZ=Asia` lewat `tzdata` (ada di image pabrik) melempar
    IsADirectoryError, bukan ZoneInfoNotFoundError. Tanpa ditangkap, line mati saat boot."""
    monkeypatch.setattr(log_pabrik, "ZoneInfo", _zona_berupa_folder)
    assert zona_dari_nama("Asia") == (UTC, False)


# ── format ───────────────────────────────────────────────────────────────────


def _record(pesan: str = "halo", **extra) -> logging.LogRecord:
    record = logging.LogRecord("palmgrade.x", logging.WARNING, __file__, 1, pesan, None, None)
    record.created = _EPOCH
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_jam_log_bertanda_zona_pabrik():
    zona, _ = zona_dari_nama("Asia/Jakarta")
    teks = FormatterPabrik(zona).format(_record(line_code="line-2"))
    assert teks == "2026-09-30T14:03:07.123+07:00 | WARNING | line-2 | palmgrade.x | halo"


def test_jam_utc_tetap_ditandai():
    teks = FormatterPabrik(UTC).format(_record(line_code="console"))
    assert teks.startswith("2026-09-30T07:03:07.123+00:00 | WARNING | console |")


def test_record_yang_sudah_membawa_line_code_tidak_ditimpa():
    record = _record(line_code="line-3")
    FilterKonteks("console").filter(record)
    assert record.line_code == "line-3"


# ── pemasangan ───────────────────────────────────────────────────────────────


def test_baris_membawa_konteks_dan_zona(pasang, capsys):
    pasang(konteks="line-2", zona="Asia/Jakarta")
    logging.getLogger("palmgrade.uji").info("kamera siap")
    [baris] = _baris(capsys)
    assert "+07:00 | INFO | line-2 | palmgrade.uji | kamera siap" in baris


def test_konsol_memakai_penanda_console(pasang, capsys):
    pasang(konteks=KONTEKS_KONSOL, zona="Asia/Jakarta")
    logging.getLogger("palmgrade.uji").warning("x")
    assert "| WARNING | console | palmgrade.uji | x" in _baris(capsys)[0]


def test_info_tampil_dengan_level_bawaan(pasang, capsys):
    pasang(konteks="line-1")
    logging.getLogger("palmgrade.uji").info("info biasa")
    assert any("info biasa" in b for b in _baris(capsys))


def test_log_level_warning_menyembunyikan_info(pasang, capsys):
    pasang(konteks="line-1", level="WARNING")
    logging.getLogger("palmgrade.uji").info("tidak tampil")
    logging.getLogger("palmgrade.uji").warning("tampil")
    baris = _baris(capsys)
    assert not any("tidak tampil" in b for b in baris)
    assert any("tampil" in b for b in baris)


def test_log_level_debug_menampilkan_debug(pasang, capsys):
    pasang(konteks="line-1", level="DEBUG")
    logging.getLogger("palmgrade.uji").debug("rinci")
    assert any("rinci" in b for b in _baris(capsys))


def test_log_level_error_tidak_membuat_tab_log_kehilangan_warning(pasang, capsys):
    tampung = _Tampung()
    pasang(konteks=KONTEKS_KONSOL, level="ERROR", handler_tambahan=(tampung,))
    logging.getLogger("palmgrade.uji").warning("peringatan penting")
    assert not any("peringatan penting" in b for b in _baris(capsys))
    assert [r.getMessage() for r in tampung.records] == ["peringatan penting"]


def test_log_level_salah_jatuh_ke_info_dengan_satu_peringatan(pasang, capsys):
    pasang(konteks="line-1", level="verbose")
    logging.getLogger("palmgrade.uji").info("tetap tampil")
    baris = _baris(capsys)
    peringatan = [b for b in baris if "LOG_LEVEL" in b]
    assert len(peringatan) == 1 and "| WARNING |" in peringatan[0] and "'verbose'" in peringatan[0]
    assert any("tetap tampil" in b for b in baris)


def test_zona_salah_tidak_menahan_boot_dan_ditandai_utc(pasang, capsys):
    pasang(konteks="line-1", zona="Asia/Nowhere")
    logging.getLogger("palmgrade.uji").info("jalan terus")
    baris = _baris(capsys)
    assert len([b for b in baris if "FACTORY_TZ" in b]) == 1
    assert "+00:00 | INFO | line-1 | palmgrade.uji | jalan terus" in baris[-1]


def test_zona_kosong_ditandai_utc_tanpa_peringatan(pasang, capsys):
    pasang(konteks="line-1", zona="")
    logging.getLogger("palmgrade.uji").info("x")
    baris = _baris(capsys)
    assert len(baris) == 1 and "+00:00 |" in baris[0]


def test_memanggil_dua_kali_tidak_menggandakan_baris(pasang, capsys):
    pasang(konteks="line-1")
    pasang(konteks="line-1", level="DEBUG")
    logging.getLogger("palmgrade.uji").warning("sekali saja")
    assert len([b for b in _baris(capsys) if "sekali saja" in b]) == 1


def test_keluaran_yatim_yang_dikembalikan_pemanggil_lain_dibuang(pasang, capsys):
    """Pemasangan lama dilepas, lalu daftar handler root dipulihkan orang lain (test
    fixture, kode pihak ketiga) sehingga handler keluaran lamanya kembali tanpa pemilik.
    Pemasangan berikutnya tetap menulis tiap baris sekali."""
    root = logging.getLogger()
    semula = list(root.handlers)
    p = pasang(konteks="line")
    dengan_lama = list(root.handlers)
    p.lepas()
    root.handlers = dengan_lama
    try:
        pasang(konteks=KONTEKS_KONSOL)
        logging.getLogger("palmgrade.uji").warning("satu kali")
        baris = [b for b in _baris(capsys) if "satu kali" in b]
        assert len(baris) == 1 and "| console |" in baris[0]
    finally:
        root.handlers = semula


def test_handler_tambahan_ikut_dilepas_saat_dipasang_ulang(pasang):
    pertama = _Tampung()
    pasang(konteks="line-1", handler_tambahan=(pertama,))
    pasang(konteks="line-1")
    logging.getLogger("palmgrade.uji").warning("sesudah ganti")
    assert pertama.records == []


def test_handler_tambahan_menerima_line_code(pasang):
    tampung = _Tampung()
    pasang(konteks="line-3", handler_tambahan=(tampung,))
    logging.getLogger("palmgrade.uji").error("x")
    assert tampung.records[0].line_code == "line-3"


def test_lepas_mengembalikan_root_seperti_semula(pasang):
    root = logging.getLogger()
    handler_semula, level_semula = list(root.handlers), root.level
    paket = logging.getLogger("palmgrade")
    level_paket_semula = paket.level
    p = pasang(konteks="line-1", level="DEBUG", handler_tambahan=(_Tampung(),))
    # DEBUG cuma untuk paket kita; root (pustaka pihak ketiga) tetap INFO.
    assert root.level == logging.INFO and paket.level == logging.DEBUG
    p.lepas()
    p.lepas()  # aman diulang
    assert root.handlers == handler_semula and root.level == level_semula
    assert paket.level == level_paket_semula
    assert log_pabrik._aktif is None


def test_debug_model_output_tetap_menyalakan_debug_worker(pasang, capsys, monkeypatch):
    nama = "palmgrade.workers.frame_processing_worker"
    semula = logging.getLogger(nama).level
    monkeypatch.setenv("DEBUG_MODEL_OUTPUT", "true")
    try:
        pasang(konteks="line-1")
        logging.getLogger(nama).debug("[MODEL] kotak")
        logging.getLogger("palmgrade.uji").debug("debug lain")
        baris = _baris(capsys)
        assert any("[MODEL] kotak" in b for b in baris)
        assert not any("debug lain" in b for b in baris)
    finally:
        logging.getLogger(nama).setLevel(semula)


def test_zona_berupa_folder_tidak_menahan_boot(pasang, capsys, monkeypatch):
    monkeypatch.setattr(log_pabrik, "ZoneInfo", _zona_berupa_folder)
    pasang(konteks="line-1", zona="Asia")
    logging.getLogger("palmgrade.uji").info("jalan terus")
    baris = _baris(capsys)
    assert len([b for b in baris if "FACTORY_TZ" in b]) == 1
    assert "+00:00 | INFO | line-1 | palmgrade.uji | jalan terus" in baris[-1]


def test_handler_tambahan_dipakai_ulang_tidak_membawa_konteks_lama(pasang):
    """Handler milik pemanggil (tab Log) yang dipasang ulang sesudah `lepas()` tidak
    boleh masih membawa filter konteks dan formatter (zona) pemasangan lama."""
    tampung = _Tampung()
    pasang(konteks="line-1", zona="Asia/Jakarta", handler_tambahan=(tampung,)).lepas()
    assert tampung.filters == [] and tampung.formatter is None
    pasang(konteks=KONTEKS_KONSOL, zona="", handler_tambahan=(tampung,))
    logging.getLogger("palmgrade.uji").warning("sesudah pasang ulang")
    [record] = tampung.records
    assert record.line_code == KONTEKS_KONSOL
    assert "+00:00 | WARNING | console |" in tampung.format(record)


def test_debug_model_output_tidak_membuat_log_level_diabaikan(pasang, capsys, monkeypatch):
    """`DEBUG_MODEL_OUTPUT` menambah baris `[MODEL]`, tidak membuka keluaran proses
    untuk logger lain yang levelnya disetel sendiri (uvicorn.access INFO)."""
    nama = "palmgrade.workers.frame_processing_worker"
    worker = logging.getLogger(nama)
    semula = worker.level
    _uvicorn_seperti_saat_boot()
    monkeypatch.setenv("DEBUG_MODEL_OUTPUT", "true")
    p = pasang(konteks="line-1", level="WARNING")
    _akses("/internal/assignment", 200, "POST")
    worker.debug("[MODEL] kotak")
    baris = _baris(capsys)
    assert not any("/internal/assignment" in b for b in baris)
    assert any("[MODEL] kotak" in b for b in baris)
    p.lepas()
    assert worker.level == semula


def test_log_level_debug_tidak_menyalakan_debug_pustaka_lain(pasang, capsys):
    """botocore di DEBUG menulis header bertanda tangan (access key id): LOG_LEVEL=DEBUG
    cuma berlaku untuk paket palmgrade."""
    pasang(konteks=KONTEKS_KONSOL, level="DEBUG")
    logging.getLogger("botocore.endpoint").debug("Authorization: AWS4-HMAC-SHA256 rahasia")
    logging.getLogger("botocore.endpoint").info("pustaka info tetap tampil")
    logging.getLogger("palmgrade.uji").debug("debug milik kita")
    baris = _baris(capsys)
    assert not any("rahasia" in b for b in baris)
    assert any("pustaka info tetap tampil" in b for b in baris)
    assert any("debug milik kita" in b for b in baris)


def test_level_klien_http_yang_lebih_ketat_dihormati(pasang):
    lg = logging.getLogger("httpx")
    semula = lg.level
    lg.setLevel(logging.ERROR)
    try:
        p = pasang(konteks=KONTEKS_KONSOL)
        assert lg.level == logging.ERROR
        p.lepas()
        assert lg.level == logging.ERROR
    finally:
        lg.setLevel(semula)


# ── uvicorn ──────────────────────────────────────────────────────────────────


def _uvicorn_seperti_saat_boot() -> None:
    """Urutan produksi: uvicorn memasang konfigurasinya dulu, baru app di-import."""
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)


def _akses(jalur: str, status: int, metode: str = "GET") -> None:
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", metode, jalur, "1.1", status
    )


def test_galat_uvicorn_sampai_handler_tambahan_dengan_traceback(pasang):
    _uvicorn_seperti_saat_boot()
    tampung = _Tampung()
    pasang(konteks=KONTEKS_KONSOL, handler_tambahan=(tampung,))
    try:
        raise RuntimeError("route meledak")
    except RuntimeError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=exc)
    [record] = tampung.records
    assert record.name == "uvicorn.error" and record.exc_info is not None


def _tenggang_habis(jumlah: int = 1) -> None:
    """Persis panggilan uvicorn 0.34 `Server.shutdown` saat koneksi masih terbuka."""
    logging.getLogger("uvicorn.error").error(
        "Cancel %s running task(s), timeout graceful shutdown exceeded", jumlah
    )


def test_tenggang_tutup_uvicorn_cuma_info_tidak_sampai_tab_log(pasang, capsys):
    """Tes manual 2026-10-01: layar konsol SELALU membuka `/api/video_feed`, jadi
    tiap restart atau upgrade line menulis baris ini. Itu jalan normal (1 detik
    `--timeout-graceful-shutdown`), bukan galat: tetap di `docker logs` sebagai INFO,
    tidak masuk tab Log dan Discord."""
    _uvicorn_seperti_saat_boot()
    tampung = _Tampung()
    pasang(konteks="line-2", handler_tambahan=(tampung,))
    _tenggang_habis()
    assert tampung.records == []
    [baris] = _baris(capsys)
    assert "| INFO | line-2 | uvicorn.error | Cancel 1 running task(s)" in baris


def test_galat_uvicorn_lain_tetap_error(pasang):
    _uvicorn_seperti_saat_boot()
    tampung = _Tampung()
    pasang(konteks="line-2", handler_tambahan=(tampung,))
    logging.getLogger("uvicorn.error").error("Cancel ditolak: %s", "bukan tenggang")
    [record] = tampung.records
    assert record.levelno == logging.ERROR


def test_access_log_memakai_format_yang_sama(pasang, capsys):
    _uvicorn_seperti_saat_boot()
    pasang(konteks="line-1", zona="Asia/Jakarta")
    _akses("/internal/assignment", 200, "POST")
    [baris] = _baris(capsys)
    assert "+07:00 | INFO | line-1 | uvicorn.access |" in baris
    assert '"POST /internal/assignment HTTP/1.1" 200' in baris


def test_polling_sukses_dibisukan_galatnya_tetap_tertulis(pasang, capsys):
    _uvicorn_seperti_saat_boot()
    pasang(konteks="line-1")
    _akses("/internal/status", 200)
    _akses("/health?x=1", 200)
    _akses("/health", 503)
    _akses("/internal/status", 401)
    baris = _baris(capsys)
    assert len(baris) == 2
    assert '"GET /health HTTP/1.1" 503' in baris[0]
    assert '"GET /internal/status HTTP/1.1" 401' in baris[1]


def test_lepas_mengembalikan_handler_uvicorn(pasang):
    _uvicorn_seperti_saat_boot()
    semula = list(logging.getLogger("uvicorn").handlers)
    p = pasang(konteks="line-1")
    assert logging.getLogger("uvicorn").handlers == []
    p.lepas()
    assert logging.getLogger("uvicorn").handlers == semula
    assert logging.getLogger("uvicorn").propagate is False
    assert logging.getLogger("uvicorn.access").filters == []
    assert logging.getLogger("uvicorn.error").filters == []


# ── httpx ────────────────────────────────────────────────────────────────────


def test_httpx_tidak_menulis_alamat_permintaan(pasang, capsys):
    """httpx menulis tiap permintaan di INFO lengkap dengan alamatnya. Di konsol itu
    berarti alamat webhook Discord (rahasia) tertulis di `docker logs`, ditambah
    polling status tiga line tiap detik. Dibatasi WARNING apa pun `LOG_LEVEL`-nya."""
    semula = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    p = pasang(konteks=KONTEKS_KONSOL, level="DEBUG")
    transport = httpx.MockTransport(lambda _permintaan: httpx.Response(204))
    with httpx.Client(transport=transport) as klien:
        klien.post("https://discord.com/api/webhooks/1/token-palsu", json={"content": "x"})
    assert not any("webhooks" in b for b in _baris(capsys))
    p.lepas()
    assert {n: logging.getLogger(n).level for n in ("httpx", "httpcore")} == semula
