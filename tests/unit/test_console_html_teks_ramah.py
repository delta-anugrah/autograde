"""Plain-language screen text outside the Log tab (user decision 2026-10-01, PR #200).

After testing PR #200 the user decided: on every console screen EXCEPT the Log tab, no
system error text may be visible. No HTTP status, URL, raw exception or server text, env
var or config name, file name, or error code; messages still say what happened, which
line, since when, and what to do. The Log tab (support only) stays technical, and that is
where the raw detail goes.

Two layers, like `test_console_html_antrean_line.py`:
- text invariants, always run: KAMUS in both languages, static HTML, CSS, helpers;
- behaviour through node with the REAL KAMUS (`konsol_js`): `alasan()`, `api()` when the
  console does not answer, the Diagnostik card, the line queue and the ERP queue.
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest
from konsol_js import HTML, NODE, esc_asli, fungsi, jalankan, kamus_asli

from palmgrade.domain.line_tak_terbaca import SEBAB_SEMUA
from palmgrade.integrations.erp.outbox_store import JENIS_GAGAL

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

#: Keys shown ONLY on the Log tab (its Discord status sentence), which stays technical.
KHUSUS_TAB_LOG = frozenset({
    "discordMati", "discordUrlSalah", "discordAktif", "discordTertahan",
    "discordDitolak", "discordRusak", "discordIsiDitolak",
})

#: What no screen text outside the Log tab may contain.
TERLARANG = {
    "nama env/konfigurasi (UPPER_SNAKE)": r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b",
    "kode HTTP": r"HTTP",
    "alamat web": r"https?://",
    "placeholder kode": r"\{kode\}",
    "kode galat": r"Kode \{|\(kode",
    "placeholder status HTTP": r"\{status\}",
    "placeholder jalur": r"\{path\}",
    "placeholder teks galat mentah": r"\{galat\}",
    "berkas .env": r"\.env\b",
    "berkas .db": r"\.db\b",
    "jalur folder": r"\b[a-z_]{3,}/",
    "berkas .pt": r"\.pt\b",
    "perintah make": r"\bmake (?:operator|up|console|line|demo|restart|reset)",
}

#: Info sentences on support-only screens that may name the recordings folder (fix wave
#: ruling, rule 21): support has to find the file. Exempt from "jalur folder" only.
INFO_FOLDER = frozenset({"rekamSelesai", "rekamCatatanRetensi", "bahayaRekamanTeks"})


def _kamus(bahasa: str) -> dict[str, str]:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok.group(1)))


def _pelanggaran(teks: str, kunci: str = "") -> list[str]:
    return [
        nama for nama, pola in TERLARANG.items()
        if re.search(pola, teks) and not (nama == "jalur folder" and kunci in INFO_FOLDER)
    ]


# ── text invariants ─────────────────────────────────────────────────────


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kamus_di_luar_tab_log_tanpa_teks_sistem(bahasa):
    salah = {
        k: _pelanggaran(v, k) for k, v in _kamus(bahasa).items()
        if k not in KHUSUS_TAB_LOG and _pelanggaran(v, k)
    }
    assert not salah, salah


def test_daftar_khusus_tab_log_masih_ada_di_kamus():
    """A stale allow-list would let a renamed key slip through unchecked."""
    for bahasa in ("id", "en"):
        assert KHUSUS_TAB_LOG <= set(_kamus(bahasa)), bahasa
        assert INFO_FOLDER <= set(_kamus(bahasa)), bahasa


def test_teks_statis_html_tanpa_teks_sistem():
    tampil = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", "", HTML, flags=re.S)
    baris = [b.strip() for b in re.sub(r"<[^>]+>", "\n", tampil).splitlines() if b.strip()]
    atribut = re.findall(r'(?:placeholder|title|aria-label)="([^"]*)"', tampil)
    # Static defaults of the INFO_FOLDER keys (replaced by KAMUS at runtime) carry the folder too.
    info = {_kamus("id")[k] for k in INFO_FOLDER}
    salah = [t for t in baris + atribut if _pelanggaran(t) and t not in info]
    assert not salah, salah


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_setiap_sebab_line_tak_terbaca_punya_kalimat(bahasa):
    """`sebab_kode` from the backend (domain/line_tak_terbaca.py) -> `lineSebab_<code>`."""
    kamus = _kamus(bahasa)
    hilang = [s for s in SEBAB_SEMUA if f"lineSebab_{s}" not in kamus]
    assert not hilang, hilang


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_setiap_jenis_gagal_antrean_punya_kalimat(bahasa):
    """`error_kind` from ErpOutboxStore -> `antreanSebab_<code>`, plus the generic one."""
    kamus = _kamus(bahasa)
    hilang = [j for j in (*JENIS_GAGAL, "lain") if f"antreanSebab_{j}" not in kamus]
    assert not hilang, hilang


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kalimat_umum_dan_konsol_putus_ada(bahasa):
    kamus = _kamus(bahasa)
    for kunci in ("err_umum", "err_konsol_putus", "gagalUmum", "antreanLineGalatTerakhir"):
        assert kunci in kamus, kunci


def test_kunci_lama_yang_menyebut_http_dibuang():
    """Replaced by `lineSebab_*`, which the Diagnostik card and the line queue share."""
    for kunci in ("antreanLineKunciKonsol:", "antreanLineErrorLine:", "antreanLineTakTerjangkau:"):
        assert kunci not in HTML, kunci


def test_alasan_tidak_pernah_memakai_teks_server():
    assert ".message" not in fungsi("alasan")


def test_setelan_memakai_alasan_bukan_field_yang_tak_pernah_diisi():
    """`api()` fills `message`/`kode`, never `pesan`/`detail`: those paths always wrote "gagal"."""
    muat = fungsi("muatSetelan")
    simpan = HTML.split('$("set-simpan").addEventListener("click"', 1)[1].split("\n}));", 1)[0]
    for blok in (muat, simpan):
        assert "e.pesan" not in blok and "e.detail" not in blok
        assert "alasan(e, " in blok
    # The field is still highlighted: read from the server text, never shown.
    assert 'setAttribute("aria-invalid", "true")' in simpan


def test_pita_dan_kotak_tidak_lagi_mengisi_kode():
    for nama in ("pitaAi", "pitaDisk", "isiRestart", "pitaKunciDitolak", "pesanGagalKirimUlang"):
        fn = fungsi(nama)
        assert '"{kode}"' not in fn and '"{status}"' not in fn, nama
    assert "RESTART_KODE" not in HTML


def test_kartu_diagnostik_tidak_menulis_sebab_mentah():
    fn = fungsi("kartuDiagnostik")
    assert "d.sebab)" not in fn and "d.sebab}" not in fn
    assert "kunciSebabTakTerbaca(d)" in fn


def test_antrean_erp_tidak_menulis_last_error():
    assert "last_error" not in fungsi("barisAntrean")


def test_kotak_versi_selebar_bagian_status_lain():
    """User 2026-10-01: the Versi box stood inset from the Diagnostik grid and the
    queue tables. All three now sit on the panel's own padding: none adds a side margin."""
    def aturan(pemilih: str) -> str:
        cocok = re.search(rf"(?m)^\s*{re.escape(pemilih)}\s*\{{([^}}]*)\}}", HTML)
        assert cocok, pemilih
        return cocok.group(1)

    def margin_samping(isi: str) -> str | None:
        m = re.search(r"(?:^|[;\s])margin\s*:\s*([^;]+)", isi)
        if m is None:
            return None
        nilai = m.group(1).split()
        return nilai[1] if len(nilai) > 1 else nilai[0]

    for pemilih in (".daftar-definisi", ".kartu-grid", ".tabel"):
        isi = aturan(pemilih)
        assert margin_samping(isi) in (None, "0"), (pemilih, isi)
        assert "margin-left" not in isi and "margin-right" not in isi, pemilih
    assert not re.search(r"#versi-daftar\s*\{[^}]*margin", HTML)
    assert not re.search(r"#sec-status[^{]*\.daftar-definisi\s*\{[^}]*margin", HTML)


# ── behaviour through node, with the real KAMUS ─────────────────────────

MENTAH = "line-1 did not answer: Client error '404 Not Found' for url 'http://127.0.0.1:8001/internal/status'"
POTONGAN_MENTAH = ("404", "Not Found", "http", "did not answer", "internal/status", "HTTP", "Client error")
DASH = 'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));'
DIAG = ["tanda", "diagPlc", "diagAngka", "diagFrame", "diagDisk", "diagLisensi", "diagNol",
        "kunciSebabTakTerbaca", "kartuDiagnostik"]
ANTREAN_LINE = ["kunciSebabTakTerbaca", "keadaanAntreanLine", "barisAntreanLine", "waktu", "lamaProses"]
SEHAT = {"terjangkau": True, "aktif": True, "lama_tertinggal": False, "menunggu": 3, "tersambung": True}
JAM = 1_789_873_200


def _esc(teks: str) -> str:
    """Python twin of the screen's `esc()`, to find a KAMUS sentence inside rendered HTML."""
    ganti = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"}
    return "".join(ganti.get(c, c) for c in teks)


def _tanpa_mentah(teks: str) -> None:
    for potongan in POTONGAN_MENTAH:
        assert potongan not in teks, (potongan, teks)


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
@pytest.mark.parametrize("e", [
    {"kode": "kode_baru_dari_versi_lain", "message": MENTAH, "params": {}},
    {"message": MENTAH},
    {"kode": None, "message": "HTTP 500"},
])
def test_kode_asing_jadi_kalimat_umum_bukan_teks_server(bahasa, e):
    kamus = _kamus(bahasa)
    teks = jalankan(["kodeDikenal", "saranUmum", "alasan"], f"alasan({json.dumps(e)})", bahasa=bahasa)
    assert teks == f"{kamus['gagalUmum']}. {kamus['err_umum']}"
    _tanpa_mentah(teks)


@butuh_node
def test_kode_asing_dengan_konteks_pemanggil():
    kamus = _kamus("id")
    teks = jalankan(["kodeDikenal", "saranUmum", "alasan"], f"alasan({json.dumps({'message': MENTAH})}, 'gagalSumberKamera')")
    assert teks == f"{kamus['gagalSumberKamera']}. {kamus['err_umum']}"


@butuh_node
def test_kode_yang_dikenal_tetap_kalimatnya_sendiri_tanpa_status():
    e = {"kode": "line_menolak", "params": {"line": "Line 1", "status": 401}, "message": MENTAH}
    teks = jalankan(["kodeDikenal", "saranUmum", "alasan"], f"alasan({json.dumps(e)})")
    assert teks == _kamus("id")["err_line_menolak"].replace("{line}", "Line 1")
    assert "401" not in teks
    _tanpa_mentah(teks)


@butuh_node
def test_awalan_tidak_dobel_gagal_untuk_kode_asing():
    kamus = _kamus("id")
    fn = ["kodeDikenal", "saranUmum", "alasan", "gagalKarena"]
    dikenal = {"kode": "line_tidak_menjawab", "params": {"line": "Line 2"}, "message": MENTAH}
    assert jalankan(fn, f"gagalKarena('gagalDaftar', {json.dumps(dikenal)})") == (
        f"{kamus['gagalDaftar']}: {kamus['err_line_tidak_menjawab'].replace('{line}', 'Line 2')}")
    asing = {"message": MENTAH}
    assert jalankan(fn, f"gagalKarena('gagalDaftar', {json.dumps(asing)})") == (
        f"{kamus['gagalDaftar']}. {kamus['err_umum']}")


def _jalankan_api(fetch_js: str, bahasa: str = "id") -> dict:
    """`api()` itself, with `fetch` replaced: what the screen says when the console fails."""
    skrip = "\n".join([
        kamus_asli(), esc_asli(),
        f"let bahasa = {json.dumps(bahasa)};",
        "const t = (k) => KAMUS[bahasa][k] ?? k;",
        'const lokal = () => (bahasa === "id" ? "id-ID" : "en-GB");',
        "const $ = () => ({ hidden: true });",
        "const LANE_GERBANG = new Set();",
        "function bukaGerbang() {}",
        f"globalThis.fetch = {fetch_js};",
        fungsi("ambil"), fungsi("galatJawaban"), fungsi("api"), fungsi("kodeDikenal"), fungsi("saranUmum"), fungsi("alasan"),
        "(async () => { try { await api('/api/console/state'); console.log('null'); }"
        " catch (e) { console.log(JSON.stringify({ kode: e.kode ?? null, teks: alasan(e) })); } })();",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_konsol_yang_tidak_menjawab_punya_kalimatnya_sendiri(bahasa):
    """fetch rejects when no answer came at all; the browser's text never reaches the screen."""
    hasil = _jalankan_api('async () => { throw new TypeError("Failed to fetch"); }', bahasa)
    assert hasil == {"kode": "konsol_putus", "teks": _kamus(bahasa)["err_konsol_putus"]}


@butuh_node
def test_500_tanpa_kode_jadi_kalimat_umum():
    hasil = _jalankan_api(
        "async () => ({ ok: false, status: 500, json: async () => { throw new SyntaxError('Unexpected token'); } })")
    kamus = _kamus("id")
    assert hasil == {"kode": None, "teks": f"{kamus['gagalUmum']}. {kamus['err_umum']}"}


@butuh_node
def test_jawaban_berkode_tetap_diterjemahkan():
    detail = {"code": "line_tidak_menjawab", "params": {"line": "Line 1", "status": 404}, "message": MENTAH}
    hasil = _jalankan_api(
        f"async () => ({{ ok: false, status: 502, json: async () => ({{ detail: {json.dumps(detail)} }}) }})")
    assert hasil["teks"] == _kamus("id")["err_line_tidak_menjawab"].replace("{line}", "Line 1")
    _tanpa_mentah(hasil["teks"])


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
@pytest.mark.parametrize("sebab", [*SEBAB_SEMUA, None, "kode_dari_versi_baru"])
def test_kartu_line_tak_terbaca_menulis_kalimat_ramah(bahasa, sebab):
    d = {"terjangkau": False, "sebab": MENTAH}
    if sebab is not None:
        d["sebab_kode"] = sebab
    html = jalankan(DIAG, f"kartuDiagnostik('line-1', {json.dumps(d)})", bahasa=bahasa, tambahan=DASH)
    kunci = f"lineSebab_{sebab}" if sebab in SEBAB_SEMUA else "lineSebab_lain"
    assert _esc(_kamus(bahasa)[kunci]) in html
    _tanpa_mentah(html)


@butuh_node
@pytest.mark.parametrize("sebab", [*SEBAB_SEMUA, None])
def test_antrean_line_tak_terbaca_memakai_kalimat_yang_sama(sebab):
    d = {"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404, "pesan": MENTAH}
    if sebab is not None:
        d["sebab_kode"] = sebab
    html = jalankan(ANTREAN_LINE, f"barisAntreanLine('line-2', {json.dumps(d)}, 0)", tambahan=DASH)
    assert _esc(_kamus("id")[f"lineSebab_{sebab or 'lain'}"]) in html
    assert "data-kirim-ulang-line" not in html
    _tanpa_mentah(html)


@butuh_node
def test_galat_terakhir_line_cuma_jamnya_teksnya_di_tab_log():
    d = {**SEHAT, "tersambung": False, "sebab_putus": "tak_terjangkau", "putus_sejak": JAM,
         "galat": "ConnectError: All connection attempts failed", "galat_at": JAM}
    html = jalankan(ANTREAN_LINE, f"barisAntreanLine('line-1', {json.dumps(d)}, {JAM * 1000})", tambahan=DASH)
    jam = jalankan(["waktu"], f"waktu({JAM * 1000})")
    assert _esc(_kamus("id")["antreanLineGalatTerakhir"].replace("{jam}", jam)) in html
    assert "ConnectError" not in html and "connection attempts" not in html


@butuh_node
def test_janjang_ditolak_tanpa_alasan_mentah():
    d = {**SEHAT, "ditolak": 2, "ditolak_at": JAM, "ditolak_alasan": "HTTP 400: <timestamp cacat>",
         "galat": "HTTP 400: <timestamp cacat>", "galat_at": JAM}
    html = jalankan(ANTREAN_LINE, f"barisAntreanLine('line-2', {json.dumps(d)}, {JAM * 1000})", tambahan=DASH)
    assert "2 janjang DITOLAK konsol, terakhir pukul " in html
    assert "timestamp cacat" not in html and "HTTP" not in html


@butuh_node
@pytest.mark.parametrize("jenis", [*JENIS_GAGAL, None, "jenis_dari_versi_baru"])
def test_baris_antrean_erp_menulis_sebab_bukan_last_error(jenis):
    r = {"kind": "upsert_visit", "key": "WB-2026-00004", "attempts": 2, "next_attempt_at": 0,
         "last_error": "POST /api/method/erpnext.palm_mill.api.upsert_visit: HTTP 417: <b>Nomor</b>",
         "error_kind": jenis}
    html = jalankan(["jadwalAntrean", "waktu", "sebabAntrean", "barisAntrean"], f"barisAntrean({json.dumps(r)}, 'AutoERP')",
                    tambahan=DASH)
    kunci = f"antreanSebab_{jenis}" if jenis in JENIS_GAGAL else "antreanSebab_lain"
    assert _esc(_kamus("id")[kunci].replace("{tujuan}", "AutoERP")) in html
    assert "HTTP" not in html and "417" not in html and "api/method" not in html and "Nomor" not in html


@butuh_node
def test_antrean_manifest_menyebut_r2():
    r = {"kind": "visit_manifest", "key": "w-1", "attempts": 1, "next_attempt_at": 0,
         "last_error": "Could not connect to the endpoint URL", "error_kind": "tak_terjangkau"}
    html = jalankan(["jadwalAntrean", "waktu", "sebabAntrean", "barisAntrean"], f"barisAntrean({json.dumps(r)}, 'R2')",
                    tambahan=DASH)
    assert _esc(_kamus("id")["antreanSebab_tak_terjangkau"].replace("{tujuan}", "R2")) in html
    assert "endpoint" not in html


def test_kedua_tabel_antrean_menyebut_tujuannya():
    assert "barisAntrean(x, \"AutoERP\")" in fungsi("muatAntrean")
    assert "barisAntrean(x, \"R2\")" in fungsi("muatManifest")


@butuh_node
@pytest.mark.parametrize("e,saran", [
    ({"kode": "line_menolak", "params": {"line": "Line 1", "status": 401}, "message": MENTAH}, "saranKunciLine"),
    ({"kode": "line_tidak_menjawab", "params": {"line": "Line 1"}, "message": MENTAH}, "saranLineMati"),
    ({"kode": "line_tidak_menjawab", "params": {"line": "Line 1", "status": 500}, "message": MENTAH},
     "saranBukaLog"),
])
def test_gagal_kirim_ulang_tanpa_kode_dan_tanpa_teks_server(e, saran):
    teks = jalankan(
        ["kodeDikenal", "saranUmum", "alasan", "waktu", "pesanGagalKirimUlang"],
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        tambahan=_konstanta("SARAN_KIRIM_ULANG"),
    )
    assert teks.startswith("Kirim Ulang line-1 gagal pukul 28/09/2026 14:05:09: Line 1 ")
    assert teks.endswith(_kamus("id")[saran])
    assert "kode" not in teks
    _tanpa_mentah(teks)


@butuh_node
def test_gagal_kirim_ulang_kode_asing_tidak_menunjuk_tab_log_dua_kali():
    kamus = _kamus("id")
    teks = jalankan(
        ["kodeDikenal", "saranUmum", "alasan", "waktu", "pesanGagalKirimUlang"],
        f"pesanGagalKirimUlang({json.dumps({'message': MENTAH})}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        tambahan=_konstanta("SARAN_KIRIM_ULANG"),
    )
    assert teks == f"Kirim Ulang line-1 gagal pukul 28/09/2026 14:05:09: {kamus['err_umum']}."
    assert kamus["saranBukaLog"] not in teks


def _konstanta(nama: str) -> str:
    return re.search(rf"^const {nama} = .*?;$", HTML, re.M).group(0)


@butuh_node
@pytest.mark.parametrize("kode", ["rekam_keadaan_berubah", "rekam_disk_mepet", "rekam_ditolak"])
def test_kode_penolakan_rekam_diterjemahkan(kode):
    """routes/console.py `_REKAM_TOLAK` codes: their sentences sat in KAMUS without the
    `err_` prefix, so the screen showed the line's raw answer instead (found 2026-10-01)."""
    e = {"kode": kode, "message": "line-1 409 {\"detail\":\"sudah merekam\"}", "params": {}}
    teks = jalankan(["kodeDikenal", "saranUmum", "alasan"], f"alasan({json.dumps(e)}, 'gagalRekam')")
    assert teks == _kamus("id")[f"err_{kode}"]



# ── fix wave 2026-10-01 ─────────────────────────────────────────────────


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_alasan_model_dari_kode_bukan_teks_server(bahasa):
    kamus = _kamus(bahasa)
    m = {"berkas": "a$b.pt", "cocok": False, "alasan": "nama berkas: a$b.pt: nama memuat karakter",
         "alasan_kode": [{"kode": "kelas_asing", "kelas": "ACC, REJ"}, {"kode": "kelas_hilang", "kelas": "Ripe"}]}
    teks = jalankan(["alasanModel"], f"alasanModel({json.dumps(m)})", bahasa=bahasa)
    assert teks == (kamus["modelAlasan_kelas_asing"].replace("{kelas}", "ACC, REJ") + "; "
                    + kamus["modelAlasan_kelas_hilang"].replace("{kelas}", "Ripe"))
    for kode, harap in (([{"kode": "nama_tak_sah"}]), "modelAlasan_nama_tak_sah"), (([{"kode": "kode_baru"}]), "modelAlasan_lain"), (([]), "modelAlasan_lain"):
        teks = jalankan(["alasanModel"], f"alasanModel({json.dumps({**m, 'alasan_kode': kode})})", bahasa=bahasa)
        assert teks == kamus[harap], teks
        assert "nama memuat karakter" not in teks and "$" not in teks


def test_layar_model_tidak_membaca_alasan_mentah():
    for nama in ("opsiModel", "rinciModel", "barisModel"):
        fn = fungsi(nama)
        assert "m.alasan" not in fn.replace("m.alasan_kode", ""), nama
        assert "alasanModel(m)" in fn, nama


def _jalankan_api_status(status: int, gagal: str, bahasa: str = "id") -> str:
    skrip = "\n".join([
        kamus_asli(), esc_asli(), f"let bahasa = {json.dumps(bahasa)};",
        "const t = (k) => KAMUS[bahasa][k] ?? k;",
        'const lokal = () => (bahasa === "id" ? "id-ID" : "en-GB");',
        "const $ = () => ({ hidden: true }); const LANE_GERBANG = new Set(); function bukaGerbang() {}",
        f"globalThis.fetch = async () => ({{ ok: false, status: {status}, json: async () => ({{ detail: 'conf_threshold harus antara 0 dan 1' }}) }});",
        fungsi("ambil"), fungsi("galatJawaban"), fungsi("api"), fungsi("kodeDikenal"), fungsi("saranUmum"), fungsi("alasan"),
        f"(async () => {{ try {{ await api('/x'); }} catch (e) {{ console.log(JSON.stringify(alasan(e, {json.dumps(gagal)}))); }} }})();",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_penolakan_4xx_tanpa_kode_kalimatnya_sendiri(bahasa):
    """Fix wave ruling: an uncoded 400 (Setelan, Sumber Kamera, Model, Rekam setelan) is a
    refused value, not "try once more"; 5xx keeps err_umum."""
    kamus = _kamus(bahasa)
    assert _jalankan_api_status(400, "gagalSetelan", bahasa) == f"{kamus['gagalSetelan']}. {kamus['err_ditolak']}"
    assert _jalankan_api_status(500, "gagalSetelan", bahasa) == f"{kamus['gagalSetelan']}. {kamus['err_umum']}"


def test_setelan_dan_rekam_setelan_menyebut_konteksnya():
    simpan = HTML.split('$("set-simpan").addEventListener("click"', 1)[1].split("\n}));", 1)[0]
    assert 'alasan(e, "gagalSetelan")' in simpan
    assert 'alasan(e, "gagalSetelanMuat")' in fungsi("muatSetelan")
    rekam = HTML.split('$("rekam-simpan").addEventListener("click"', 1)[1].split("\n}));", 1)[0]
    assert 'alasan(e, "gagalRekamSetelan")' in rekam
    # Start/stop is a command, not loading the status (re-review C).
    perintah = HTML.split('$("rekam-baris").addEventListener("click"', 1)[1].split("\n});", 1)[0]
    assert 'alasan(e, "gagalRekamPerintah")' in perintah
    for bahasa in ("id", "en"):
        assert "gagalRekamPerintah" in _kamus(bahasa)


@butuh_node
def test_kirim_ulang_kode_asing_tidak_menulis_gagal_dua_kali():
    teks = jalankan(
        ["kodeDikenal", "alasan", "saranUmum", "waktu", "pesanGagalKirimUlang"],
        f"pesanGagalKirimUlang({json.dumps({'message': MENTAH})}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        tambahan=_konstanta("SARAN_KIRIM_ULANG"),
    )
    assert teks.lower().count("gagal") == 2, teks   # "Kirim Ulang ... gagal" + "kalau tetap gagal"
    assert ": Gagal." not in teks


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kirim_ulang_kunci_ditolak_tidak_menyuruh_panggil_teknisi_dua_kali(bahasa):
    e = {"kode": "line_menolak", "params": {"line": "Line 1", "status": 401}, "message": MENTAH}
    teks = jalankan(
        ["kodeDikenal", "alasan", "saranUmum", "waktu", "pesanGagalKirimUlang"],
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        bahasa=bahasa, tambahan=_konstanta("SARAN_KIRIM_ULANG"),
    )
    panggil = "panggil teknisi" if bahasa == "id" else "call a technician"
    assert teks.lower().count(panggil) == 1, teks


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_alarm_plc_asing_kalimat_umum_bukan_kunci_mentah(bahasa):
    skrip_alarm = (
        "const el = { hidden: true, innerHTML: '', textContent: '' }; const $ = () => el;"
    )
    hasil = jalankan(
        ["gabungAlarm", "gambarPitaAlarm"],
        "(gambarPitaAlarm([{ plc: { alarms: [{ code: 'kode_baru' }, { code: 'estop' }] } }]), el.innerHTML)",
        bahasa=bahasa, tambahan=skrip_alarm,
    )
    kamus = _kamus(bahasa)
    assert "alarm_kode_baru" not in hasil
    assert _esc(kamus["alarm_lain"]) in hasil and _esc(kamus["alarm_estop"]) in hasil



def test_unduh_riwayat_memakai_galat_yang_sama_dengan_api():
    """Re-review B: the CSV download built its error by hand and lost `status`."""
    assert "galatJawaban(res)" in fungsi("unduhRiwayat")
    assert "galatJawaban(res)" in fungsi("api")


@butuh_node
def test_422_tanpa_kode_dari_unduhan_jadi_nilai_ditolak():
    jawab = "({ status: 422, json: async () => ({ detail: 'rentang aneh' }) })"
    skrip = "\n".join([
        kamus_asli(), 'let bahasa = "id";', "const t = (k) => KAMUS[bahasa][k] ?? k;",
        'const lokal = () => "id-ID"; function bukaGerbang() {}',
        fungsi("galatJawaban"), fungsi("kodeDikenal"), fungsi("saranUmum"), fungsi("alasan"),
        f"(async () => {{ const e = await galatJawaban({jawab}); console.log(JSON.stringify(alasan(e, 'riwayatGagal'))); }})();",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    kamus = _kamus("id")
    assert json.loads(hasil.stdout) == f"{kamus['riwayatGagal']}. {kamus['err_ditolak']}"
