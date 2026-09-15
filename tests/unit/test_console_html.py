"""Penjaga statis untuk `static/console.html`.

Layar operator tidak punya build step maupun test runner JS — sengaja, supaya
tetap bisa dibuka saat internet mati. Yang dijaga di sini cuma satu invarian
yang gampang sekali dibalikkan tanpa sadar: nilai dari server tidak boleh
pernah mendarat di dalam string JavaScript di atribut HTML.

`line_code` bisa berisi `machine_id` mentah dari payload event (line yang
machine_id-nya tidak cocok registry), jadi `onclick="tugaskan('${x}')"` adalah
konteks injeksi sungguhan, bukan teori — dan `esc()` versi awal memang tidak
meloloskan kutip tunggal.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def test_tanpa_handler_inline():
    # Tombol dipasang lewat delegasi + data-line, bukan atribut on*.
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", HTML), "handler inline muncul lagi"
    assert 'data-line="' in HTML


def test_escaper_menutup_kedua_kutip():
    escaper = next(baris for baris in HTML.splitlines() if "const esc =" in baris)
    for karakter in ("&", "<", ">", '"', "'", "`"):
        assert karakter in escaper, f"esc() tidak meloloskan {karakter!r}"


def _kamus(bahasa: str) -> str:
    """The body of one language block inside `const KAMUS = {...}`."""
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_setiap_kode_error_operator_diterjemahkan_di_kedua_bahasa():
    from palmgrade.domain.operator_error import CODES

    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [c for c in CODES if f"err_{c}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_pesan_error_dirangkai_di_layar_bukan_ditempel_dari_server():
    # `+ e.message` glues a server sentence onto a translated prefix.
    assert '+ e.message' not in HTML, "pakai alasan(e), bukan e.message mentah"


# ── gerbang PIN (Fase 4) ────────────────────────────────────────────────


def _fungsi(nama: str) -> str:
    """Body of one top-level function, up to the first line that closes it."""
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal)]


def test_layar_punya_gerbang_pin():
    assert 'id="gerbang"' in HTML, "gerbang PIN hilang dari layar"


def test_sesi_habis_membuka_gerbang_bukan_cuma_pesan_error():
    """Every lane answers 401 `belum_masuk` once a session is gone. Treating that like
    any other error would leave the operator staring at a red banner over a stale screen."""
    api = _fungsi("api")
    assert "belum_masuk" in api and "bukaGerbang" in api


def test_gerbang_yang_terbuka_menahan_polling_data():
    """Found by watching a real browser: with the gate up, the 2 s poll kept asking for
    `/api/console/state` and got 401 every time — all night, on a console left signed
    out. Only the gate's own lanes may go out while it is up."""
    api = _fungsi("api")
    assert 'gerbang").hidden' in api and "LANE_GERBANG" in api


def test_lane_yang_ditahan_gerbang_memakai_kode_yang_sama():
    """The gate blocks the poll locally, without asking the server, so that throw has to
    carry `belum_masuk` too — otherwise the blocked path is an unknown error again and
    raises the same false "console is down" banner the server path no longer does."""
    api = _fungsi("api")
    assert api.count("belum_masuk") >= 2


def test_belum_masuk_bukan_konsol_mati():
    """Also found in a real browser: the gate was up and a red "Konsol tidak merespons"
    banner sat above it. Not signed in is a normal state the gate already explains, and
    a false alarm about the console being down is what makes operators stop reading the
    banner that matters — the one raised when the console really has stopped answering."""
    assert "belum_masuk" in _fungsi("refresh")


def test_gerbang_yang_naik_membersihkan_banner():
    """The first fix was not enough, and only the browser said so: the banner is written
    by the poll that *discovers* the session is gone, and nothing clears it afterwards
    because clearing only happens when a lane succeeds — which none can while the gate
    is up. So raising the gate has to clear it."""
    assert 'pesan("")' in _fungsi("bukaGerbang")


def test_nama_operator_masuk_layar_lewat_esc():
    """Operator names are typed on the PC and served to an unauthenticated page."""
    assert "esc(" in _fungsi("tombolOperator")


def test_label_gerbang_diterjemahkan_di_kedua_bahasa():
    kunci = (
        "gerbangJudul", "gerbangPilih", "gerbangEmail", "gerbangSandi",
        "gerbangMasuk", "tombolKeluar",
    )
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [k for k in kunci if f"{k}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_setiap_placeholder_ikut_diterjemahkan():
    """`data-t-ph` is a second, easily-forgotten channel: `terapkanBahasa` handles
    `data-t` textContent, and a placeholder that nothing applies stays Indonesian on the
    English screen — visible only to whoever switches language and looks at a hint."""
    assert "data-t-ph" in _fungsi("terapkanBahasa")

    for atribut in re.findall(r'data-t-ph="(\w+)"', HTML):
        for bahasa in ("id", "en"):
            assert f"{atribut}:" in _kamus(bahasa), f"KAMUS.{bahasa} belum punya {atribut}"


def test_halaman_tidak_pernah_membaca_cookie():
    """The session cookie is HttpOnly. Code that reaches for `document.cookie` is someone
    trying to handle auth in the page, where any script could read it."""
    assert "document.cookie" not in HTML
