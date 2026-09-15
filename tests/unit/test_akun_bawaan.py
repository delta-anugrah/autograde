"""The two accounts baked into every AutoGrade image (Fase 4, plan §6.5).

A mill PC can be installed before it has ever reached the internet, and AutoERP's
accounts arrive only with the first pull. Without something already on the disk there
would be nothing to sign in with, and the console would be a locked screen on the day it
is most needed.

So each image carries two local accounts:

- `operator@autograde.local` — the mill's own account, handed to the shift
- `support@autograde.local` — ours, for a developer coming in over AnyDesk

**Only the hash is baked, never the password.** The build takes
`CONSOLE_DEFAULT_HASH` / `CONSOLE_SUPPORT_HASH`, so a raw password never enters the
image, its layers, or its build log — a factory PC is reachable over AnyDesk, and an
image layer is readable by anyone who has one.

Per the operator's decision (2026-09-15) the passwords are **different per mill**,
generated at install time. The emails are fixed across images so support does not have
to ask which address a given mill used.

The rule that matters most here is the last one: seeding must never overwrite an account
that already exists. A container restarts for all sorts of reasons, and a restart that
silently restored the factory password would undo every password the mill had changed —
quietly, and exactly on the accounts that are the same on every image.
"""

from __future__ import annotations

from palmgrade.domain.operator_auth import hash_password, operator_id_for, verify_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.akun_bawaan import (
    EMAIL_BAWAAN,
    EMAIL_SUPPORT,
    seed_akun_bawaan,
)

SANDI_BAWAAN = "pabrik2026"
SANDI_SUPPORT = "support2026"


def _store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _seed(store, *, bawaan=SANDI_BAWAAN, support=SANDI_SUPPORT):
    return seed_akun_bawaan(
        store,
        hash_bawaan=hash_password(bawaan) if bawaan else "",
        hash_support=hash_password(support) if support else "",
    )


def test_kedua_akun_dibuat_dan_bisa_dipakai_masuk(tmp_path):
    store = _store(tmp_path)

    dibuat = _seed(store)

    assert sorted(dibuat) == [EMAIL_BAWAAN, EMAIL_SUPPORT]
    for email, sandi in ((EMAIL_BAWAAN, SANDI_BAWAAN), (EMAIL_SUPPORT, SANDI_SUPPORT)):
        row = store.operator_by_email(email)
        assert row["status"] == "active"
        assert row["asal"] == "lokal", "akun bawaan milik PC ini, bukan milik AutoERP"
        assert verify_password(sandi, row["password_hash"])


def test_emailnya_sama_di_semua_image(tmp_path):
    """Support tidak boleh perlu nanya dulu 'email lu apa?' tiap mau masuk ke satu PKS."""
    assert EMAIL_BAWAAN == "operator@autograde.local"
    assert EMAIL_SUPPORT == "support@autograde.local"


def test_seed_kedua_kali_tidak_menimpa_apa_pun(tmp_path):
    """Container restart itu hal biasa. Kalau seed menimpa, sandi yang sudah diganti
    pabrik balik ke sandi pabrikan — diam-diam, dan justru di akun yang sandinya sama
    di semua image."""
    store = _store(tmp_path)
    _seed(store)
    store.upsert_operator_lokal(
        {
            "email": EMAIL_BAWAAN,
            "nama": "Pak Budi",
            "password_hash": hash_password("sudahdiganti2026"),
        }
    )

    dibuat = _seed(store)

    assert dibuat == []
    row = store.operator_by_email(EMAIL_BAWAAN)
    assert verify_password("sudahdiganti2026", row["password_hash"])
    assert not verify_password(SANDI_BAWAAN, row["password_hash"])


def test_akun_yang_dimatikan_tidak_dihidupkan_lagi_oleh_restart(tmp_path):
    """Akun bawaan dimatikan itu keputusan sadar — biasanya karena pabrik sudah punya
    akun sendiri dari AutoERP. Restart tidak boleh membatalkannya."""
    store = _store(tmp_path)
    _seed(store)
    store.set_operator_status(operator_id_for(EMAIL_BAWAAN), "off")

    _seed(store)

    assert store.operator_by_email(EMAIL_BAWAAN)["status"] == "off"


def test_hash_kosong_berarti_akun_itu_tidak_dibuat(tmp_path):
    """Build tanpa hash (atau `.env` yang lupa diisi) tidak boleh menghasilkan akun
    tanpa sandi yang bisa dimasuki siapa saja."""
    store = _store(tmp_path)

    dibuat = seed_akun_bawaan(store, hash_bawaan="", hash_support="")

    assert dibuat == []
    assert store.operators() == []


def test_hash_yang_tidak_bisa_dibaca_ditolak_bukan_disimpan(tmp_path):
    """Compose memakan `$` (`$$` kalau mau satu `$`), jadi hash yang terpotong itu
    kejadian nyata, bukan teori. Akun dengan hash rusak = akun yang tidak bisa dimasuki
    siapa pun tapi kelihatan ada di layar; lebih baik tidak dibuat."""
    store = _store(tmp_path)

    dibuat = seed_akun_bawaan(
        store, hash_bawaan="pbkdf2-sha256$29000$terpotong", hash_support="sandi-mentah"
    )

    assert dibuat == []
    assert store.operators() == []


def test_sandi_mentah_tidak_pernah_diterima_sebagai_hash(tmp_path):
    """Kalau ini lolos, sandi mentah ikut tertanam di image — hal yang justru
    dihindari seluruh rancangan ini."""
    store = _store(tmp_path)

    seed_akun_bawaan(store, hash_bawaan=SANDI_BAWAAN, hash_support=SANDI_SUPPORT)

    assert store.operators() == []


def test_akun_support_tetap_dibuat_walau_akun_bawaan_tidak(tmp_path):
    """Dua akun itu berdiri sendiri: satu hash yang lupa diisi tidak boleh ikut
    mematikan jalur masuk yang satunya."""
    store = _store(tmp_path)

    dibuat = seed_akun_bawaan(store, hash_bawaan="", hash_support=hash_password(SANDI_SUPPORT))

    assert dibuat == [EMAIL_SUPPORT]
    assert store.operator_by_email(EMAIL_BAWAAN) is None
    assert verify_password(SANDI_SUPPORT, store.operator_by_email(EMAIL_SUPPORT)["password_hash"])


def test_akun_milik_autoerp_dengan_email_sama_tidak_disentuh(tmp_path):
    """Kalau backoffice sampai bikin akun AutoERP dengan email yang sama, yang menang
    AutoERP — seperti aturan dua sumber pada umumnya (invarian 19)."""
    store = _store(tmp_path)
    erp_hash = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"
    store.upsert_operator_erp(
        {
            "email": EMAIL_SUPPORT,
            "nama": "Support ERP",
            "password_hash": erp_hash,
            "erp_name": EMAIL_SUPPORT,
            "active": 1,
        }
    )

    _seed(store)

    row = store.operator_by_email(EMAIL_SUPPORT)
    assert (row["asal"], row["password_hash"]) == ("erp", erp_hash)
