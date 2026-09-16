import time

import pytest

from palmgrade.domain.log_redaksi import redact


def test_password_is_masked():
    assert "rahasia123" not in redact("login gagal: password=rahasia123")


def test_token_masked_inside_json():
    result = redact('{"token": "abc.def.ghi", "line": "line-1"}')
    assert "abc.def.ghi" not in result
    assert "line-1" in result, "a non-secret must stay readable"


def test_password_hash_is_masked():
    assert "$pbkdf2-sha256$29000$xyz" not in redact(
        "hash mismatch for password_hash=$pbkdf2-sha256$29000$xyz"
    )


def test_authorization_header_is_masked():
    # Must check the token substring alone, not "Bearer eyJhbGci" together —
    # that compound check used to pass even when only "Bearer" got redacted
    # and the token itself leaked in full.
    assert "eyJhbGci" not in redact("Authorization: Bearer eyJhbGci")


def test_ordinary_message_is_unchanged():
    """A filter that is too eager makes the log useless."""
    message = "kamera line-2 putus setelah 43 detik, retry 3"
    assert redact(message) == message


def test_empty_text_is_safe():
    assert redact("") == ""


def test_passwordless_does_not_trigger():
    """The "password" key must not match as a prefix of another word."""
    message = "passwordless mode aktif untuk line-1"
    assert redact(message) == message


@pytest.mark.parametrize(
    ("text", "secret"),
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
def test_secret_does_not_leak(text: str, secret: str):
    assert secret not in redact(text)


def test_json_with_spaces_still_leaves_other_fields_readable():
    result = redact('{"sandi":"p@ss w0rd","line":"line-1"}')
    assert "line-1" in result


def test_quoted_value_with_a_newline_is_masked():
    """A multi-line traceback is exactly the shape this filter has to catch."""
    result = redact('secret="line1\nline2"')
    assert "line1" not in result
    assert "line2" not in result


def test_escaped_quote_does_not_end_the_value():
    """`\\"` inside a value must not read as its closing quote — the tail after it must not leak."""
    result = redact('password="p\\"ss"')
    assert 'ss"' not in result


def test_konsol_sesi_is_masked():
    """`konsol_sesi` = the console session cookie name (routes/console.py) — a live token."""
    assert "abc123def" not in redact("Set-Cookie: konsol_sesi=abc123def; HttpOnly")


def test_key_mid_word_does_not_trigger():
    """`not-a-secret` is not a secret key — leave it and its neighbour alone."""
    message = "not-a-secret=fine"
    assert redact(message) == message
    assert "fine" in redact(message)


def test_two_keys_on_one_line_are_both_masked():
    result = redact("token=a secret=b")
    assert result == "token=«redacted» secret=«redacted»"


def test_query_string_masks_only_the_value_not_the_rest_of_the_line():
    """`&` is not part of a valid value — neighbouring params (line, truck) must survive."""
    result = redact("GET /x?api_key=abc123&line=2&truck=B1234XY")
    assert "abc123" not in result
    assert "line=2" in result
    assert "truck=B1234XY" in result


def test_query_string_password_leaves_the_redirect_readable():
    result = redact("POST /login?password=p123&redirect=/console")
    assert "p123" not in result
    assert "redirect=/console" in result


def test_query_string_two_secrets_both_masked_line_survives():
    """Two secret keys in one query string — both must be masked, not just the first."""
    result = redact("/api?token=t1&api_key=k2&line=3")
    assert "t1" not in result
    assert "k2" not in result
    assert "line=3" in result


@pytest.mark.parametrize(
    "text",
    [
        "password=p#ss123",
        "token=ab&cd1234",
        "api_key=a#b&c",
    ],
)
def test_plain_value_with_ampersand_or_hash_does_not_leak_a_tail(text: str):
    """`&`/`#` mid-value (not before a new param) must not end the mask early.

    The mirror case of an escaped quote: here the tail leaks AFTER the marker, not before.
    """
    result = redact(text)
    assert "«redacted»" in result
    tail = result.split("«redacted»", 1)[1]
    assert tail == "", f"tail leaked after the marker: {tail!r}"


def test_unclosed_quoted_value_does_not_hang():
    """A quoted value that never closes, flooded with backslashes, must not hang."""
    start = time.monotonic()
    redact('password="' + "\\" * 60)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"too slow: {elapsed:.3f}s — likely catastrophic backtracking"
