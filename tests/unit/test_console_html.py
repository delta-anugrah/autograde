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


def test_reject_manual_tidak_mengirim_nama_dari_halaman():
    """Sejak Fase 4 server memakai pemegang sesi. Halaman yang tetap mengirim
    `requested_by` bikin satu-satunya aksi operator yang bernama itu terbaca seolah
    namanya masih datang dari layar — padahal diabaikan."""
    # Yang dicek kodenya, bukan komentarnya: komentar di atas baris itu memang
    # menyebut `requested_by` untuk menerangkan kenapa dia tidak dikirim lagi.
    assert "requested_by:" not in HTML
    assert 'JSON.stringify({ requested_by' not in HTML


def test_halaman_tidak_pernah_membaca_cookie():
    """The session cookie is HttpOnly. Code that reaches for `document.cookie` is someone
    trying to handle auth in the page, where any script could read it."""
    assert "document.cookie" not in HTML


# ── piston manual ───────────────────────────────────────────────────────


def _blok_klik_piston() -> str:
    """The body of the `data-aksi === "piston"` branch in the delegated click
    handler — from its own `else if` guard up to (not including) the next
    branch's guard.

    Slicing on the guard STRING (not a fixed character count) means the slice
    boundary moves with the code: it starts exactly where the piston branch's
    condition is written and ends exactly where the next `} else {` (the
    manual-reject fallback, the last branch in the chain) begins. Bunches of
    unrelated code before (`tugaskan`, `lepas`) can never leak in because the
    split point is *after* them; the reject fallback after the piston branch
    can never leak in because the split point on `} else {` is *before* it.
    """
    setelah_guard = HTML.split('tombol.dataset.aksi === "piston"', 1)[1]
    return setelah_guard.split('} else {', 1)[0]


def test_membuka_lewat_dialog_menutup_langsung():
    # Opening moves metal: it must ask first. Closing returns to the safe
    # state: it must never be blocked by anything, confirm() included.
    blok = _blok_klik_piston()

    # (a) Opening requires confirmation. There must be exactly one confirm()
    # in the branch, and it must be reached only when `buka` (open) is true -
    # a version that wrapped the WHOLE branch (open and close alike) behind
    # one `if (buka ...) confirm(...)` would still contain both the strings
    # "confirm(" and "buka", so the guard's shape is checked, not just its
    # presence.
    assert blok.count('confirm(') == 1, "harus ada tepat satu confirm() di cabang piston"
    sebelum_confirm = blok.split('confirm(', 1)[0]
    assert re.search(r'if\s*\(\s*buka\s*&&', sebelum_confirm), (
        "confirm() harus dijaga oleh `if (buka && ...)` - kalau tidak, "
        "menutup piston (buka=false) ikut kena dialog juga"
    )

    # (b) Closing is instant: past that one guard line, the call that reaches
    # the server is not wrapped in any further `if (buka` condition. Cutting
    # the branch right after the guard's early-return (`return;`) isolates
    # exactly the code both open (once confirmed) and close fall through to -
    # a second `if (buka ...)` gating the API call there would mean closing
    # silently does nothing, which "confirm(" being merely absent would not
    # catch.
    setelah_guard = blok.split('confirm(', 1)[1]
    setelah_return = setelah_guard.split('return;', 1)[1]
    assert 'api(' in setelah_return, "cabang piston tidak pernah memanggil endpoint"
    jalur_bersama = setelah_return.split('api(', 1)[0]
    assert 'if (buka' not in jalur_bersama, (
        "panggilan API tidak boleh digerbangi `if (buka` lagi setelah dialog - "
        "kalau begitu menutup piston tidak melakukan apa-apa"
    )


def _blok_pintasan_p() -> str:
    """The full `P` shortcut block, from its own `pTahan` state declaration to
    the end of its `keydown` listener.

    `pTahan` (not `spasi`) is the state flag this block declares for itself,
    so `let pTahan = false;` only ever appears once, at the TOP of this block -
    slicing from there cannot start inside the `Spasi` block above it, whose
    own state flag is a different identifier (`spasi`) declared earlier in the
    file. The end boundary is the block's own listener closing with `});`
    immediately followed by the next top-level statement in the brief
    (`$("daftar")...`), so the slice cannot run on into unrelated code either.
    """
    dari_awal = HTML.split('let pTahan = false;', 1)[1]
    return dari_awal.split('$("daftar")', 1)[0]


def test_pintasan_piston_memakai_kode_tombol_bukan_huruf():
    # Layout keyboard beda-beda; ev.key bisa bukan "p".
    assert 'ev.code === "KeyP"' in HTML


def test_pintasan_piston_tidak_aktif_saat_mengetik():
    # A slice ending right before the FIRST `ev.code === "KeyP"` can
    # accidentally read backwards into the END of the `Spasi` block above it
    # (which has its own, identical-looking typing guard) and pass even if the
    # `P` block itself has none. Anchoring on the block's own `pTahan` start
    # instead means the guard checked here can only be the one written inside
    # this block - there is nothing from `Spasi` left in the slice to match
    # against.
    blok = _blok_pintasan_p()
    assert 'closest("input, textarea, .pilih")' in blok
# ── panel dropdown tidak boleh terpotong tepi layar ────────────────────────────


def test_panel_dropdown_menempel_ke_tepi_yang_benar():
    """Panel `.pilih` yang menempel di sisi kanan strip tally tumbuh ke kanan dan
    keluar layar: `left:0` mengukur dari tepi kiri tombol, dan tombolnya sendiri sudah
    mepet kanan. Dibuktikan di browser 1366x768: kanan panel 1369 px di layar 1366.

    Perbaikannya tidak bisa `right:0` polos untuk semua `.pilih` (yang di sisi kiri
    justru jadi salah arah), jadi yang dipakai penanda posisi eksplisit.
    """
    assert ".pilih-panel--kanan" in HTML, "belum ada varian panel yang menempel kanan"
    aturan = next(
        baris for baris in HTML.splitlines() if ".pilih-panel--kanan" in baris and "right" in baris
    )
    assert "right:0" in aturan.replace(" ", "")
    assert "left:auto" in aturan.replace(" ", ""), "left:0 bawaan harus dibatalkan"


def test_dropdown_tata_letak_memakai_varian_kanan():
    """Ini satu-satunya `.pilih` yang duduk di ujung kanan strip."""
    blok = HTML.split('<div class="tata">', 1)[1].split("</div>\n</section>", 1)[0]
    assert "pilih-panel--kanan" in blok


# ── tombol lihat sandi ─────────────────────────────────────────────────────────


def test_tombol_lihat_sandi_ada_di_gerbang():
    """Diketik buta, sering pakai sarung tangan, di layar sentuh luar ruangan. Tanpa
    cara melihat yang diketik, satu salah ketik terbaca sebagai "sandi saya ditolak"."""
    blok = HTML.split('<div class="gerbang-isi">', 1)[1].split("</div>", 1)[0]
    assert 'id="gerbang-lihat"' in blok


def test_tombol_lihat_sandi_menukar_type_bukan_menaruh_sandi_di_DOM():
    """Menampilkannya dengan menulis nilai ke elemen lain akan menyalin sandi ke tempat
    kedua yang gampang ikut ter-render atau ter-log. Yang ditukar atribut `type`."""
    fn = _fungsi("lihatSandi")
    assert '"text"' in fn and '"password"' in fn
    assert ".value" not in fn, "sandi tidak boleh disalin ke tempat lain"


def test_status_lihat_sandi_tidak_ikut_tersimpan():
    """`simpan()` menaruh di localStorage. Sandi terbuka yang bertahan antar sesi bikin
    layar bersama menampilkan sandi operator berikutnya."""
    assert "simpan(\"lihatSandi\"" not in HTML


def test_sandi_kembali_tertutup_setiap_gerbang_dibuka():
    """Operator berikutnya tidak boleh mewarisi kolom yang masih terbuka."""
    assert "tutupSandi()" in _fungsi("bukaGerbang")


def test_tombol_lihat_sandi_punya_label_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("lihatSandi", "sembunyikanSandi"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


# ── pagination riwayat grading ────────────────────────────────────────────────


def test_grading_punya_pemilih_jumlah_baris_dan_tombol_halaman():
    blok = HTML.split('<section id="sec-grading"', 1)[1].split("</section>", 1)[0]
    assert 'id="grading-per"' in blok, "belum ada pemilih jumlah baris per halaman"
    assert 'id="grading-prev"' in blok and 'id="grading-next"' in blok


def test_halaman_grading_dibaca_dari_total_server_bukan_panjang_halaman():
    """`items.length` cuma sepanjang satu halaman, jadi halaman terakhir yang kebetulan
    penuh akan terbaca sebagai "masih ada lagi" selamanya."""
    assert "gradingTotal = r.total" in _fungsi("muatGrading")
    # Yang menentukan ada-tidaknya halaman berikutnya harus total, bukan panjang halaman.
    batas = _fungsi("segarkanHalaman")
    assert "gradingTotal" in batas
    assert "items.length" not in batas


def test_polling_dua_detik_tidak_menarik_halaman_yang_sedang_dibaca():
    """Kalau tarikan 2 detik ikut menimpa tabel, operator yang sedang di halaman 3
    dilempar balik ke halaman 1 tiap dua detik. Halaman selain yang pertama dipegang."""
    fn = _fungsi("refresh")
    assert "gradingOffset" in fn


def test_pindah_halaman_tidak_pernah_offset_negatif():
    """Tombol Sebelumnya di halaman pertama tidak boleh mengirim offset negatif: server
    menolaknya 422 dan layar cuma menampilkan error tanpa sebab yang kelihatan."""
    fn = _fungsi("gantiHalaman")
    assert "Math.max(0" in fn


def test_label_pagination_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("perHalaman", "halamanSebelum", "halamanBerikut", "rentangBaris"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


def test_tombol_lihat_sandi_duduk_di_dalam_kolom():
    """Tombol terpisah di samping kolom tidak terbaca sebagai "lihat sandi" oleh yang
    memakainya. Posisinya di dalam kolom, seperti layar login mana pun."""
    aturan = next(b for b in HTML.splitlines() if ".sandi-lihat {" in b)
    assert "position:absolute" in aturan.replace(" ", "")
    # Dan tidak boleh menutupi teks: kolomnya menyisakan ruang selebar tombol, jadi
    # ketukan di ujung sandi yang sudah diketik tetap mendarat di kolomnya.
    input_aturan = next(b for b in HTML.splitlines() if ".sandi-baris input" in b)
    assert "padding-right" in input_aturan


def test_tulisan_tombol_berubah_saat_sandi_terbuka():
    """Latarnya tidak diwarnai penuh, jadi yang memberi tahu keadaannya tulisannya.
    Satu kata untuk dua keadaan berarti tidak ada yang menandai sandi sedang terbuka."""
    fn = _fungsi("lihatSandi")
    assert "sembunyikanSingkat" in fn and "lihatSingkat" in fn


def test_tombol_lihat_sandi_tidak_memakai_data_t():
    """Wajahnya bergantian antara dua kunci, disetel `lihatSandi`. `data-t` di elemen itu
    akan menimpanya tiap ganti bahasa dan mengunci tulisannya di satu keadaan."""
    blok = HTML.split('id="gerbang-lihat"', 1)[1].split(">", 1)[0]
    assert "data-t=" not in blok
