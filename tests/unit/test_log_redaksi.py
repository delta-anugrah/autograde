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
    assert "Bearer eyJhbGci" not in redaksi("Authorization: Bearer eyJhbGci")


def test_pesan_biasa_tidak_berubah():
    """Penyaring yang terlalu rakus bikin log tidak berguna."""
    pesan = "kamera line-2 putus setelah 43 detik, retry 3"
    assert redaksi(pesan) == pesan


def test_teks_kosong_aman():
    assert redaksi("") == ""
