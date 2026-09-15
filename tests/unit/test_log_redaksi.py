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
