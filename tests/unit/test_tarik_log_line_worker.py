"""`TarikLogLineWorker` (batch 3.2): kursor, halaman, penundaan, dan line versi lama."""
from __future__ import annotations

import asyncio
import logging

import httpx

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.log_repository import LogStore
from palmgrade.workers.tarik_log_line_worker import (
    JEDA_GAGAL_S,
    JEDA_RUTE_TIDAK_ADA_S,
    MAKS_HALAMAN,
    TarikLogLineWorker,
)

LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")


def _entri(id_: int, seq: int, *, level: str = "ERROR", count: int = 1) -> dict:
    return {"id": id_, "seq": seq, "first_at": 100.0, "last_at": 100.0, "level": level,
            "source": "palmgrade.x", "message": f"pesan {id_}", "detail": None, "count": count}


class _Jam:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _LinePalsu:
    """Satu line dengan log berurutan; `jawab` bisa diganti exception."""

    def __init__(self, entri: list[dict], *, generasi: str = "g1") -> None:
        self.entri = entri
        self.generasi = generasi
        self.gagal: Exception | None = None
        self.permintaan: list[tuple[int, str, int]] = []

    def jawab(self, setelah: int, generasi: str, batas: int) -> dict:
        self.permintaan.append((setelah, generasi, batas))
        if self.gagal is not None:
            raise self.gagal
        mulai = setelah if generasi == self.generasi else 0
        sisa = [e for e in self.entri if e["seq"] > mulai]
        halaman = sisa[:batas]
        return {"generasi": self.generasi, "entri": halaman,
                "seq_akhir": halaman[-1]["seq"] if halaman else mulai,
                "lagi": len(sisa) > batas, "dibuang": 0}


class _Klien:
    def __init__(self, lines: dict[str, _LinePalsu]) -> None:
        self.lines = lines

    async def log_line(self, line, *, setelah, generasi, batas):
        return self.lines[line.line_code].jawab(setelah, generasi, batas)


class _Digest:
    def __init__(self) -> None:
        self.galat = []

    def antre_line(self, galat) -> None:
        self.galat.extend(galat)


def _pesan(store: LogStore) -> list[tuple[str, str]]:
    items = store.read(level=None, search=None, limit=1000, offset=0)["items"]
    return sorted((b["line_code"] or "konsol", b["message"]) for b in items)


def test_tarikan_pertama_menyimpan_semua_dan_berikutnya_cuma_yang_baru(tmp_path):
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1), _entri(2, 2)])
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=_Jam())

    asyncio.run(worker.run_once())
    line.entri.append(_entri(3, 3))
    asyncio.run(worker.run_once())

    assert _pesan(store) == [("line-1", "pesan 1"), ("line-1", "pesan 2"), ("line-1", "pesan 3")]
    assert [p[0] for p in line.permintaan] == [0, 2]


def test_tumpukan_ditarik_per_halaman_sampai_maks_per_putaran(tmp_path):
    store = LogStore(tmp_path / "log.db")
    jumlah = 100 * MAKS_HALAMAN + 30
    line = _LinePalsu([_entri(i, i) for i in range(1, jumlah + 1)])
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=_Jam())

    asyncio.run(worker.run_once())
    assert len(line.permintaan) == MAKS_HALAMAN
    assert store.kursor_line("line-1").seq == 100 * MAKS_HALAMAN

    asyncio.run(worker.run_once())
    assert store.kursor_line("line-1").seq == jumlah
    assert len(_pesan(store)) == jumlah


def test_line_versi_lama_404_diam_dan_ditanya_lagi_lima_menit_kemudian(tmp_path, caplog):
    store = LogStore(tmp_path / "log.db")
    lama = _LinePalsu([])
    lama.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "line-1 did not answer: 404", line="Line 1", status=404)
    jam = _Jam()
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": lama}), store, jam=jam, monotonik=jam)

    with caplog.at_level(logging.DEBUG, logger="palmgrade.workers.tarik_log_line_worker"):
        asyncio.run(worker.run_once())
        jam.t += JEDA_RUTE_TIDAK_ADA_S - 1
        asyncio.run(worker.run_once())
    assert len(lama.permintaan) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    lama.gagal = None
    lama.entri.append(_entri(1, 1))
    jam.t += 2
    asyncio.run(worker.run_once())
    assert _pesan(store) == [("line-1", "pesan 1")]


def test_line_mati_atau_menolak_kunci_ditunda_30_detik_tanpa_warning(tmp_path, caplog):
    store = LogStore(tmp_path / "log.db")
    mati = _LinePalsu([_entri(1, 1)])
    mati.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "tidak menjawab", line="Line 1")
    menolak = _LinePalsu([_entri(1, 1)])
    menolak.gagal = LineUnavailable(LINE_MENOLAK, "refused", line="Line 2", status=401)
    jam = _Jam()
    worker = TarikLogLineWorker(
        [LINE_1, LINE_2], _Klien({"line-1": mati, "line-2": menolak}), store, jam=jam, monotonik=jam
    )

    with caplog.at_level(logging.DEBUG):
        asyncio.run(worker.run_once())
        jam.t += JEDA_GAGAL_S - 1
        asyncio.run(worker.run_once())

    assert (len(mati.permintaan), len(menolak.permintaan)) == (1, 1)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_satu_line_mati_tidak_menahan_line_lain(tmp_path):
    store = LogStore(tmp_path / "log.db")
    mati = _LinePalsu([])
    mati.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "x", line="Line 1")
    hidup = _LinePalsu([_entri(1, 1)])
    worker = TarikLogLineWorker([LINE_1, LINE_2], _Klien({"line-1": mati, "line-2": hidup}), store, jam=_Jam())

    asyncio.run(worker.run_once())

    assert _pesan(store) == [("line-2", "pesan 1")]


def test_jawaban_cacat_tidak_menyimpan_dan_kursor_tidak_maju(tmp_path):
    store = LogStore(tmp_path / "log.db")

    class _KlienCacat:
        async def log_line(self, line, **_):
            return {"generasi": "g1", "entri": [{"id": 1}], "seq_akhir": 9, "lagi": False, "dibuang": 0}

    worker = TarikLogLineWorker([LINE_1], _KlienCacat(), store, jam=_Jam())
    asyncio.run(worker.run_once())

    assert _pesan(store) == []
    assert store.kursor_line("line-1").seq == 0


def test_konsol_restart_melanjutkan_dari_kursor_di_disk(tmp_path):
    line = _LinePalsu([_entri(1, 1), _entri(2, 2)])
    asyncio.run(TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), LogStore(tmp_path / "log.db"), jam=_Jam()).run_once())
    line.entri.append(_entri(3, 3))

    store_baru = LogStore(tmp_path / "log.db")  # proses konsol baru
    asyncio.run(TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store_baru, jam=_Jam()).run_once())

    assert line.permintaan[-1][0] == 2
    assert len(_pesan(store_baru)) == 3


def test_log_line_direset_ditarik_dari_awal_generasi_baru(tmp_path):
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1), _entri(2, 2)])
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=_Jam())
    asyncio.run(worker.run_once())

    line.generasi = "g2"
    line.entri = [_entri(1, 1)]
    line.entri[0]["message"] = "sesudah reset"
    asyncio.run(worker.run_once())

    assert ("line-1", "sesudah reset") in _pesan(store)
    assert store.kursor_line("line-1").generasi == "g2"


def test_error_baru_diteruskan_ke_digest_warning_tidak(tmp_path):
    store = LogStore(tmp_path / "log.db")
    digest = _Digest()
    line = _LinePalsu([_entri(1, 1, count=3), _entri(2, 2, level="WARNING")])
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, digest=digest, jam=_Jam())

    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())

    assert [(g.line_code, g.message, g.tambah) for g in digest.galat] == [("line-1", "pesan 1", 3)]


def test_baris_yang_dibuang_line_dilaporkan_sekali(tmp_path, caplog):
    store = LogStore(tmp_path / "log.db")

    class _KlienBuang:
        async def log_line(self, line, **_):
            return {"generasi": "g1", "entri": [], "seq_akhir": 0, "lagi": False, "dibuang": 12}

    worker = TarikLogLineWorker([LINE_1], _KlienBuang(), store, jam=_Jam())
    with caplog.at_level(logging.WARNING):
        asyncio.run(worker.run_once())
        asyncio.run(worker.run_once())

    peringatan = [r.getMessage() for r in caplog.records if "membuang" in r.getMessage()]
    assert peringatan == [
        "line-1 membuang 12 baris log sebelum sempat ditarik konsol (log line penuh saat konsol "
        "tidak menariknya). Galat yang tersisa tetap tampil di tab Log."
    ]


def test_putaran_yang_gagal_tidak_mematikan_tarikan(tmp_path, caplog):
    """Aturan 6: satu putaran yang melempar = satu WARNING, putaran berikutnya tetap jalan."""
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1)])
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, interval_s=0, jam=_Jam())
    asli = worker.run_once
    putaran: list[int] = []

    async def rusak_sekali() -> None:
        putaran.append(1)
        if len(putaran) == 1:
            raise RuntimeError("putaran rusak")
        await asli()

    worker.run_once = rusak_sekali

    async def jalankan() -> None:
        tugas = asyncio.create_task(worker.run_loop())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if _pesan(store):
                break
        tugas.cancel()

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.tarik_log_line_worker"):
        asyncio.run(jalankan())

    assert _pesan(store) == [("line-1", "pesan 1")]
    assert [r.getMessage() for r in caplog.records] == ["Tarikan log line gagal satu putaran"]


def test_store_konsol_rusak_menunda_line_itu_saja(tmp_path, caplog):
    store = LogStore(tmp_path / "log.db")
    satu, dua = _LinePalsu([_entri(1, 1)]), _LinePalsu([_entri(1, 1)])

    class _StoreRusakUntukLine1:
        def kursor_line(self, line_code):
            if line_code == "line-1":
                raise OSError("disk konsol penuh")
            return store.kursor_line(line_code)

        def serap_line(self, line_code, jawaban, *, now):
            return store.serap_line(line_code, jawaban, now=now)

    jam = _Jam()
    worker = TarikLogLineWorker(
        [LINE_1, LINE_2], _Klien({"line-1": satu, "line-2": dua}), _StoreRusakUntukLine1(),
        jam=jam, monotonik=jam,
    )
    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.tarik_log_line_worker"):
        asyncio.run(worker.run_once())

    assert _pesan(store) == [("line-2", "pesan 1")]
    (pesan,) = _peringatan(caplog)
    assert "line-1" in pesan and "OSError" in pesan

def _peringatan(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_jam_dinding_mundur_tidak_memperpanjang_penundaan(tmp_path):
    """NTP yang memundurkan jam PC pabrik sejam tidak boleh membuat tab Log diam sejam."""
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1)])
    line.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "tidak menjawab", line="Line 1")
    dinding, monoton = _Jam(), _Jam()
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=dinding, monotonik=monoton)

    asyncio.run(worker.run_once())
    line.gagal = None
    dinding.t -= 3600
    monoton.t += JEDA_GAGAL_S + 1
    asyncio.run(worker.run_once())

    assert _pesan(store) == [("line-1", "pesan 1")]


def test_jam_dinding_maju_tidak_memotong_penundaan(tmp_path):
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1)])
    line.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "tidak menjawab", line="Line 1")
    dinding, monoton = _Jam(), _Jam()
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=dinding, monotonik=monoton)

    asyncio.run(worker.run_once())
    dinding.t += 86400
    monoton.t += 1
    asyncio.run(worker.run_once())

    assert len(line.permintaan) == 1


def test_galat_tak_terduga_satu_line_tidak_menahan_line_lain(tmp_path, caplog):
    store = LogStore(tmp_path / "log.db")
    hidup = _LinePalsu([_entri(1, 1)])
    diminta: list[str] = []

    class _KlienSatuRusak:
        async def log_line(self, line, *, setelah, generasi, batas):
            diminta.append(line.line_code)
            if line.line_code == "line-1":
                raise httpx.InvalidURL("alamat line-1 rusak")
            return hidup.jawab(setelah, generasi, batas)

    jam = _Jam()
    worker = TarikLogLineWorker([LINE_1, LINE_2], _KlienSatuRusak(), store, jam=jam, monotonik=jam)
    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.tarik_log_line_worker"):
        asyncio.run(worker.run_once())
        jam.t += JEDA_GAGAL_S - 1
        asyncio.run(worker.run_once())  # line-1 masih ditunda
        jam.t += 2
        asyncio.run(worker.run_once())  # dicoba lagi, masih rusak: tidak ada peringatan kedua

    assert _pesan(store) == [("line-2", "pesan 1")]
    assert diminta.count("line-1") == 2
    (pesan,) = _peringatan(caplog)
    assert "line-1" in pesan and "InvalidURL" in pesan


def test_log_line_mati_503_diperingatkan_sekali_lalu_pulih(tmp_path, caplog):
    """Line yang log_line.db-nya tidak bisa dibuka menjawab 503 `log_line_mati`:
    support harus tahu, sekali, bukan diam seperti line mati."""
    store = LogStore(tmp_path / "log.db")
    line = _LinePalsu([_entri(1, 1)])
    line.gagal = LineUnavailable(LINE_TIDAK_MENJAWAB, "503", line="Line 1", status=503)
    jam = _Jam()
    worker = TarikLogLineWorker([LINE_1], _Klien({"line-1": line}), store, jam=jam, monotonik=jam)

    with caplog.at_level(logging.WARNING, logger="palmgrade.workers.tarik_log_line_worker"):
        asyncio.run(worker.run_once())
        jam.t += JEDA_GAGAL_S + 1
        asyncio.run(worker.run_once())  # masih 503
        line.gagal = None
        jam.t += JEDA_GAGAL_S + 1
        asyncio.run(worker.run_once())
        asyncio.run(worker.run_once())  # sehat terus: tidak ada peringatan lagi

    peringatan = _peringatan(caplog)
    assert len(peringatan) == 2
    assert "line-1" in peringatan[0] and "log_line.db" in peringatan[0]
    assert "line-1" in peringatan[1] and "kembali" in peringatan[1]
    assert _pesan(store) == [("line-1", "pesan 1")]
    assert len(line.permintaan) == 4
