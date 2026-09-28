"""Mengurus akun lokal dari tab Akun (support), bukan cuma dari terminal PC.

Dibuka 2026-09-26 atas permintaan user: support perlu membuat akun operator
baru tanpa AnyDesk + terminal. Aturannya sama dengan `make operator`, ditambah
yang cuma masuk akal di layar bersama:

- **Tambah** menolak email yang sudah ada. Di terminal, email lama berarti
  ganti sandi; di layar, form "akun baru" yang diam-diam mengganti sandi orang
  lain adalah kejutan yang buruk.
- **Akun AutoERP tidak disentuh sama sekali.** Tarikan berikutnya akan
  membatalkan perubahan apa pun, dan orang yang diberi tahu "berhasil" baru
  tahu belakangan.
- **Akun sendiri tidak bisa dimatikan atau diturunkan role-nya**: satu klik
  salah dan tidak ada support yang tersisa untuk membetulkannya.
- Setiap perubahan tercatat WARNING dengan email pelakunya, jadi muncul di tab
  Log.
"""

from __future__ import annotations

import logging

import pytest

from palmgrade.domain.operator_auth import new_session_token, operator_id_for, verify_password
from palmgrade.domain.operator_error import (
    AKUN_DIRI_SENDIRI,
    AKUN_EMAIL_TIDAK_SAH,
    AKUN_MILIK_ERP,
    AKUN_NAMA_KOSONG,
    AKUN_SANDI_BEDA,
    AKUN_SUDAH_ADA,
    AKUN_TIDAK_ADA,
    SANDI_PENDEK,
    OperatorError,
)
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.operator_admin import OperatorAdmin

SUPPORT = "support@pks.test"
SANDI = "sawit2026"
ERP_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


def _admin(tmp_path) -> tuple[OperatorAdmin, ConsoleStore]:
    store = ConsoleStore(tmp_path / "console.db")
    return OperatorAdmin(store), store


def _kode(exc_info) -> str:
    return exc_info.value.code


def _akun_erp(store: ConsoleStore, email: str = "erp@pks.test") -> str:
    return store.upsert_operator_erp(
        {"email": email, "full_name": "Orang ERP", "password_hash": ERP_HASH, "active": 1}
    )


# ── tambah ────────────────────────────────────────────────────────────────


def test_tambah_membuat_akun_lokal_yang_bisa_dipakai_masuk(tmp_path):
    admin, store = _admin(tmp_path)

    hasil = admin.tambah("Budi@PKS.test ", " Pak  Budi ", SANDI, SANDI, "operator", oleh=SUPPORT)

    row = store.operator(operator_id_for("budi@pks.test"))
    assert hasil == {"email": "budi@pks.test", "role": "operator"}
    assert (row["origin"], row["status"], row["role"], row["full_name"]) == (
        "lokal", "active", "operator", "Pak Budi",
    )
    assert verify_password(SANDI, row["password_hash"])


def test_tambah_bisa_langsung_membuat_akun_support(tmp_path):
    admin, store = _admin(tmp_path)

    admin.tambah("ani@pks.test", "Ani", SANDI, SANDI, "support", oleh=SUPPORT)

    assert store.operator(operator_id_for("ani@pks.test"))["role"] == "support"


def test_role_asing_dari_layar_jatuh_ke_operator(tmp_path):
    """Role menentukan siapa yang bisa membuka Danger Zone. Nilai yang tidak
    dikenal tidak boleh dipercaya begitu saja, dan tidak boleh mengunci akun."""
    admin, store = _admin(tmp_path)

    hasil = admin.tambah("ani@pks.test", "Ani", SANDI, SANDI, "admin", oleh=SUPPORT)

    assert hasil["role"] == "operator"
    assert store.operator(operator_id_for("ani@pks.test"))["role"] == "operator"


def test_tambah_menolak_email_yang_sudah_ada_dan_tidak_mengganti_sandinya(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)

    with pytest.raises(OperatorError) as err:
        admin.tambah("budi@pks.test", "Budi Lain", "sandi-baru-99", "sandi-baru-99", "support",
                     oleh=SUPPORT)

    assert _kode(err) == AKUN_SUDAH_ADA
    row = store.operator(operator_id_for("budi@pks.test"))
    assert verify_password(SANDI, row["password_hash"])
    assert (row["full_name"], row["role"]) == ("Budi", "operator")


def test_tambah_menolak_email_milik_autoerp(tmp_path):
    admin, store = _admin(tmp_path)
    _akun_erp(store)

    with pytest.raises(OperatorError) as err:
        admin.tambah("erp@pks.test", "Tiruan", SANDI, SANDI, "operator", oleh=SUPPORT)

    assert _kode(err) == AKUN_MILIK_ERP
    assert store.operator(operator_id_for("erp@pks.test"))["password_hash"] == ERP_HASH


@pytest.mark.parametrize(
    ("email", "nama", "sandi", "ulang", "kode"),
    [
        ("bukan-email", "Budi", SANDI, SANDI, AKUN_EMAIL_TIDAK_SAH),
        ("dua kata@pks.test", "Budi", SANDI, SANDI, AKUN_EMAIL_TIDAK_SAH),
        ("a@b@pks.test", "Budi", SANDI, SANDI, AKUN_EMAIL_TIDAK_SAH),
        ("", "Budi", SANDI, SANDI, AKUN_EMAIL_TIDAK_SAH),
        ("budi@pks.test", "   ", SANDI, SANDI, AKUN_NAMA_KOSONG),
        ("budi@pks.test", "Budi", SANDI, "sawit2027", AKUN_SANDI_BEDA),
        ("budi@pks.test", "Budi", "pendek", "pendek", SANDI_PENDEK),
    ],
)
def test_tambah_memeriksa_isian_sebelum_menyimpan(tmp_path, email, nama, sandi, ulang, kode):
    admin, store = _admin(tmp_path)

    with pytest.raises(OperatorError) as err:
        admin.tambah(email, nama, sandi, ulang, "operator", oleh=SUPPORT)

    assert _kode(err) == kode
    assert store.akun_untuk_support(now=0) == []


def test_kesalahan_isian_tetap_valueerror_supaya_terminal_tidak_berubah(tmp_path):
    """`scripts/console-operator.py` menangkap ValueError. Kode baru untuk layar
    tidak boleh membuat terminal mencetak traceback."""
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak sama"):
        admin.add_or_reset("budi@pks.test", "Budi", SANDI, "sawit2027")


def test_tambah_tercatat_di_log_dengan_pelakunya_tanpa_sandi(tmp_path, caplog):
    admin, _ = _admin(tmp_path)

    with caplog.at_level(logging.WARNING, logger="palmgrade.services.operator_admin"):
        admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "support", oleh=SUPPORT)

    pesan = " ".join(r.getMessage() for r in caplog.records)
    assert "budi@pks.test" in pesan
    assert SUPPORT in pesan
    assert "support" in pesan
    assert SANDI not in pesan


# ── ganti sandi ───────────────────────────────────────────────────────────


def test_ganti_sandi_akun_lokal_mengakhiri_sesinya_dan_mengosongkan_kuncian(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "support", oleh=SUPPORT)
    oid = operator_id_for("budi@pks.test")
    store.create_session(new_session_token(), oid, now=1000.0, ttl_s=3600)
    for _ in range(5):
        store.record_login_failure(oid, now=1000.0)

    admin.ganti_sandi("budi@pks.test", "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)

    row = store.operator(oid)
    assert verify_password("sandi-baru-99", row["password_hash"])
    assert not verify_password(SANDI, row["password_hash"])
    assert (row["full_name"], row["role"], row["fail_count"]) == ("Budi", "support", 0)
    assert store.akun_untuk_support(now=1001.0)[0]["sesi_aktif"] == 0


def test_ganti_sandi_tidak_menghidupkan_akun_yang_sengaja_dimatikan(tmp_path):
    """Di terminal, reset sandi ikut menghidupkan akun. Di layar itu dua tombol
    yang berbeda, jadi ganti sandi tidak boleh diam-diam membuka pintu."""
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)
    admin.atur_status("budi@pks.test", False, oleh=SUPPORT)

    admin.ganti_sandi("budi@pks.test", "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)

    assert store.operator(operator_id_for("budi@pks.test"))["status"] == "off"


def test_ganti_sandi_akun_sendiri_boleh(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah(SUPPORT, "Support", SANDI, SANDI, "support", oleh=SUPPORT)

    admin.ganti_sandi(SUPPORT, "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)

    assert verify_password("sandi-baru-99", store.operator(operator_id_for(SUPPORT))["password_hash"])


def test_ganti_sandi_menolak_akun_autoerp_dan_akun_yang_tidak_ada(tmp_path):
    admin, store = _admin(tmp_path)
    _akun_erp(store)

    with pytest.raises(OperatorError) as erp:
        admin.ganti_sandi("erp@pks.test", "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)
    with pytest.raises(OperatorError) as hilang:
        admin.ganti_sandi("siapa@pks.test", "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)

    assert (_kode(erp), _kode(hilang)) == (AKUN_MILIK_ERP, AKUN_TIDAK_ADA)
    assert store.operator(operator_id_for("erp@pks.test"))["password_hash"] == ERP_HASH


def test_ganti_sandi_memeriksa_sandi_dua_kali_dan_panjangnya(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)

    with pytest.raises(OperatorError) as beda:
        admin.ganti_sandi("budi@pks.test", "sandi-baru-99", "sandi-baru-98", oleh=SUPPORT)
    with pytest.raises(OperatorError) as pendek:
        admin.ganti_sandi("budi@pks.test", "pendek", "pendek", oleh=SUPPORT)

    assert (_kode(beda), _kode(pendek)) == (AKUN_SANDI_BEDA, SANDI_PENDEK)
    assert verify_password(SANDI, store.operator(operator_id_for("budi@pks.test"))["password_hash"])


# ── matikan / aktifkan ────────────────────────────────────────────────────


def test_matikan_akun_lokal_mengakhiri_sesinya_lalu_bisa_diaktifkan_lagi(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)
    oid = operator_id_for("budi@pks.test")
    token = new_session_token()
    store.create_session(token, oid, now=1000.0, ttl_s=3600)

    admin.atur_status("budi@pks.test", False, oleh=SUPPORT)

    assert store.operator(oid)["status"] == "off"
    assert store.session(token, now=1001.0) is None

    admin.atur_status("budi@pks.test", True, oleh=SUPPORT)

    assert store.operator(oid)["status"] == "active"
    # Token lama tetap mati: sesinya sudah dihapus, bukan cuma disaring.
    assert store.session(token, now=1002.0) is None


def test_tidak_bisa_mematikan_akun_sendiri(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah(SUPPORT, "Support", SANDI, SANDI, "support", oleh=SUPPORT)

    with pytest.raises(OperatorError) as err:
        admin.atur_status(" Support@PKS.test", False, oleh=SUPPORT)

    assert _kode(err) == AKUN_DIRI_SENDIRI
    assert store.operator(operator_id_for(SUPPORT))["status"] == "active"


def test_matikan_menolak_akun_autoerp_dan_akun_yang_tidak_ada(tmp_path):
    admin, store = _admin(tmp_path)
    _akun_erp(store)

    with pytest.raises(OperatorError) as erp:
        admin.atur_status("erp@pks.test", False, oleh=SUPPORT)
    with pytest.raises(OperatorError) as hilang:
        admin.atur_status("siapa@pks.test", False, oleh=SUPPORT)

    assert (_kode(erp), _kode(hilang)) == (AKUN_MILIK_ERP, AKUN_TIDAK_ADA)
    assert store.operator(operator_id_for("erp@pks.test"))["status"] == "active"


# ── ubah role ─────────────────────────────────────────────────────────────


def test_ubah_role_akun_lokal(tmp_path):
    admin, store = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)

    hasil = admin.atur_role("budi@pks.test", "support", oleh=SUPPORT)

    assert hasil == "support"
    assert store.operator(operator_id_for("budi@pks.test"))["role"] == "support"


def test_tidak_bisa_mengubah_role_sendiri(tmp_path):
    """Support yang menurunkan dirinya sendiri jadi operator kehilangan layar
    ini di klik berikutnya, dan bisa jadi tidak ada support lain di PC itu."""
    admin, store = _admin(tmp_path)
    admin.tambah(SUPPORT, "Support", SANDI, SANDI, "support", oleh=SUPPORT)

    with pytest.raises(OperatorError) as err:
        admin.atur_role(SUPPORT, "operator", oleh=SUPPORT)

    assert _kode(err) == AKUN_DIRI_SENDIRI
    assert store.operator(operator_id_for(SUPPORT))["role"] == "support"


def test_ubah_role_menolak_akun_autoerp(tmp_path):
    """Role akun AutoERP datang dari AutoERP lewat `ERP_ALLOWED_ROLES`. Mengubahnya
    di sini akan dibatalkan tarikan berikutnya."""
    admin, store = _admin(tmp_path)
    _akun_erp(store)

    with pytest.raises(OperatorError) as err:
        admin.atur_role("erp@pks.test", "support", oleh=SUPPORT)

    assert _kode(err) == AKUN_MILIK_ERP
    assert store.operator(operator_id_for("erp@pks.test"))["role"] == "operator"


def test_status_dan_role_tercatat_di_log(tmp_path, caplog):
    admin, _ = _admin(tmp_path)
    admin.tambah("budi@pks.test", "Budi", SANDI, SANDI, "operator", oleh=SUPPORT)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="palmgrade.services.operator_admin"):
        admin.atur_status("budi@pks.test", False, oleh=SUPPORT)
        admin.atur_role("budi@pks.test", "support", oleh=SUPPORT)
        admin.ganti_sandi("budi@pks.test", "sandi-baru-99", "sandi-baru-99", oleh=SUPPORT)

    pesan = [r.getMessage() for r in caplog.records]
    assert len(pesan) == 3
    assert all("budi@pks.test" in p and SUPPORT in p for p in pesan)
    assert not any("sandi-baru-99" in p for p in pesan)
