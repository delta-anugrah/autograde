"""OPS-2: satu truk fisik harus jadi satu baris, sekali saja, saat pasang PC.

Kenapa ini ada: PC pabrik yang sudah jalan menyimpan truk ber-id acak dari
palmgrade-api (`gen_random_uuid()`), sedangkan AutoGrade menurunkan id dari plat
(`uuid5`). Plat **tidak** punya indeks unik, jadi tarikan master data pertama
menambah baris kedua untuk truk yang sama, dan tonase satu truk terbelah dua tanpa
ada apa pun di layar yang mengatakannya.

Yang dijaga di sini bukan "fungsinya jalan", tapi hal-hal yang kalau salah merusak
angka yang dibayar ke petani:

- id acak lama **tidak bisa** dihitung ulang dari plat, jadi jembatannya cuma plat
  ternormalisasi; kalau pencocokannya beda sedikit saja, penggabungannya salah truk
- `truck_id` hidup di **tiga** tabel (`inspections`, `assignments`, `weighings`).
  Kelewat satu = baris itu menggantung ke id yang sudah tidak ada, dan tonasenya
  hilang dari rekap
- rekonsiliasi dijalankan orang yang sedang pasang PC, sering dua kali karena ragu.
  Jalan kedua tidak boleh mengubah apa pun
"""

from __future__ import annotations

import pytest

from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.rekonsiliasi import rekonsiliasi_truk

# Bentuk id yang dipakai palmgrade-api: uuid4 acak, tidak ada hubungannya dengan plat.
ID_LAMA = "7f3a9b21-0000-4000-8000-000000000001"
ID_LAMA_2 = "7f3a9b21-0000-4000-8000-000000000002"


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


def _truk_gaya_lama(store: ConsoleStore, truck_id: str, plat: str, **over) -> None:
    """Baris truk seperti yang ditinggalkan palmgrade-api di PC pabrik."""
    row = {"id": truck_id, "plate_number": plat, "status": "active"}
    row.update(over)
    store.upsert_truck(row)


def _timbangan(store: ConsoleStore, wid: str, truck_id: str, plat: str, **over) -> None:
    row = {
        "id": wid,
        "ref": None,
        "plate_number": plat,
        "plate_norm": plat.replace(" ", "").replace("-", "").upper(),
        "truck_id": truck_id,
        "work_date": "2026-09-15",
        "gross_kg": 13250.0,
        "tare_kg": None,
        "net_kg": None,
        "entered_at": "2026-09-15T08:55:00+07:00",
        "exited_at": None,
    }
    row.update(over)
    store.upsert_weighing(row)


def _inspeksi(store: ConsoleStore, event_id: str, truck_id: str) -> None:
    store.add_inspection(
        {
            "event_id": event_id,
            "machine_id": "m-1",
            "line_code": "line-1",
            "work_date": "2026-09-15",
            "timestamp": "2026-09-15T09:00:00+07:00",
            "ripeness_status": "ACC",
            "ripeness_confidence": 0.9,
            "capture_type": "auto",
            "image_path": "captures/results/2026-09-15/a.webp",
            "truck_id": truck_id,
            "assignment_id": "asg-1",
            "prediction": "Acc",
            "tp_status": None,
            "tp_confidence": None,
        }
    )


# ── inti: dua baris jadi satu ─────────────────────────────────────────────────


def test_truk_berplat_sama_digabung_jadi_satu_baris(store):
    """Ini seluruh alasan OPS-2 ada. Sebelum digabung operator melihat dua truk
    berplat sama di dropdown dan tidak tahu harus pilih yang mana."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})
    assert len([t for t in store.trucks() if t["plate_number"] == "BE 4412 OFL"]) == 2

    hasil = rekonsiliasi_truk(store)

    sisa = [t for t in store.trucks() if t["plate_number"] == "BE 4412 OFL"]
    assert len(sisa) == 1
    assert sisa[0]["id"] == baru, "yang disisakan harus id turunan plat, bukan id acak"
    assert hasil.digabung == 1


def test_baris_yang_disisakan_menyimpan_erp_name(store):
    """`erp_name` itu tautan ke AutoERP. Hilang = truk naik lagi sebagai truk baru
    tanpa pemilik, dan backoffice melengkapi truk yang sama dua kali."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})

    rekonsiliasi_truk(store)

    assert store.truck(baru)["erp_name"] == "TRK-0001"


def test_supplier_dari_baris_lama_tidak_hilang(store):
    """Label Sumber TBS dibaca dari truk, bukan disalin ke baris grading. Supplier
    yang hilang saat penggabungan mengubah label di seluruh riwayat truk itu."""
    store.upsert_supplier({"id": "sup-1", "name": "Koperasi A", "sumber": "Plasma"})
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL", supplier_id="sup-1")
    baru = truck_id_for("BE 4412 OFL")
    # Tarikan ERP datang tanpa supplier (truk belum dilengkapi backoffice).
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.truck(baru)["supplier_id"] == "sup-1"


# ── tiga tabel yang memegang truck_id ────────────────────────────────────────


def test_timbangan_ikut_dipindah(store):
    """Kalau tidak: neto-nya menggantung ke id yang sudah dihapus dan hilang dari
    rekap, padahal itu angka yang dibayar."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _timbangan(store, "w-1", ID_LAMA, "BE 4412 OFL")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.weighing("w-1")["truck_id"] == baru


def test_grading_ikut_dipindah(store):
    """Janjang yang menggantung tidak muncul di rekap truk mana pun."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _inspeksi(store, "ev-1", ID_LAMA)
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    rekap = {r["truck_id"]: r for r in store.rekap_truk("2026-09-15")}
    assert baru in rekap
    assert ID_LAMA not in rekap
    assert rekap[baru]["total"] == 1


def test_penugasan_line_yang_sedang_jalan_ikut_dipindah(store):
    """Rekonsiliasi dijalankan saat pasang PC, dan pabrik bisa sedang jalan. Truk
    yang sedang di line harus tetap di line-nya sesudah digabung."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    store.set_assignment("line-1", "asg-1", ID_LAMA)
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    assert store.assignments()["line-1"]["truck_id"] == baru


# ── pencocokan plat ─────────────────────────────────────────────────────────


def test_plat_beda_tulisan_tetap_dianggap_satu_truk(store):
    """Plat yang sama diketik operator, program timbangan, dan ERP dengan tiga gaya
    berbeda. Pencocokan harus memakai bentuk ternormalisasi yang sama dengan
    `truck_id_for`, kalau tidak truk yang mestinya digabung malah dilewati."""
    _truk_gaya_lama(store, ID_LAMA, "be-4412-ofl")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    hasil = rekonsiliasi_truk(store)

    assert hasil.digabung == 1
    assert len([t for t in store.trucks()]) == 1


def test_truk_berplat_beda_tidak_pernah_disentuh(store):
    """Penggabungan yang kelewat agresif menggabung dua truk berbeda, dan tonase
    satu petani mendarat di petani lain. Ini yang paling mahal kalau salah."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _truk_gaya_lama(store, ID_LAMA_2, "BE 9999 XYZ")
    _timbangan(store, "w-2", ID_LAMA_2, "BE 9999 XYZ")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    rekonsiliasi_truk(store)

    # Truk kedua ikut dibetulkan id-nya (memang harus), tapi tetap jadi barisnya
    # sendiri: platnya utuh dan timbangannya ikut ke sana, bukan ke truk pertama.
    lain = truck_id_for("BE 9999 XYZ")
    assert store.truck(lain)["plate_number"] == "BE 9999 XYZ"
    assert store.weighing("w-2")["truck_id"] == lain
    assert len(store.trucks_semua()) == 2, "dua truk berbeda tidak boleh jadi satu baris"


def test_truk_lama_tanpa_pasangan_dipindah_ke_id_turunan_plat(store):
    """Truk lama yang belum pernah ada di ERP tetap harus pindah ke id turunan plat.
    Kalau dibiarkan, tarikan ERP besok yang membawa plat itu akan membuat baris kedua,
    dan kita kembali ke masalah yang sama."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _timbangan(store, "w-1", ID_LAMA, "BE 4412 OFL")

    hasil = rekonsiliasi_truk(store)

    baru = truck_id_for("BE 4412 OFL")
    assert store.truck(baru) is not None
    assert store.truck(ID_LAMA) is None
    assert store.weighing("w-1")["truck_id"] == baru
    assert hasil.dipindah == 1


def test_truk_yang_id_nya_sudah_benar_dilewati(store):
    """Sebagian besar baris di PC pabrik baru sudah benar. Menyentuhnya tanpa perlu
    cuma memperbesar peluang rusak."""
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    hasil = rekonsiliasi_truk(store)

    assert hasil.digabung == 0 and hasil.dipindah == 0
    assert hasil.dilewati == 1


# ── dijalankan orang, sering dua kali ────────────────────────────────────────


def test_dijalankan_dua_kali_hasilnya_sama(store):
    """Yang menjalankan ini sedang pasang PC dan sering ragu apakah tadi sudah
    jalan. Jalan kedua harus tidak mengubah apa pun."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _timbangan(store, "w-1", ID_LAMA, "BE 4412 OFL")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active",
                        "erp_name": "TRK-0001"})

    rekonsiliasi_truk(store)
    kedua = rekonsiliasi_truk(store)

    assert kedua.digabung == 0 and kedua.dipindah == 0
    assert store.weighing("w-1")["truck_id"] == baru
    assert store.truck(baru)["erp_name"] == "TRK-0001"


def test_mode_periksa_tidak_menulis_apa_pun(store):
    """Dijalankan dulu untuk dilihat sebelum diputuskan. Kalau mode periksa ikut
    menulis, tidak ada gunanya punya mode itu."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    _timbangan(store, "w-1", ID_LAMA, "BE 4412 OFL")

    hasil = rekonsiliasi_truk(store, tulis=False)

    assert hasil.dipindah == 1, "laporannya tetap harus menghitung apa yang AKAN terjadi"
    assert store.truck(ID_LAMA) is not None, "tidak boleh ada yang berubah"
    assert store.weighing("w-1")["truck_id"] == ID_LAMA


def test_plat_kosong_masuk_daftar_kecuali_bukan_bikin_gagal(store):
    """Satu baris rusak tidak boleh membatalkan seluruh rekonsiliasi: sisanya tetap
    perlu dibetulkan, dan yang rusak dicetak untuk diperiksa orang (spec OPS-2)."""
    store.upsert_truck({"id": ID_LAMA, "plate_number": None, "status": "active"})
    _truk_gaya_lama(store, ID_LAMA_2, "BE 4412 OFL")

    hasil = rekonsiliasi_truk(store)

    assert ID_LAMA in [k.truck_id for k in hasil.kecuali]
    assert hasil.dipindah == 1, "truk yang sehat tetap dibetulkan"
    assert store.truck(ID_LAMA) is not None, "yang rusak ditinggal apa adanya"


def test_hasilnya_bisa_dibaca_manusia(store):
    """Dibaca di terminal PC pabrik oleh orang yang mengerjakan sepuluh hal lain."""
    _truk_gaya_lama(store, ID_LAMA, "BE 4412 OFL")
    baru = truck_id_for("BE 4412 OFL")
    store.upsert_truck({"id": baru, "plate_number": "BE 4412 OFL", "status": "active"})

    laporan = rekonsiliasi_truk(store).laporan()

    assert "1" in laporan
    assert "BE 4412 OFL" in laporan
