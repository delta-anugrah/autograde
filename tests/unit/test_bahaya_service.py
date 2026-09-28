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
from bahaya_palsu import HASH, LINES, LinePalsu, buka_tiket, hitung, isi_data

from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.bahaya import MODE_SEMUA, MODE_TRANSAKSI
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.akun_bawaan import EMAIL_BAWAAN, EMAIL_SUPPORT
from palmgrade.services.bahaya_service import (
    BahayaDitolak,
    BahayaSemuaMenolak,
    BahayaService,
    BahayaTidakSah,
)

HARI = "2026-09-25"


@pytest.fixture
def rakit(tmp_path):
    def buat(
        *, erp_aktif=True, hash_bawaan=HASH, hash_support=HASH, tarik_master=None, tunggu_mati_s=2.0
    ):
        store = ConsoleStore(tmp_path / "console.db")
        log = LogStore(tmp_path / "log.db")
        outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
        manifest = ErpOutboxStore(tmp_path / "manifest_outbox.db")
        line = LinePalsu()
        svc = BahayaService(
            store, log, line, LINES, outbox, manifest,
            erp_aktif=erp_aktif, hash_bawaan=hash_bawaan, hash_support=hash_support,
            hari_kerja=lambda: HARI,
            tarik_master=tarik_master, tunggu_mati_s=tunggu_mati_s, jeda_cek_s=0.0,
        )
        return svc, store, log, outbox, manifest, line
    return buat


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
    isi_data(store)

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


@pytest.mark.parametrize("hash_support", ["", "sandi-mentah-bukan-hash"])
def test_mode_semua_butuh_hash_support_yang_terbaca(rakit, hash_support):
    """Hash operator saja tidak cukup: sesudah mode semua cuma akun bawaan yang
    kembali, dan tanpa akun SUPPORT Danger Zone ikut terkunci. Hash yang tidak
    terbaca (sandi mentah, `$` dimakan compose) tidak akan dibuat jadi akun."""
    svc, *_ = rakit(erp_aktif=False, hash_bawaan=HASH, hash_support=hash_support)
    r = asyncio.run(svc.ringkasan())
    assert r["aksi"]["semua"]["hambatan"] == [{"kode": "tanpa_sumber_akun"}]


def test_antrean_line_gagal_diperingatkan(rakit):
    """Janjang yang ditolak konsol berkali-kali (`outbox_failed`) ikut hilang
    bersama `outbox.db` — bukan hambatan (tidak akan pernah terkirim), tapi disebut."""
    svc, _store, _log, _o, _m, line = rakit()
    line.detail["line-2"]["outbox_failed"] = 3

    r = asyncio.run(svc.ringkasan())

    assert r["aksi"]["transaksi"]["hambatan"] == []
    assert {"kode": "antrean_line_gagal", "line": "line-2", "jumlah": 3} in (
        r["aksi"]["transaksi"]["peringatan"]
    )


# ── tiket timbang terbuka ───────────────────────────────────────────────────


def test_tiket_terbuka_hari_ini_menolak_hapus(rakit):
    """Truk di tengah kunjungan: bruto-nya sudah ditimbang dan itu yang dibayar.
    Menghapusnya membuat neto truk itu tidak pernah bisa dihitung."""
    svc, store, _log, _o, _m, line = rakit()
    isi_data(store)
    buka_tiket(store, hari=HARI)
    buka_tiket(store, hari=HARI, tara=5200.0, nomor="w-lengkap")  # sudah keluar: bukan hambatan

    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert exc.value.hambatan == [{"kode": "tiket_terbuka", "jumlah": 1}]
    assert line.perintah == []
    assert hitung(store, "weighings") == 2


def test_tiket_terbuka_hari_lama_cuma_diperingatkan(rakit):
    """Tiket kemarin yang taranya tidak pernah diisi hampir pasti sisa uji coba —
    menghambatnya membuat tombol tidak bisa dipakai tanpa membereskan sampah dulu."""
    svc, store, *_ = rakit()
    buka_tiket(store, hari="2026-09-20")

    r = asyncio.run(svc.ringkasan())

    assert r["aksi"]["transaksi"]["hambatan"] == []
    assert {"kode": "tiket_lama_terbuka", "jumlah": 1} in r["aksi"]["transaksi"]["peringatan"]


# ── hapus data ──────────────────────────────────────────────────────────────


def test_konfirmasi_salah_tidak_mengirim_apa_pun(rakit):
    svc, store, _log, _o, _m, line = rakit()
    isi_data(store)

    with pytest.raises(BahayaTidakSah) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="hapus", oleh="s@pks.id"))

    assert exc.value.code == "konfirmasi_salah"
    assert line.perintah == []
    assert hitung(store, "inspections") == 1


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
    isi_data(store)
    line.detail["line-2"]["outbox_pending"] = 4

    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert exc.value.code == "bahaya_ditolak"
    assert exc.value.hambatan == [{"kode": "antrean_line", "line": "line-2", "jumlah": 4}]
    assert line.perintah == []
    assert hitung(store, "inspections") == 1


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
    isi_data(store)
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
    assert hitung(store, "inspections") == 0
    assert hitung(store, "trucks") == 1  # mode transaksi: master tetap
    assert hitung(store, "sesi") == 1  # tidak ada yang keluar
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
    isi_data(store)
    janjang_saat_line_hidup: list[int] = []
    line.saat_hidup_dicek = lambda _line: janjang_saat_line_hidup.append(
        hitung(store, "inspections")
    )

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert janjang_saat_line_hidup, "konsol tidak menunggu line sama sekali"
    assert all(n == 1 for n in janjang_saat_line_hidup)
    assert hitung(store, "inspections") == 0


def test_line_menolak_di_tengah_konsol_tetap_dikosongkan(rakit):
    svc, store, _log, _o, _m, line = rakit()
    isi_data(store)
    line.tolak_hapus.add("line-2")

    hasil = asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": False, "kode": "truk_terpasang"}
    assert per_line["line-1"]["ok"] and per_line["line-3"]["ok"]
    assert hitung(store, "inspections") == 0


def test_semua_line_menolak_tidak_ada_yang_dihapus(rakit, jejak):
    """Tidak satu line pun menerima = foto semua line masih utuh. Mengosongkan
    konsol di titik ini membuang index yang menunjuk foto-foto itu."""
    svc, store, log, outbox, _m, line = rakit(erp_aktif=False)
    jejak(log)
    isi_data(store)
    outbox.enqueue("visit", "k1", {"x": 1})
    line.status_hapus = {
        "line-1": (404, '{"detail":"Not Found"}'),
        "line-2": (403, '{"error":"LICENSE_INVALID","status":"expired"}'),
        "line-3": (409, '{"detail":{"kode":"truk_terpasang"}}'),
    }

    with pytest.raises(BahayaSemuaMenolak) as exc:
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s@pks.id"))

    assert exc.value.code == "semua_line_menolak"
    assert exc.value.params == {"lines": "line-1:versi_lama,line-2:lisensi,line-3:truk_terpasang"}
    assert hitung(store, "inspections") == 1
    assert outbox.pending_count() == 1
    baris = log.read(level=None, search="Danger Zone", limit=5, offset=0)["items"]
    assert baris and "s@pks.id" in baris[0]["message"]


def test_penolakan_line_dibaca_dari_status_http(rakit):
    """404 = line versi lama tanpa lane ini; 403 = lisensi line habis (middleware
    lisensi menolak semua `/internal/*`). Tindakannya beda dari "ditolak" biasa."""
    svc, store, _log, _o, _m, line = rakit()
    isi_data(store)
    line.status_hapus = {
        "line-1": (404, '{"detail":"Not Found"}'),
        "line-2": (403, '{"error":"LICENSE_INVALID","status":"expired"}'),
    }

    hasil = asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-1"] == {"line_code": "line-1", "ok": False, "kode": "versi_lama"}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": False, "kode": "lisensi"}
    assert per_line["line-3"] == {"line_code": "line-3", "ok": True}
    assert hitung(store, "inspections") == 0  # satu line menerima: konsol dikosongkan


def test_perintah_hapus_dikirim_bersamaan(rakit):
    """Berurutan = line yang lambat menjawab membuat line lain sudah restart
    sementara line terakhir belum ditanya."""
    svc, _store, _log, _o, _m, line = rakit()

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert [arah for arah, _ in line.urutan[:3]] == ["masuk", "masuk", "masuk"]


def test_tidak_memeriksa_line_sebelum_jedanya_habis(rakit):
    """Line masih hidup `jeda_detik` sesudah menjawab — memeriksanya lebih awal
    cuma membuang pertanyaan, dan satu tenggat lewat di situ terbaca mati."""
    svc, _store, _log, _o, _m, line = rakit()
    line.jeda = 0.2
    dicek: list[float] = []
    line.saat_hidup_dicek = lambda _l: dicek.append(time.monotonic())
    mulai = time.monotonic()

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert dicek and min(dicek) - mulai >= 0.2


def test_sekali_tidak_menjawab_belum_dianggap_mati(rakit):
    """`/health` yang sekali lewat tenggat (line sibuk) bukan line yang mati:
    butuh dua kali berturut-turut."""
    svc, _store, _log, _o, _m, line = rakit()
    line.hidup_urutan = {"line-1": [True, False, True, False, False]}

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert line.hidup_dicek.count("line-1") == 5


def test_line_yang_tidak_kunjung_mati_disebut(rakit):
    svc, store, _log, _o, _m, line = rakit(tunggu_mati_s=0.3)
    isi_data(store)
    line.selalu_hidup.add("line-2")

    hasil = asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": True, "kode": "belum_mati"}
    assert per_line["line-1"] == {"line_code": "line-1", "ok": True}
    assert hitung(store, "inspections") == 0


def test_penugasan_dikunci_selama_hapus_dan_dibuka_sesudahnya(rakit):
    """`ConsoleService.assign_truck` membaca tanda ini: truk yang dipasang di
    tengah penghapusan digrading ke penugasan yang barisnya ikut terhapus."""
    svc, store, _log, _o, _m, line = rakit()
    terlihat: list[bool] = []
    line.saat_hidup_dicek = lambda _l: terlihat.append(store.hapus_berjalan)

    asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert terlihat and all(terlihat)
    assert store.hapus_berjalan is False


def test_penugasan_dibuka_lagi_walau_hapus_ditolak(rakit):
    svc, store, _log, _o, _m, line = rakit()
    line.detail["line-1"]["current_assignment_id"] = "assign-1"
    with pytest.raises(BahayaDitolak):
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))
    line.detail["line-1"]["current_assignment_id"] = None
    line.status_hapus = {c.line_code: (404, "{}") for c in LINES}
    with pytest.raises(BahayaSemuaMenolak):
        asyncio.run(svc.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))
    assert store.hapus_berjalan is False


def test_hapus_semua_membuat_ulang_akun_bawaan_dan_menarik_master(rakit):
    ditarik: list[bool] = []

    async def tarik():
        ditarik.append(True)
        return 0

    svc, store, *_ = rakit(tarik_master=tarik)
    isi_data(store)

    asyncio.run(svc.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s"))

    assert hitung(store, "trucks") == 0
    assert hitung(store, "sesi") == 0
    assert store.operator_by_email("ani@pks.id") is None
    assert store.operator_by_email(EMAIL_BAWAAN) is not None
    assert store.operator_by_email(EMAIL_SUPPORT)["role"] == "support"
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'
    assert ditarik == [True]


def test_tarikan_master_gagal_tidak_menggagalkan_hapus(rakit):
    async def tarik():
        raise RuntimeError("AutoERP tidak menjawab")

    svc, store, *_ = rakit(tarik_master=tarik)
    isi_data(store)

    hasil = asyncio.run(svc.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s"))

    assert hasil["mode"] == MODE_SEMUA
    assert hitung(store, "trucks") == 0


def test_hapus_semua_tanpa_sumber_akun_ditolak(rakit):
    svc, store, *_, line = rakit(erp_aktif=False, hash_bawaan="", hash_support="")
    isi_data(store)

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
    isi_data(store)

    assert svc.logout_semua(oleh="s") == {"sesi_dihapus": 1}
    assert hitung(store, "sesi") == 0
    assert hitung(store, "operators") == 1


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
