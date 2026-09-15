from palmgrade.domain.peran import (
    PERAN_OPERATOR,
    PERAN_SUPPORT,
    parse_daftar_izin,
    peran_sah,
    saring_peran_erp,
)


def test_peran_dikenal_lolos_apa_adanya():
    assert peran_sah("support") == PERAN_SUPPORT
    assert peran_sah("operator") == PERAN_OPERATOR


def test_peran_asing_jatuh_ke_operator():
    """Sebuah nilai yang tidak dikenal tidak boleh membuka apa pun."""
    for nilai in ("admin", "", None, 7, "developer"):
        assert peran_sah(nilai) == PERAN_OPERATOR


def test_peran_dibaca_tanpa_peduli_besar_kecil_huruf():
    assert peran_sah("Support") == PERAN_SUPPORT


def test_spasi_pinggir_ditoleransi():
    """Nilai peran datang dari env dan dari kolom yang bisa diketik orang.

    Menolak karena satu spasi akan menurunkan akun support jadi operator tanpa
    jejak apa pun — gagal diam-diam, yang paling mahal di layar pabrik.
    """
    assert peran_sah("  support  ") == PERAN_SUPPORT
    assert peran_sah("SUPPORT ") == PERAN_SUPPORT


def test_daftar_izin_dibaca_dari_env():
    assert parse_daftar_izin("support") == frozenset({"support"})
    assert parse_daftar_izin("support, operator") == frozenset({"support", "operator"})
    assert parse_daftar_izin("") == frozenset()
    assert parse_daftar_izin("   ") == frozenset()


def test_peran_erp_di_luar_daftar_izin_jatuh_ke_operator():
    """Rem dari sisi pabrik: kosongkan .env dan ERP tidak bisa menaikkan siapa pun."""
    assert saring_peran_erp("support", frozenset()) == PERAN_OPERATOR
    assert saring_peran_erp("support", frozenset({"support"})) == PERAN_SUPPORT


def test_peran_erp_asing_tetap_jatuh_walau_daftar_izin_luas():
    assert saring_peran_erp("admin", frozenset({"admin"})) == PERAN_OPERATOR
