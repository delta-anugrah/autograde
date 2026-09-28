"""`ConsoleStore.akun_untuk_support` — daftar akun untuk layar Akun (support).

Query-nya menyebut kolom satu per satu, bukan `SELECT *`: jawabannya keluar dari
proses sebagai JSON, dan hash sandi tidak boleh ikut walau cuma sekali.
"""
from __future__ import annotations

from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore

SEKARANG = 1_800_000_000.0


def _store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _akun(store: ConsoleStore, email: str, nama: str) -> str:
    return store.upsert_operator_manual(
        {"email": email, "full_name": nama, "password_hash": hash_password("sandi-uji-123")}
    )


def test_tanpa_hash_sandi(tmp_path):
    store = _store(tmp_path)
    _akun(store, "ani@pks.id", "Ani")

    baris = store.akun_untuk_support(now=SEKARANG)

    assert len(baris) == 1
    assert "password_hash" not in baris[0]
    assert "scrypt$" not in repr(baris)


def test_akun_mati_ikut_tampil(tmp_path):
    """Yang dimatikan tetap terlihat: support perlu tahu akun itu ADA tapi mati,
    bukan mengira akunnya hilang lalu membuatnya lagi."""
    store = _store(tmp_path)
    oid = _akun(store, "budi@pks.id", "Budi")
    store.set_operator_status(oid, "off")

    baris = store.akun_untuk_support(now=SEKARANG)

    assert [b["status"] for b in baris] == ["off"]


def test_sesi_kedaluwarsa_tidak_dihitung(tmp_path):
    """"Sedang masuk" berarti token yang masih bisa dipakai, bukan baris yang
    belum disapu `purge_sessions`."""
    store = _store(tmp_path)
    oid = _akun(store, "ani@pks.id", "Ani")
    store.create_session("token-lama", oid, now=SEKARANG - 100, ttl_s=10)
    store.create_session("token-baru", oid, now=SEKARANG, ttl_s=3600)

    baris = store.akun_untuk_support(now=SEKARANG)

    assert baris[0]["sesi_aktif"] == 1


def test_akun_aktif_di_atas_lalu_urut_nama(tmp_path):
    store = _store(tmp_path)
    _akun(store, "zul@pks.id", "zul")
    mati = _akun(store, "ani@pks.id", "Ani")
    _akun(store, "budi@pks.id", "Budi")
    store.set_operator_status(mati, "off")

    baris = store.akun_untuk_support(now=SEKARANG)

    assert [b["email"] for b in baris] == ["budi@pks.id", "zul@pks.id", "ani@pks.id"]


def test_membawa_hitungan_salah_sandi_untuk_status_terkunci(tmp_path):
    store = _store(tmp_path)
    oid = _akun(store, "ani@pks.id", "Ani")
    for _ in range(5):
        store.record_login_failure(oid, now=SEKARANG - 10)

    baris = store.akun_untuk_support(now=SEKARANG)[0]

    assert baris["fail_count"] == 5
    assert baris["last_failed_at"] == SEKARANG - 10
