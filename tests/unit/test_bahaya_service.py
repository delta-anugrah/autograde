"""`BahayaService` — lima aksi Danger Zone dengan store SUNGGUHAN dan line palsu.

Line palsu mencatat perintah yang diterimanya, jadi tiap test bisa membuktikan
dua hal sekaligus: apa yang terjadi, dan apa yang TIDAK terjadi (perintah hapus
yang tidak pernah boleh terkirim saat konfirmasi salah atau ada hambatan).
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from palmgrade.core.config import LineEndpoint
from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.bahaya import MODE_SEMUA, MODE_TRANSAKSI
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.akun_bawaan import EMAIL_BAWAAN, EMAIL_SUPPORT
from palmgrade.services.bahaya_service import BahayaDitolak, BahayaService, BahayaTidakSah

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)
HASH = hash_password("sandi-bawaan-uji")


class LinePalsu:
    """Tiga line yang sehat, kecuali diubah per test."""

    def __init__(self) -> None:
        self.detail = {
            ln.line_code: {"outbox_pending": 0, "current_assignment_id": None} for ln in LINES
        }
        self.mati: set[str] = set()
        self.merekam: set[str] = set()
        self.tolak_hapus: set[str] = set()
        self.perintah: list[tuple[str, str]] = []
        self.hidup_sisa: dict[str, int] = {}
        self.saat_hidup_dicek = None

    def _cek(self, line: LineEndpoint) -> None:
        if line.line_code in self.mati:
            raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} mati", line=line.name)

    async def health_detail(self, line):
        self._cek(line)
        return dict(self.detail[line.line_code])

    async def rekam_berkas(self, line):
        self._cek(line)
        return {"line_code": line.line_code, "berkas": 2, "bytes": 1000,
                "merekam": line.line_code in self.merekam}

    async def hapus_data(self, line, *, mode, diminta_oleh):
        self._cek(line)
        if line.line_code in self.tolak_hapus:
            raise LinePlcTolak(409, '{"detail":{"kode":"truk_terpasang"}}')
        self.perintah.append(("hapus_data", line.line_code))
        self.hidup_sisa[line.line_code] = 2  # masih menjawab dua kali, lalu mati
        return {"status": "menghapus"}

    async def rekam_hapus(self, line):
        self._cek(line)
        if line.line_code in self.merekam:
            raise LinePlcTolak(409, '{"detail":{"kode":"sedang_merekam"}}')
        self.perintah.append(("rekam_hapus", line.line_code))
        return {"line_code": line.line_code, "berkas": 2, "bytes": 1000}

    async def restart(self, line):
        self._cek(line)
        self.perintah.append(("restart", line.line_code))

    async def hidup(self, line):
        if self.saat_hidup_dicek:
            self.saat_hidup_dicek(line)
        sisa = self.hidup_sisa.get(line.line_code, 0)
        if sisa > 0:
            self.hidup_sisa[line.line_code] = sisa - 1
            return True
        return False


@pytest.fixture
def rakit(tmp_path):
    def buat(*, erp_aktif=True, hash_bawaan=HASH, hash_support=HASH, tarik_master=None):
        store = ConsoleStore(tmp_path / "console.db")
        log = LogStore(tmp_path / "log.db")
        outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
        manifest = ErpOutboxStore(tmp_path / "manifest_outbox.db")
        line = LinePalsu()
        svc = BahayaService(
            store, log, line, LINES, outbox, manifest,
            erp_aktif=erp_aktif, hash_bawaan=hash_bawaan, hash_support=hash_support,
            tarik_master=tarik_master, tunggu_mati_s=2.0, jeda_cek_s=0.0,
        )
        return svc, store, log, outbox, manifest, line
    return buat


def _isi_data(store: ConsoleStore) -> None:
    with store._lock, store._db:
        store._db.execute(
            "INSERT INTO inspections (event_id, machine_id, line_code, work_date, timestamp, "
            "ripeness_status, capture_type, received_at) VALUES ('e1', 'm-1', 'line-1', "
            "'2026-09-25', '2026-09-25T01:00:00Z', 'ACC', 'auto', ?)", (time.time(),),
        )
        store._db.execute("INSERT INTO trucks (id, plate_number) VALUES ('t1', 'B1234XY')")
    store.set_state("setelan_grading", '{"conf_threshold": 0.6}')
    oid = store.upsert_operator_manual(
        {"email": "ani@pks.id", "full_name": "Ani", "password_hash": HASH}
    )
    store.create_session("tok", oid, now=time.time(), ttl_s=3600)


def _hitung(store: ConsoleStore, tabel: str) -> int:
    with store._lock:
        return store._db.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]


@pytest.fixture
def jejak(tmp_path):
    """Log sink sungguhan (yang dipasang lifespan konsol), ke LogStore uji."""
    dipasang: list[logging.Handler] = []

    def pasang(log: LogStore):
        dipasang.append(install_log_sink(log))

    yield pasang
    for h in dipasang:
        logging.getLogger().removeHandler(h)


# ── ringkasan ───────────────────────────────────────────────────────────────


def test_ringkasan_line_sehat(rakit):
    svc, store, *_ = rakit()
    _isi_data(store)

    r = asyncio.run(svc.ringkasan())

    assert r["aksi"]["transaksi"]["hambatan"] == []
    assert r["aksi"]["semua"]["hambatan"] == []
    assert r["data"]["janjang"] == 1
    assert r["aksi"]["logout"]["sesi_aktif"] == 1
    assert r["aksi"]["rekaman"] == {"berkas": 6, "bytes": 3000, "peringatan": []}
    assert [ln["line_code"] for ln in r["lines"]] == ["line-1", "line-2", "line-3"]


def test_ringkasan_menyebut_hambatan_per_line(rakit):
    svc, _store, _log, _outbox, _m, line = rakit()
    line.mati.add("line-2")
    line.detail["line-3"]["current_assignment_id"] = "assign-9"

    r = asyncio.run(svc.ringkasan())

    assert r["aksi"]["transaksi"]["hambatan"] == [
        {"kode": "line_mati", "line": "line-2"},
        {"kode": "truk_terpasang", "line": "line-3"},
    ]
    assert {"kode": "line_mati", "line": "line-2"} in r["aksi"]["restart"]["peringatan"]


def test_ringkasan_mode_semua_tanpa_sumber_akun(rakit):
    svc, *_ = rakit(erp_aktif=False, hash_bawaan="", hash_support="")
    r = asyncio.run(svc.ringkasan())
    assert r["aksi"]["semua"]["hambatan"] == [{"kode": "tanpa_sumber_akun"}]
    assert r["aksi"]["transaksi"]["hambatan"] == []


# ── hapus data ──────────────────────────────────────────────────────────────


def test_konfirmasi_salah_tidak_mengirim_apa_pun(rakit):
    svc, store, _log, _o, _m, line = rakit()
    _isi_data(store)

    with pytest.raises(BahayaTidakSah) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="hapus", oleh="s@pks.id"))

    assert exc.value.code == "konfirmasi_salah"
    assert line.perintah == []
    assert _hitung(store, "inspections") == 1


def test_mode_asing_ditolak(rakit):
    svc, *_ , line = rakit()
    with pytest.raises(BahayaTidakSah) as exc:
        asyncio.run(svc.hapus_data(mode="semuanya", konfirmasi="HAPUS", oleh="s"))
    assert exc.value.code == "mode_asing"
    assert line.perintah == []


def test_hambatan_menolak_dan_tidak_menghapus(rakit):
    """Kondisi berubah antara panel dibuka dan tombol ditekan: server yang
    memutuskan, bukan layar."""
    svc, store, _log, _o, _m, line = rakit()
    _isi_data(store)
    line.detail["line-2"]["outbox_pending"] = 4

    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert exc.value.code == "bahaya_ditolak"
    assert exc.value.hambatan == [{"kode": "antrean_line", "line": "line-2", "jumlah": 4}]
    assert line.perintah == []
    assert _hitung(store, "inspections") == 1


def test_antrean_erp_pending_menolak(rakit):
    svc, store, _log, outbox, _m, line = rakit()
    outbox.enqueue("visit", "k1", {"x": 1})

    with pytest.raises(BahayaDitolak):
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))
    assert outbox.pending_count() == 1
    assert line.perintah == []


def test_hapus_transaksi_sukses(rakit, jejak):
    svc, store, log, outbox, manifest, line = rakit(erp_aktif=False)
    jejak(log)
    _isi_data(store)
    outbox.enqueue("visit", "k1", {"x": 1})  # ERP mati: diperingatkan, ikut terhapus
    manifest.enqueue("manifest", "m1", {"y": 1})
    log.write("ERROR", "lama", "galat lama", None, now=time.time())

    hasil = asyncio.run(
        svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi=" HAPUS ", oleh="support@pks.id")
    )

    assert sorted(line.perintah) == [
        ("hapus_data", "line-1"), ("hapus_data", "line-2"), ("hapus_data", "line-3"),
    ]
    assert all(r["ok"] for r in hasil["lines"])
    assert _hitung(store, "inspections") == 0
    assert _hitung(store, "trucks") == 1  # mode transaksi: master tetap
    assert _hitung(store, "sesi") == 1  # tidak ada yang keluar
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'
    assert outbox.pending_count() == 0
    assert manifest.pending_count() == 0
    # Log lama hilang; jejak siapa yang menghapus jadi baris PERTAMA log baru.
    baris = log.read(level=None, search=None, limit=10, offset=0)["items"]
    assert len(baris) == 1
    assert "support@pks.id" in baris[0]["message"]
    assert "transaksi" in baris[0]["message"]


def test_menunggu_line_mati_sebelum_menghapus_konsol(rakit):
    """Line keluar 1 detik sesudah menjawab, dan janjang yang lewat di detik itu
    masih dikirim ke konsol. Data konsol baru boleh dihapus sesudah line diam —
    kalau lebih cepat, baris grading yang fotonya sudah hilang tertinggal."""
    svc, store, _log, _o, _m, line = rakit()
    _isi_data(store)
    janjang_saat_line_hidup: list[int] = []
    line.saat_hidup_dicek = lambda _line: janjang_saat_line_hidup.append(
        _hitung(store, "inspections")
    )

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert janjang_saat_line_hidup, "konsol tidak menunggu line sama sekali"
    assert all(n == 1 for n in janjang_saat_line_hidup)
    assert _hitung(store, "inspections") == 0


def test_line_menolak_di_tengah_konsol_tetap_dikosongkan(rakit):
    svc, store, _log, _o, _m, line = rakit()
    _isi_data(store)
    line.tolak_hapus.add("line-2")

    hasil = asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": False, "kode": "truk_terpasang"}
    assert per_line["line-1"]["ok"] and per_line["line-3"]["ok"]
    assert _hitung(store, "inspections") == 0


def test_hapus_semua_membuat_ulang_akun_bawaan_dan_menarik_master(rakit):
    ditarik: list[bool] = []

    async def tarik():
        ditarik.append(True)
        return 0

    svc, store, *_ = rakit(tarik_master=tarik)
    _isi_data(store)

    asyncio.run(svc.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s"))

    assert _hitung(store, "trucks") == 0
    assert _hitung(store, "sesi") == 0
    assert store.operator_by_email("ani@pks.id") is None
    assert store.operator_by_email(EMAIL_BAWAAN) is not None
    assert store.operator_by_email(EMAIL_SUPPORT)["role"] == "support"
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'
    assert ditarik == [True]


def test_tarikan_master_gagal_tidak_menggagalkan_hapus(rakit):
    async def tarik():
        raise RuntimeError("AutoERP tidak menjawab")

    svc, store, *_ = rakit(tarik_master=tarik)
    _isi_data(store)

    hasil = asyncio.run(svc.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s"))

    assert hasil["mode"] == MODE_SEMUA
    assert _hitung(store, "trucks") == 0


def test_hapus_semua_tanpa_sumber_akun_ditolak(rakit):
    svc, store, *_, line = rakit(erp_aktif=False, hash_bawaan="", hash_support="")
    _isi_data(store)

    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s"))

    assert exc.value.hambatan == [{"kode": "tanpa_sumber_akun"}]
    assert store.operator_by_email("ani@pks.id") is not None
    assert line.perintah == []


# ── restart, logout, rekaman ────────────────────────────────────────────────


def test_restart_semua_hasil_per_line(rakit, jejak):
    svc, _store, log, _o, _m, line = rakit()
    jejak(log)
    line.mati.add("line-3")

    hasil = asyncio.run(svc.restart_semua(oleh="s@pks.id"))

    assert [(r["line_code"], r["ok"]) for r in hasil["lines"]] == [
        ("line-1", True), ("line-2", True), ("line-3", False),
    ]
    assert ("restart", "line-1") in line.perintah
    baris = log.read(level=None, search="Restart", limit=5, offset=0)["items"]
    assert baris and "s@pks.id" in baris[0]["message"]


def test_logout_semua(rakit):
    svc, store, *_ = rakit()
    _isi_data(store)

    assert svc.logout_semua(oleh="s") == {"sesi_dihapus": 1}
    assert _hitung(store, "sesi") == 0
    assert _hitung(store, "operators") == 1


def test_hapus_rekaman_perlu_konfirmasi(rakit):
    svc, *_, line = rakit()
    with pytest.raises(BahayaTidakSah):
        asyncio.run(svc.hapus_rekaman(konfirmasi="", oleh="s"))
    assert line.perintah == []


def test_hapus_rekaman_melewati_line_yang_merekam_dan_mati(rakit):
    svc, *_, line = rakit()
    line.merekam.add("line-2")
    line.mati.add("line-3")

    hasil = asyncio.run(svc.hapus_rekaman(konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-1"] == {"line_code": "line-1", "ok": True, "berkas": 2, "bytes": 1000}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": False, "kode": "sedang_merekam"}
    assert per_line["line-3"] == {"line_code": "line-3", "ok": False, "kode": "line_mati"}
    assert hasil["berkas"] == 2
    assert hasil["bytes"] == 1000
