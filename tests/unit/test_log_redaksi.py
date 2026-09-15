import time

import pytest

from palmgrade.domain.log_redaksi import redaksi


def test_sandi_ditutup():
    assert "rahasia123" not in redaksi("login gagal: password=rahasia123")


def test_token_ditutup_dalam_json():
    keluar = redaksi('{"token": "abc.def.ghi", "line": "line-1"}')
    assert "abc.def.ghi" not in keluar
    assert "line-1" in keluar, "yang bukan rahasia harus tetap kebaca"


def test_hash_sandi_ditutup():
    assert "$pbkdf2-sha256$29000$xyz" not in redaksi(
        "hash mismatch for password_hash=$pbkdf2-sha256$29000$xyz"
    )


def test_header_authorization_ditutup():
    # Must check the token substring alone, not "Bearer eyJhbGci" together —
    # that compound check used to pass even when only "Bearer" got redacted
    # and the token itself leaked in full.
    assert "eyJhbGci" not in redaksi("Authorization: Bearer eyJhbGci")


def test_pesan_biasa_tidak_berubah():
    """Penyaring yang terlalu rakus bikin log tidak berguna."""
    pesan = "kamera line-2 putus setelah 43 detik, retry 3"
    assert redaksi(pesan) == pesan


def test_teks_kosong_aman():
    assert redaksi("") == ""


def test_passwordless_tidak_terpicu():
    """Kunci "password" tidak boleh cocok sebagai prefix kata lain."""
    pesan = "passwordless mode aktif untuk line-1"
    assert redaksi(pesan) == pesan


@pytest.mark.parametrize(
    ("teks", "rahasia"),
    [
        ("token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc-_XYZ", "eyJhbGciOiJIUzI1NiJ9"),
        ("password_hash=$pbkdf2-sha256$29000$salt$digest", "digest"),
        ("password_hash=scrypt$32768$8$1$c2FsdA$aGFzaA", "aGFzaA"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.QQ", "eyJhbGciOiJIUzI1NiJ9"),
        ('{"sandi":"p@ss w0rd","line":"line-1"}', "p@ss w0rd"),
        ("GET /x?api_key=abc123&line=2", "abc123"),
        ("PASSWORD=RahasiaBanget", "RahasiaBanget"),
        ("token  =  abc.def", "abc.def"),
        ("secret='sh h h'", "sh h h"),
    ],
)
def test_rahasia_tidak_bocor(teks: str, rahasia: str):
    assert rahasia not in redaksi(teks)


def test_json_dengan_spasi_tetap_menyisakan_field_lain():
    """Nilai berspasi tertutup penuh, tapi field tetangga tetap kebaca."""
    keluar = redaksi('{"sandi":"p@ss w0rd","line":"line-1"}')
    assert "line-1" in keluar


def test_nilai_berkutip_dengan_baris_baru_ditutup():
    """Traceback multi-baris adalah bentuk asli yang mau ditangkap penyaring ini."""
    keluar = redaksi('secret="line1\nline2"')
    assert "line1" not in keluar
    assert "line2" not in keluar


def test_kutip_ter_escape_tidak_mengakhiri_nilai():
    """`\\"` di dalam nilai tidak boleh dibaca sebagai penutup — ekor sesudahnya jangan bocor."""
    keluar = redaksi('password="p\\"ss"')
    assert 'ss"' not in keluar


def test_konsol_sesi_ditutup():
    """`konsol_sesi` = nama cookie sesi konsol (routes/console.py) — token hidup."""
    assert "abc123def" not in redaksi("Set-Cookie: konsol_sesi=abc123def; HttpOnly")


def test_kunci_tengah_kata_tidak_terpicu():
    """`not-a-secret` bukan kunci rahasia — jangan ditutup, dan tetangganya tetap kebaca."""
    pesan = "not-a-secret=fine"
    assert redaksi(pesan) == pesan
    assert "fine" in redaksi(pesan)


def test_dua_kunci_di_satu_baris_dua_duanya_ditutup():
    keluar = redaksi("token=a secret=b")
    assert keluar == "token=«ditutup» secret=«ditutup»"


def test_query_string_hanya_menutup_nilai_bukan_sisa_baris():
    """`&` bukan bagian nilai yang sah — parameter tetangga (line, truck) tidak boleh ikut hilang."""
    keluar = redaksi("GET /x?api_key=abc123&line=2&truck=B1234XY")
    assert "abc123" not in keluar
    assert "line=2" in keluar
    assert "truck=B1234XY" in keluar


def test_query_string_password_menyisakan_redirect():
    keluar = redaksi("POST /login?password=p123&redirect=/console")
    assert "p123" not in keluar
    assert "redirect=/console" in keluar


def test_query_string_dua_rahasia_dua_duanya_ditutup_line_selamat():
    """Dua kunci rahasia di satu query string — keduanya harus tertutup, bukan cuma yang pertama."""
    keluar = redaksi("/api?token=t1&api_key=k2&line=3")
    assert "t1" not in keluar
    assert "k2" not in keluar
    assert "line=3" in keluar


@pytest.mark.parametrize(
    "teks",
    [
        "password=p#ss123",
        "token=ab&cd1234",
        "api_key=a#b&c",
    ],
)
def test_nilai_polos_dengan_ampersand_pagar_tidak_bocor_ekor(teks: str):
    """`&`/`#` di tengah nilai (bukan sebelum param baru) tidak boleh mengakhiri redaksi.

    Kebalikan dari kutip ter-escape: ekornya bocor SESUDAH marker, bukan sebelum.
    """
    keluar = redaksi(teks)
    assert "«ditutup»" in keluar
    ekor = keluar.split("«ditutup»", 1)[1]
    assert ekor == "", f"ekor bocor sesudah marker: {ekor!r}"


def test_kutip_tak_ditutup_tidak_hang():
    """Nilai berkutip yang tidak pernah ditutup, dibanjiri backslash, tidak boleh macet."""
    mulai = time.monotonic()
    redaksi('password="' + "\\" * 60)
    lama = time.monotonic() - mulai
    assert lama < 1.0, f"terlalu lama: {lama:.3f}s — kemungkinan backtracking katastrofik"
