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
import urllib.parse
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
    assert "+ e.message" not in HTML, "pakai alasan(e), bukan e.message mentah"


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
        "gerbangJudul",
        "gerbangPilih",
        "gerbangEmail",
        "gerbangSandi",
        "gerbangMasuk",
        "tombolKeluar",
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
    assert "JSON.stringify({ requested_by" not in HTML


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
    return setelah_guard.split("} else {", 1)[0]


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
    assert blok.count("confirm(") == 1, "harus ada tepat satu confirm() di cabang piston"
    sebelum_confirm = blok.split("confirm(", 1)[0]
    assert re.search(r"if\s*\(\s*buka\s*&&", sebelum_confirm), (
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
    setelah_guard = blok.split("confirm(", 1)[1]
    setelah_return = setelah_guard.split("return;", 1)[1]
    assert "api(" in setelah_return, "cabang piston tidak pernah memanggil endpoint"
    jalur_bersama = setelah_return.split("api(", 1)[0]
    assert "if (buka" not in jalur_bersama, (
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
    dari_awal = HTML.split("let pTahan = false;", 1)[1]
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
    aturan = next(baris for baris in HTML.splitlines() if ".pilih-panel--kanan" in baris and "right" in baris)
    assert "right:0" in aturan.replace(" ", "")
    assert "left:auto" in aturan.replace(" ", ""), "left:0 bawaan harus dibatalkan"


def test_dropdown_tata_letak_memakai_varian_kanan():
    """Ini satu-satunya `.pilih` yang duduk di ujung kanan strip."""
    blok = HTML.split('<div class="tata">', 1)[1].split("</div>\n</section>", 1)[0]
    assert "pilih-panel--kanan" in blok


def test_ada_varian_panel_ke_atas():
    """Panel yang duduk di kaki tabel panjang tumbuh ke bawah, keluar dari ujung
    halaman, dan operator harus menggulir dulu untuk menjangkau pilihannya.

    Sama seperti `--kanan`, ini tidak bisa dipukul rata ke semua `.pilih` (yang di
    atas justru jadi salah arah), jadi dipakai penanda posisi eksplisit.
    """
    assert ".pilih-panel--atas" in HTML, "belum ada varian panel yang membuka ke atas"
    aturan = next(baris for baris in HTML.splitlines() if ".pilih-panel--atas" in baris and "bottom" in baris)
    assert "top:auto" in aturan.replace(" ", ""), "top bawaan harus dibatalkan"
    assert "bottom:calc(100%+4px)" in aturan.replace(" ", "")


def test_dropdown_baris_per_halaman_memakai_varian_atas():
    """`.pilih` ini duduk paling bawah di tab Grading, di bawah tabelnya."""
    blok = HTML.split('<div class="halaman">', 1)[1].split("</div>\n</section>", 1)[0]
    assert "pilih-panel--atas" in blok


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
    assert 'simpan("lihatSandi"' not in HTML


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


def test_pindah_halaman_tidak_pernah_keluar_rentang():
    """Offset negatif maupun offset melewati akhir daftar dibalas 422 oleh server, dan
    layar cuma menampilkan error tanpa sebab yang kelihatan.

    Dijepitnya di `keHalaman`, satu tempat: tombol nomor dan tombol
    Sebelumnya/Berikutnya dua-duanya lewat sana, jadi tidak ada jalur yang bisa lolos
    tanpa penjepitan.
    """
    assert "keHalaman(" in _fungsi("gantiHalaman"), "harus lewat keHalaman, bukan hitung sendiri"
    penjepit = _fungsi("keHalaman")
    assert "Math.max(1" in penjepit and "Math.min(" in penjepit


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


# ── nomor baris & lompat halaman ─────────────────────────────────────────────


def test_nomor_baris_ikut_halaman_bukan_selalu_mulai_dari_satu():
    """Ketemu di PC Lampung 2026-09-15 dengan 130.506 baris: nomor di kolom "No"
    selalu 1-200 di setiap halaman, jadi dua baris berbeda punya nomor sama dan
    operator tidak bisa menyebut "baris nomor 412" ke siapa pun.

    Nomornya harus offset halaman + posisi, bukan posisi saja.
    """
    fn = _fungsi("barisRecent")
    assert "gradingOffset" in fn, "nomor baris tidak memakai offset halaman"


def test_lompat_halaman_ada_supaya_tidak_klik_berkali_kali():
    """130.506 baris pada 200 per halaman = 653 halaman. Tanpa lompat, halaman 300
    berarti 299 kali klik Berikutnya."""
    blok = HTML.split('<section id="sec-grading"', 1)[1].split("</section>", 1)[0]
    assert 'id="grading-nomor"' in blok, "belum ada tombol nomor halaman"


def test_nomor_halaman_dibatasi_jumlahnya():
    """653 tombol halaman akan memenuhi layar. Yang ditampilkan jendela di sekitar
    halaman sekarang, plus yang pertama dan terakhir supaya dua ujung selalu terjangkau."""
    fn = _fungsi("tombolNomorHalaman")
    assert "JENDELA_HALAMAN" in fn or "jendela" in fn.lower()


def test_lompat_halaman_menolak_di_luar_rentang():
    """Halaman 0 atau halaman 700 dari 653 mengirim offset yang dibalas 422, dan
    layar cuma menampilkan error tanpa sebab yang kelihatan."""
    fn = _fungsi("keHalaman")
    assert "Math.max" in fn and "Math.min" in fn


def test_input_lompat_halaman_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        assert "keHalaman:" in isi, f"KAMUS.{bahasa} belum punya keHalaman"


def test_favicon_tertanam_bukan_berkas_luar():
    """Konsol harus tetap utuh saat internet mati dan `static/` tidak di-mount,
    jadi lambangnya ikut di dalam berkas — bukan URL yang harus diambil."""
    ikon = re.search(r'<link rel="icon" href="([^"]*)">', HTML)
    assert ikon, "link favicon hilang"
    href = ikon.group(1)
    assert href.startswith("data:image/svg+xml,"), "favicon menunjuk ke luar berkas"
    # `xmlns` itu label namespace XML, bukan alamat yang diambil browser — dibuang
    # dulu supaya sisanya benar-benar diperiksa sebagai permintaan jaringan.
    isi = urllib.parse.unquote(href).replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in isi and "https://" not in isi, "favicon menarik sesuatu dari jaringan"


def test_favicon_tidak_memutus_atribut_href():
    """Kutip ganda dan `#` mentah di dalam data URI memutus atribut href — yang
    pertama menutup href lebih awal, yang kedua dibaca sebagai fragment URL.
    Keduanya bikin ikon diam-diam tidak muncul, tanpa error di mana pun."""
    href = re.search(r'<link rel="icon" href="([^"]*)">', HTML).group(1)
    muatan = href[len("data:image/svg+xml,") :]
    assert '"' not in muatan, "kutip ganda mentah memutus atribut href"
    assert "#" not in muatan, "# mentah memotong data URI jadi fragment"
    dipulihkan = urllib.parse.unquote(muatan)
    assert dipulihkan.lstrip().startswith("<svg"), "data URI tidak memuat SVG"
    assert dipulihkan.rstrip().endswith("</svg>")


# ── halaman cetak QR ────────────────────────────────────────────────────────


def test_tab_truk_punya_tombol_cetak_qr():
    blok = HTML.split('<section id="sec-truk"', 1)[1].split("</section>", 1)[0]
    assert 'id="cetak-qr"' in blok


def test_kartu_qr_memuat_gambar_dari_server_bukan_pustaka_cdn():
    """`console.html` nol referensi https:// dengan sengaja — layar harus tetap terbuka
    saat internet mati, dan QR yang gagal dimuat berarti gerbang berhenti."""
    fn = _fungsi("kartuQr")
    assert "/api/console/trucks/" in fn and "qr.png" in fn
    assert "https://" not in fn


def test_plat_di_url_qr_di_encode():
    """Plat masuk ke URL. Tanpa encode, plat berspasi memotong URL-nya dan gambarnya
    tidak pernah dimuat."""
    assert "encodeURIComponent" in _fungsi("kartuQr")


def test_kartu_qr_juga_mencetak_platnya_sebagai_tulisan():
    """QR yang rusak atau kotor tidak terbaca scanner. Nomor platnya harus tetap ada
    supaya operator bisa mengetiknya manual."""
    fn = _fungsi("kartuQr")
    assert "plate_number" in fn


def test_nama_truk_di_kartu_lewat_esc():
    """Plat truk manual diketik operator, jadi nilai dari database masuk ke HTML."""
    assert "esc(" in _fungsi("kartuQr")


def test_halaman_cetak_disembunyikan_saat_tidak_mencetak():
    """Kartunya menumpuk di bawah tabel kalau tidak disembunyikan, dan layar operator
    dibaca dari jauh — satu layar penuh kartu QR membuat tab Truk tidak terpakai."""
    assert 'id="qr-cetak"' in HTML
    aturan = [b for b in HTML.splitlines() if "#qr-cetak" in b and "display" in b]
    assert aturan, "#qr-cetak tidak punya aturan display"


def test_label_cetak_qr_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("btnCetakQr", "qrJudul"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


# ── kolom scan di timbang masuk ─────────────────────────────────────────────


def test_tab_timbangan_punya_kolom_scan():
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split("</section>", 1)[0]
    assert 'id="scan-plat"' in blok


def test_dropdown_plat_tetap_ada_sebagai_cadangan():
    """Scanner rusak, layar HP retak, QR belum dicetak — tiga kejadian nyata di gerbang.
    Scan melengkapi cara lama, tidak menggantikannya."""
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split("</section>", 1)[0]
    assert 'id="plat-timbang"' in blok


def test_scan_dikirim_saat_enter_bukan_butuh_tombol():
    """Scanner barcode itu papan ketik: dia mengetik isi QR lalu menekan Enter sendiri.
    Kalau butuh klik tombol, operator harus menyentuh layar tiap truk dan gunanya
    scan hilang."""
    # Enter ditangani di listener keydown pada kolom scan itu sendiri.
    blok = HTML.split('$("scan-plat").addEventListener("keydown"', 1)
    assert len(blok) == 2, "kolom scan tidak menangani Enter"
    assert '"Enter"' in blok[1][:200], "keydown-nya tidak memeriksa Enter"
    assert "kirimScan()" in blok[1][:400], "Enter tidak mengirim scan"


def test_scan_memanggil_lane_scan_bukan_menebak_sendiri():
    """Normalisasi plat dan penolakan QR sampah hidup di server (`domain/qr.py`).
    Layar yang menebak sendiri akan punya aturan kedua yang bisa berbeda."""
    assert "/api/console/scan" in _fungsi("kirimScan")


def test_scan_yang_ketemu_mengisi_plat_lalu_pindah_ke_bruto():
    """Yang menghemat waktu bukan scan-nya saja, tapi kursor yang sudah siap di kolom
    berikutnya: operator menimbang sambil memegang HP supir."""
    fn = _fungsi("kirimScan")
    assert "pilihNilai" in fn and "plat-timbang" in fn
    assert 'bruto").focus' in fn


def test_scan_ganda_dalam_sekejap_diabaikan():
    """Scanner kadang membaca satu QR dua kali dalam beberapa ratus milidetik. Tanpa
    penjaga, kiriman kedua menimpa apa yang baru terisi."""
    fn = _fungsi("kirimScan")
    assert "scanSibuk" in fn


def test_truk_belum_terdaftar_diarahkan_ke_pendaftaran_manual():
    """Truk pinjaman itu alasan fitur ini ada. Layar harus mengatakan apa yang bisa
    dilakukan, bukan cuma "tidak ditemukan"."""
    fn = _fungsi("kirimScan")
    assert "ditemukan" in fn
    for bahasa in ("id", "en"):
        assert "scanBelumAda:" in _kamus(bahasa)


def test_kolom_scan_dikosongkan_setelah_dibaca():
    """Isi yang tertinggal akan tersambung dengan scan berikutnya menjadi satu teks
    panjang yang tidak cocok plat mana pun."""
    assert 'scan-plat").value = ""' in _fungsi("kirimScan")


def test_label_scan_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("phScan", "scanBelumAda"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


def test_pesan_hasil_scan_tidak_terhapus_polling_dua_detik():
    """Ketemu di browser: pesan "truk belum terdaftar" hilang dalam 2 detik karena
    `refresh()` selalu membersihkan banner saat berhasil. Operator gerbang yang sedang
    memegang HP supir tidak akan pernah membacanya.

    Pesan hasil scan punya tempatnya sendiri di dekat kolomnya, bukan banner global.
    """
    assert 'id="scan-pesan"' in HTML
    # `_fungsi` memotong di `\n}` pertama, dan `kirimScan` punya blok bersarang — jadi
    # yang diiris di sini seluruh badannya, dari namanya sampai listener berikutnya.
    badan = HTML.split("async function kirimScan()", 1)[1].split('$("scan-plat").addEventListener', 1)[0]
    assert "pesanScan(" in badan, "hasil scan masih memakai banner global"
    assert "pesan(" not in badan.replace("pesanScan(", ""), "masih ada jalur ke banner global"


# ── scan di gerbang keluar ──────────────────────────────────────────────────


def test_scan_keluar_memanggil_lane_keluar_bukan_lane_masuk():
    """Dua scan, dua jawaban berbeda: yang masuk mencari truk, yang keluar mencari
    tiket yang menunggu tara."""
    assert "/api/console/scan/keluar" in _fungsi("kirimScanKeluar")


def test_dua_tiket_terbuka_diminta_dipilih_bukan_ditebak():
    """Keputusan operator 2026-09-15. Menebak bisa memasangkan tara ke kunjungan yang
    salah dan mencampur tonase dua kunjungan."""
    fn = _fungsi("kirimScanKeluar")
    assert "ganda" in fn
    for bahasa in ("id", "en"):
        assert "scanGanda:" in _kamus(bahasa)


def test_tombol_timbang_keluar_per_baris_tetap_ada():
    """Scan melengkapi, tidak menggantikan: scanner rusak atau QR belum dicetak tetap
    harus bisa menimbang keluar."""
    assert 'data-aksi="keluar"' in HTML


def test_label_scan_keluar_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("phScanKeluar", "scanTakAdaTiket"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


# ── dua kolom scan harus bisa dibedakan di layar ────────────────────────────


def test_setiap_kolom_scan_punya_label_sendiri():
    """Ketemu dari screenshot operator: dua kolom bertulisan "Scan QR truk" yang sama,
    satu di atas satu di bawah, tanpa penanda mana yang mana. Yang atas MEMBUAT tiket,
    yang bawah MENUTUP tiket — ketukar berarti tiket dobel.
    """
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split("</section>", 1)[0]
    assert 'for="scan-plat"' in blok, "kolom scan masuk tanpa label"
    assert 'for="scan-keluar"' in blok, "kolom scan keluar tanpa label"


def test_placeholder_dua_kolom_scan_tidak_sama():
    """Kalau placeholder-nya sama, label pun tidak menolong saat operator melihat
    cepat: yang dibaca pertama itu isi kolomnya."""
    assert _kamus("id").count('phScan:"Scan QR truk"') <= 1
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        masuk = re.search(r'phScan:"([^"]+)"', isi).group(1)
        keluar = re.search(r'phScanKeluar:"([^"]+)"', isi).group(1)
        assert masuk != keluar, f"KAMUS.{bahasa}: placeholder dua kolom scan sama"


def test_label_arah_gerbang_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("lbGerbangMasuk", "lbGerbangKeluar"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


def test_dua_kolom_scan_dalam_satu_baris_alat():
    """Layar operator dibaca dari beberapa meter; satu baris alat yang tinggi itu ruang
    kamera yang hilang. Dua kolom scan hidup di SATU `.tools`, bukan dua baris."""
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split('<div class="tabel">', 1)[0]
    # Dicocokkan per kelas, bukan per string persis: barisnya boleh punya kelas kedua.
    assert len(re.findall(r'class="tools\b', blok)) == 1, (
        "kolom scan masih terpecah di dua baris alat"
    )


def test_kelas_gerbang_login_tidak_dipakai_di_tab_timbangan():
    """Akar bug tata letak yang terlihat di screenshot operator: kolom scan memakai
    `.gerbang-isi`, nama yang sudah dipakai gerbang LOGIN (flex column, input 3.4rem).
    Aturan login menang, dan kolom scan melar jadi kotak raksasa yang berhamburan.

    Satu file CSS tanpa scoping berarti nama kelas itu ruang nama global. Yang dipakai
    di tab Timbangan harus berawalan `timbang-`, bukan `gerbang-`.
    """
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split("</section>", 1)[0]
    bocor = re.findall(r'class="[^"]*\bgerbang-[\w-]+', blok)
    assert not bocor, f"kelas gerbang login dipakai di tab Timbangan: {bocor}"


def test_pemisah_dua_gerbang_ikut_berpindah_saat_turun_baris():
    """Di layar sempit gerbang keluar turun ke baris kedua, dan garis di KIRI jadi
    janggal karena tidak ada apa pun di sebelahnya. Dibuktikan di browser: 1440 px
    garis kiri, 1280 px garis atas."""
    assert ".timbang-keluar" in HTML
    aturan = HTML.split("@media (max-width:1330px)", 1)
    assert len(aturan) == 2, "belum ada aturan layar sempit untuk pemisah gerbang"
    assert "border-top" in aturan[1][:300]


# ── kolom tara inline, bukan dialog yang menutup layar ─────────────────────


def test_tara_tidak_memakai_prompt_bawaan_browser():
    """`prompt()` di layar pabrik: kotaknya kecil untuk jempol bersarung tangan, tidak
    bisa diatur ukurannya, dan menerima teks apa pun tanpa validasi."""
    assert "prompt(" not in HTML, "masih memakai prompt() bawaan browser"


def test_tara_tidak_menutup_layar():
    """Dilaporkan operator: dialog yang menutup seluruh layar menghilangkan kamera line
    dan strip tally sampai tara selesai diisi. Di gerbang yang sibuk itu kehilangan
    pandangan justru saat paling butuh.

    Kolomnya muncul DI BARIS ALAT, bukan sebagai lapisan di atas layar.
    """
    assert 'id="dialog-tara"' not in HTML, "masih memakai overlay yang menutup layar"
    assert "position:fixed" not in HTML.split(".tara-isi", 1)[0][-400:]


def test_kolom_tara_ada_di_baris_alat_gerbang_keluar():
    blok = HTML.split('class="timbang-sisi timbang-keluar"', 1)[1].split("</div>\n  </div>", 1)[0]
    assert 'id="tara-nilai"' in blok, "kolom tara tidak ada di sisi gerbang keluar"
    assert 'id="tara-simpan"' in blok


def test_kolom_tara_disembunyikan_sampai_scan_berhasil():
    """Kolom yang selalu terlihat tanpa truk terpilih adalah kolom yang bisa diisi lalu
    tidak tahu harus ke tiket mana."""
    assert 'id="tara-grup" hidden' in HTML or 'id="tara-grup"' in HTML
    assert "tara-grup" in _fungsi("tanyaTara")


def test_kolom_tara_menyebut_platnya():
    """Operator melihat beberapa truk sehari; kolom tanpa nama truk bisa mendarat di
    kunjungan yang salah."""
    assert 'id="tara-plat"' in HTML
    assert "tara-plat" in _fungsi("tanyaTara")


def test_kolom_tara_memvalidasi_angka_sebelum_dikirim():
    fn = _fungsi("simpanTara")
    assert "MINIMUM_BERAT" in fn


def test_kolom_tara_bisa_dibatalkan():
    assert 'id="tara-batal"' in HTML
    assert "tutupTara" in _fungsi("simpanTara") or "tutupTara" in HTML


def test_enter_di_kolom_tara_menyimpan():
    blok = HTML.split('$("tara-nilai").addEventListener("keydown"', 1)
    assert len(blok) == 2, "Enter di kolom tara tidak ditangani"
    assert '"Enter"' in blok[1][:200]


def test_label_tara_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("btnSimpanTara", "taraMinimum", "phTara"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


# ── konfirmasi uji PLC inline, bukan prompt() bawaan browser (2026-09-16) ───
# Regression guard: the PLC coil test used to fire through `prompt()`, which a
# rebase from staging then forbade console-wide (same reasoning as tara: the
# box is tiny for a gloved thumb, can't be sized, and takes any text with no
# validation). It must stay inline like tara AND keep requiring the typed
# word - a click alone can be brushed on a touchscreen, and this is the only
# console screen that fires a PLC coil and moves a piston.


def test_uji_plc_tidak_memakai_dialog_bawaan_browser():
    assert "prompt(" not in HTML, "uji PLC masih memakai prompt() bawaan browser"
    assert "confirm(" not in _fungsi("jalankanUjiPlc"), "uji PLC memakai confirm() bawaan browser"


def test_kolom_konfirmasi_plc_ada_dan_disembunyikan_sampai_diminta():
    blok = HTML.split('id="plc-konfirmasi"', 1)[1].split(">", 1)[0]
    assert "hidden" in blok, "grup konfirmasi PLC harus mulai tersembunyi"
    assert "plc-konfirmasi" in _fungsi("tanyaUjiPlc"), "tombol uji coil tidak membuka grup inline"


def test_konfirmasi_plc_tetap_wajib_ketik_uji():
    """Beda dari tara: kolom ini bukan validasi angka tapi kata sandi sekali pakai
    untuk memicu hardware sungguhan. Klik saja - bahkan lewat confirm() - bisa
    tersenggol jempol bersarung tangan di layar sentuh; ketikan tidak."""
    fn = _fungsi("jalankanUjiPlc")
    assert '!== "UJI"' in fn, "konfirmasi uji PLC tidak lagi memvalidasi ketikan UJI"
    assert "konfirmasi: \"UJI\"" in fn, "body POST tidak lagi mengirim konfirmasi: UJI"


def test_batal_konfirmasi_plc_tidak_mengirim_apa_pun():
    fn = _fungsi("tutupUjiPlc")
    assert "hidden = true" in fn
    assert "ujiUntuk = null" in fn, "batal harus melepas coil/line yang sedang ditanyakan"
    assert "api(" not in fn, "batal tidak boleh memanggil endpoint apa pun"


def test_konfirmasi_plc_menyebut_coil_dan_line():
    """Sama seperti prompt() lama: operator harus tahu coil DAN line mana yang
    akan menyala sebelum mengetik UJI."""
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        assert "konfirmasiUjiPlc:" in isi
    assert "{coil}" in HTML.split("konfirmasiUjiPlc:", 1)[1][:200]
    assert "{line}" in HTML.split("konfirmasiUjiPlc:", 1)[1][:200]


def test_label_konfirmasi_plc_diterjemahkan():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("phUjiPlc", "btnUjiPlcJalankan", "konfirmasiUjiPlc", "ujiPlcDibatalkan"):
            assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


# ── tab developer (2026-09-15) ─────────────────────────────────────────────


# ── developer tab (2026-09-15) ─────────────────────────────────────────────


def test_tab_developer_ditandai_data_dev():
    assert 'data-dev="1"' in HTML


def test_tab_developer_disembunyikan_default():
    """Without a support role, the developer tab must not appear on screen."""
    assert "hapusTabDeveloper" in HTML


def test_konsol_tetap_tanpa_referensi_https():
    """Long-standing invariant: the console must run with the internet down."""
    assert "https://" not in HTML


# ── tab ↔ panel mapping ─────────────────────────────────────────────────────


def test_setiap_tab_berpanel_punya_id_yang_cocok():
    """`terapkanTab()` (Task 7) skips a tab with no `sec-*` panel instead of
    throwing on a null `$()` lookup - which means a typo'd id now fails
    silently rather than loudly (the tab looks clickable but nothing shows).
    The Log panel is the first dev panel to exist, so from here on a mismatch
    has something to be caught by, in both directions:
    - a tab this screen expects to work must have a panel at the right id;
    - a panel that exists must be reachable from some data-tab button (a
      typo'd id orphans the panel instead of merely mislabelling it)."""
    # The tabs wired to a working panel today - kept here, not derived from
    # TAB_SAH in the script, so a JS-side typo cannot make this test agree
    # with the very bug it exists to catch.
    tab_dengan_panel = {"grading", "truk", "timbangan", "rekap", "log"}

    data_tab = set(re.findall(r'data-tab="(\w+)"', HTML))
    id_panel = set(re.findall(r'<section id="sec-(\w+)"', HTML))

    for tab in tab_dengan_panel:
        assert tab in data_tab, f"tab {tab!r} tidak lagi punya tombol data-tab"
        assert tab in id_panel, f"tab {tab!r} tidak punya panel id=\"sec-{tab}\""

    yatim = id_panel - data_tab
    assert not yatim, f"panel ada tapi id-nya tidak cocok tombol mana pun: {sorted(yatim)}"
