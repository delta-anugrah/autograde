"""Tanda "line sedang dinyalakan ulang" di kotak kamera kartu line.

Permintaan user 2026-09-29: sesudah Simpan & Restart (Sumber Kamera, Model
Deteksi) atau Danger Zone, kotak kamera line yang restart diberi spinner dan
bar berjalan, hilang sendiri begitu line mengirim gambar lagi, dan videonya
kembali TANPA memuat ulang halaman. Lewat 60 detik, spinner diganti pesan rinci
(kode, line, jam, saran).

Permintaan operator 2026-09-29 (lanjutan): selama spinner tampil, "Kamera tidak
tersambung" tidak ikut tampil, dan hitungan detik diganti bar berjalan.

Dua lapis seperti `test_console_html_ai_mati.py`: invarian teks (selalu jalan)
dan perilaku lewat node dengan KAMUS asli (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, konstanta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

MULAI = 1_790_000_000_000  # ms; 21.13 WIB
KONSTANTA = ("RESTART_BATAS_MS", "RESTART_HAPUS_BATAS_MS", "RESTART_PASTI_MATI_MS",
             "RESTART_ULANG_FEED_MS")
BATAS_HAPUS = 600_000


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _js(nilai) -> str:
    return json.dumps(nilai)


def _tanda(**isi) -> str:
    dasar = {"mulai": MULAI, "turunPada": None, "batasMs": 60_000, "hapus": False}
    return _js({**dasar, **isi})


def _jalan(fungsi_dipakai, ekspresi, **kw):
    # "\n": the last constant line can end in a `//` comment that would swallow `tambahan`.
    return jalankan(list(fungsi_dipakai), ekspresi, tambahan=konstanta(*KONSTANTA) + "\n" + kw.pop("tambahan", ""), **kw)


# ── line mana yang ditandai: dari jawaban SERVER, bukan dari klik ──────────


@butuh_node
def test_sumber_dan_model_menandai_line_yang_direstart_saja():
    """Bentuk jawaban Sumber Kamera dan Model Deteksi (`_restart_yang_berubah`):
    line yang tidak berubah dan line yang tidak menjawab restart tidak ditandai."""
    jawaban = {"lines": [
        {"line_code": "line-1", "direstart": True, "berubah": True},
        {"line_code": "line-2", "direstart": False, "berubah": False},
        {"line_code": "line-3", "direstart": False, "berubah": True, "alasan": "mati"},
    ], "video": [], "foto": []}
    assert _jalan(["lineDirestart"], f"lineDirestart({_js(jawaban)})") == ["line-1"]


@butuh_node
def test_danger_zone_menandai_line_yang_menerima():
    """Restart semua line (`ok`) dan hapus data (`ok`, termasuk `belum_mati`:
    diterima, line itu tetap restart). Line yang menolak tidak ditandai: toast
    gagalnya sudah menyebutnya."""
    restart = {"lines": [
        {"line_code": "line-1", "ok": True},
        {"line_code": "line-2", "ok": False, "alasan": "line-2 mati"},
        {"line_code": "line-3", "ok": True},
    ]}
    hapus = {"mode": "transaksi", "konsol": {}, "lines": [
        {"line_code": "line-1", "ok": False, "kode": "lisensi"},
        {"line_code": "line-2", "ok": True, "kode": "belum_mati"},
        {"line_code": "line-3", "ok": True},
    ]}
    assert _jalan(["lineDirestart"], f"lineDirestart({_js(restart)})") == ["line-1", "line-3"]
    assert _jalan(["lineDirestart"], f"lineDirestart({_js(hapus)})") == ["line-2", "line-3"]


@butuh_node
def test_jawaban_tanpa_daftar_line_tidak_menandai_apa_pun():
    for jawaban in ("undefined", "null", "{}", '{"lines": null}', '{"sesi_dihapus": 3}'):
        assert _jalan(["lineDirestart"], f"lineDirestart({jawaban})") == [], jawaban


def test_ketiga_aksi_restart_menandai_dari_jawaban_server():
    sumber = HTML.split('$("sumber-simpan").addEventListener("click"', 1)[1].split("\n}));", 1)[0]
    assert "tandaiRestart(lineDirestart(data))" in sumber
    model = HTML.split('$("model-modal-jalankan").addEventListener("click"', 1)[1].split("\n}));", 1)[0]
    assert "tandaiRestart(lineDirestart(data))" in model
    bahaya = fungsi("jalankanBahaya")
    assert "BAHAYA_RESTART.has(aksi)" in bahaya
    assert "tandaiRestart(lineDirestart(hasil)," in bahaya


def test_hapus_rekaman_dan_logout_tidak_merestart_line():
    """`hapus-rekaman` juga menjawab `ok` per line, tapi line tidak restart."""
    baris = HTML.split("const BAHAYA_RESTART = ", 1)[1].split("\n", 1)[0]
    assert '"restart"' in baris and '"transaksi"' in baris and '"semua"' in baris
    assert '"rekaman"' not in baris and '"logout"' not in baris


# ── kapan line dianggap sudah kembali ────────────────────────────────────


@butuh_node
def test_probe_ditolak_berarti_line_mati_seketika():
    hasil = _jalan(["catatProbe"], f"(() => {{ const m = {_tanda()}; catatProbe(m, 'mati', {MULAI + 2000}); return m; }})()")
    assert hasil["turunPada"] == MULAI + 2000


@butuh_node
def test_probe_lewat_tenggat_tidak_pernah_berarti_mati():
    """Lewat tenggat = line sibuk (misalnya menguras antrean simpan), bukan mati:
    proses lama yang masih menutup bisa menjawab "hidup" sesudahnya, dan gambar
    darinya tidak boleh menghapus tanda. Proses yang macet ditangani batas
    `RESTART_PASTI_MATI_MS`."""
    for n in (1, 2, 5):
        panggil = " ".join(f"catatProbe(m, 'diam', {MULAI + 1000 * (i + 1)});" for i in range(n))
        hasil = _jalan(["catatProbe"], f"(() => {{ const m = {_tanda()}; {panggil} return m; }})()")
        assert hasil["turunPada"] is None, n
    hidup = _jalan(["catatProbe"], (
        f"(() => {{ const m = {_tanda()}; catatProbe(m, 'diam', {MULAI + 1000});"
        f" catatProbe(m, 'diam', {MULAI + 2000}); catatProbe(m, 'hidup', {MULAI + 3000}); return m; }})()"))
    assert hidup["turunPada"] is None


@butuh_node
def test_turun_pertama_yang_dicatat_tidak_ditimpa():
    hasil = _jalan(["catatProbe"], (
        f"(() => {{ const m = {_tanda()}; catatProbe(m, 'mati', {MULAI + 2000});"
        f" catatProbe(m, 'mati', {MULAI + 5000}); return m; }})()"))
    assert hasil["turunPada"] == MULAI + 2000


@butuh_node
def test_gambar_dari_stream_yang_diminta_sebelum_line_mati_tidak_menghapus_tanda():
    """Stream yang diminta sebelum line terlihat mati bisa saja dilayani proses
    LAMA: gambarnya bukan bukti line sudah kembali."""
    fn = ["batasBuktiRestart", "restartSelesai"]
    turun = _tanda(turunPada=MULAI + 4000)
    assert _jalan(fn, f"restartSelesai({turun}, {MULAI + 3000}, 1280)") is False
    assert _jalan(fn, f"restartSelesai({turun}, {MULAI + 4000}, 1280)") is True
    assert _jalan(fn, f"restartSelesai({turun}, {MULAI + 9000}, 1280)") is True


@butuh_node
def test_line_yang_tidak_terlihat_mati_dianggap_kembali_sesudah_proses_lama_pasti_keluar():
    """Restart kilat di antara dua probe: proses lama pasti sudah keluar
    `RESTART_PASTI_MATI_MS` sesudah ditandai (line keluar maks 10 detik sesudah menjawab)."""
    fn = ["batasBuktiRestart", "restartSelesai"]
    m = _tanda()
    batas = _jalan(fn, "RESTART_PASTI_MATI_MS")
    assert _jalan(fn, f"restartSelesai({m}, {MULAI + batas - 1}, 1280)") is False
    assert _jalan(fn, f"restartSelesai({m}, {MULAI + batas}, 1280)") is True


@butuh_node
def test_stream_tanpa_gambar_atau_tanpa_cap_waktu_bukan_bukti():
    fn = ["batasBuktiRestart", "restartSelesai"]
    turun = _tanda(turunPada=MULAI + 4000)
    assert _jalan(fn, f"restartSelesai({turun}, {MULAI + 5000}, 0)") is False
    # src dari render pertama halaman: tidak pernah diminta ulang sesudah tanda.
    assert _jalan(fn, f"restartSelesai({turun}, undefined, 1280)") is False


@butuh_node
def test_gambar_yang_datang_menghapus_tanda_dan_kotaknya():
    stub = """
const restartLine = {};
const digambar = [];
const gambarRestart = (kartu, m) => digambar.push([kartu.dataset.line, m]);
const kartu = { dataset: { line: "line-2" } };
"""
    fn = ["batasBuktiRestart", "restartSelesai", "selesaikanRestart"]
    lama = _jalan(fn, (
        f"(() => {{ restartLine['line-2'] = {_tanda(turunPada=MULAI + 4000)};"
        f" const img = {{ _dimintaPada: {MULAI + 1000}, naturalWidth: 1280 }};"
        f" const r = selesaikanRestart(kartu, img, {MULAI + 6000});"
        " return [r, Object.keys(restartLine), digambar]; })()"), tambahan=stub)
    assert lama == [False, ["line-2"], []]
    baru = _jalan(fn, (
        f"(() => {{ restartLine['line-2'] = {_tanda(turunPada=MULAI + 4000)};"
        f" const img = {{ _dimintaPada: {MULAI + 5000}, naturalWidth: 1280 }};"
        f" const r = selesaikanRestart(kartu, img, {MULAI + 6000});"
        " return [r, Object.keys(restartLine), digambar]; })()"), tambahan=stub)
    assert baru == [True, [], [["line-2", None]]]


@butuh_node
def test_line_tanpa_tanda_tidak_disentuh_saat_gambar_datang():
    stub = """
const restartLine = {};
const digambar = [];
const gambarRestart = () => digambar.push(1);
"""
    hasil = _jalan(["batasBuktiRestart", "restartSelesai", "selesaikanRestart"], (
        f"[selesaikanRestart({{ dataset: {{ line: 'line-1' }} }},"
        f" {{ _dimintaPada: {MULAI}, naturalWidth: 640 }}, {MULAI}), digambar.length]"), tambahan=stub)
    assert hasil == [False, 0]


def test_listener_load_kartu_lewat_feed_memuat():
    blok = HTML.split('$("lines").addEventListener("load"', 1)[1].split(", true);", 1)[0]
    assert "feedMemuat(ev.target)" in blok


@butuh_node
def test_load_tanpa_gambar_tidak_menghapus_offline():
    """Firefox menembakkan `load` juga untuk keep-alive kosong line tanpa kamera
    (naturalWidth 0): tanpa penjaga, kartu berkedip antara "Kamera tidak
    tersambung" dan kotak hitam."""
    stub = """
const dilepas = [];
const diselesaikan = [];
const selesaikanRestart = (kartu, img) => diselesaikan.push(img.naturalWidth);
const buatImg = (lebar) => ({ naturalWidth: lebar, closest: () => ({
  classList: { remove: (k) => dilepas.push([lebar, k]) } }) });
"""
    hasil = _jalan(["feedMemuat"], (
        "(feedMemuat(buatImg(0)), feedMemuat(buatImg(1280)), [dilepas, diselesaikan])"), tambahan=stub)
    assert hasil == [[[1280, "putus"]], [1280]]


# ── render ulang kartu (ganti bahasa, daftar truk, login) ─────────────────


@butuh_node
def test_img_baru_dari_render_ulang_dicap_dan_frame_segarnya_menghapus_tanda():
    """Render ulang membuat `<img>` baru = permintaan stream baru saat itu juga.
    Tanpa cap waktu, gambarnya tidak pernah dihitung bukti: sesudah 60 detik
    pengulangan berhenti, cekKamera diam karena gambar tampil, dan kotak merah
    RESTART_LAMA menempel di atas video yang sehat sampai halaman dimuat ulang."""
    stub = f"""
const restartLine = {{ "line-2": {_tanda(turunPada=MULAI + 4000)} }};
const digambar = [];
const gambarSemuaRestart = (t) => digambar.push(t);
const gambarRestart = (kartu, m) => digambar.push(m);
const img = {{ naturalWidth: 0 }};
const $ = () => ({{ querySelectorAll: (sel) => (sel === ".feed img" ? [img] : []) }});
const kartu = {{ dataset: {{ line: "line-2" }} }};
"""
    fn = ["capFeedBaru", "batasBuktiRestart", "restartSelesai", "selesaikanRestart"]
    hasil = _jalan(fn, (
        f"(() => {{ capFeedBaru({MULAI + 90_000}); const cap = img._dimintaPada;"
        f" img.naturalWidth = 1280; const r = selesaikanRestart(kartu, img, {MULAI + 91_000});"
        " return [cap, digambar[0], r, Object.keys(restartLine)]; })()"), tambahan=stub)
    assert hasil == [MULAI + 90_000, MULAI + 90_000, True, []]


def test_render_ulang_kartu_langsung_mencap_feed_dan_menggambar_tanda():
    """URL feed dan capnya memakai SATU jam render: satu permintaan per render,
    dan cap itu persis milik permintaan tersebut."""
    fn = fungsi("refresh")
    assert "const dipasangPada = Date.now();" in fn
    blok = fn.split('$("lines").innerHTML = s.lines.map((l) => kartuLine(l, dipasangPada)).join("");', 1)[1]
    assert blok.lstrip().startswith("capFeedBaru(dipasangPada);")


# ── B-1: tiap render = permintaan stream yang sungguhan ──────────────────

KARTU_STUB = """
const location = { protocol: "http:", hostname: "10.0.0.5" };
const trucks = [];
const komponenPilih = () => "";
const pitaPiston = () => "";
const pitaKunciDitolak = () => "";
const pitaAi = () => "";
const aiMati = () => false;
const frameBerhenti = () => false;
const isiTruk = () => "";
const tombolPiston = () => "";
const tombolSambungUlang = () => "";
const tombolLepas = () => "";
"""


@butuh_node
def test_url_feed_kartu_selalu_membawa_t_unik_per_render():
    """URL telanjang yang sama dengan render sebelumnya dilayani browser dari
    daftar gambar di memori (Chrome 154 dan Firefox 155, diuji reviewer):
    tidak ada permintaan ke line, `load` datang dalam 2 ms dengan frame LAMA.
    Akibatnya cap render menghapus tanda walau line masih mati, dan stream yang
    sudah putus tidak pernah tersambung lagi sesudah ganti bahasa/daftar truk/login."""
    fn = ["urlFeedBaru", "kartuLine"]
    hasil = _jalan(fn, (
        "[kartuLine({ line_code: 'line-2', name: 'Line 2', port: 8002 }, 111),"
        " kartuLine({ line_code: 'line-2', name: 'Line 2', port: 8002 }, 222)]"), tambahan=KARTU_STUB)
    assert 'src="http://10.0.0.5:8002/api/video_feed?t=111"' in hasil[0]
    assert 'src="http://10.0.0.5:8002/api/video_feed?t=222"' in hasil[1]
    assert "/api/video_feed\"" not in hasil[0] and '/api/video_feed"' not in hasil[0]


def test_kartu_line_membangun_url_lewat_url_feed_baru():
    kartu = fungsi("kartuLine")
    assert kartu.startswith("function kartuLine(l, sekarang = Date.now())")
    assert "urlFeedBaru(" in kartu
    # capFeedBaru cuma mencap: meminta ulang di situ berarti dua permintaan per render.
    assert "mintaUlangFeed(" not in fungsi("capFeedBaru")


def test_komentar_reconnect_once_yang_salah_dicabut():
    assert "reconnect once" not in HTML


# ── video kembali tanpa memuat ulang halaman ─────────────────────────────


@butuh_node
def test_url_feed_baru_memaksa_browser_meminta_ulang():
    url = _jalan(["urlFeedBaru"], "urlFeedBaru('http://10.0.0.5:8002/api/video_feed?t=11', 42)")
    assert url == "http://10.0.0.5:8002/api/video_feed?t=42"
    url = _jalan(["urlFeedBaru"], "urlFeedBaru('http://10.0.0.5:8002/api/video_feed', 7)")
    assert url == "http://10.0.0.5:8002/api/video_feed?t=7"


@butuh_node
def test_stream_diminta_ulang_begitu_line_menjawab_lagi():
    fn = ["batasBuktiRestart", "perluMintaUlangFeed"]
    m = _tanda(turunPada=MULAI + 4000)
    # Belum menjawab: meminta stream ke line yang mati cuma membuka koneksi gagal.
    assert _jalan(fn, f"perluMintaUlangFeed({m}, undefined, false, {MULAI + 6000})") is False
    # Menjawab lagi, stream terakhir diminta sebelum line mati.
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {MULAI + 1000}, true, {MULAI + 6000})") is True
    # Tanpa cap waktu sama sekali (src render pertama).
    assert _jalan(fn, f"perluMintaUlangFeed({m}, undefined, true, {MULAI + 6000})") is True


@butuh_node
def test_minta_ulang_dibatasi_jaraknya_dan_berhenti_sesudah_60_detik():
    fn = ["batasBuktiRestart", "perluMintaUlangFeed"]
    m = _tanda(turunPada=MULAI + 4000)
    jarak = _jalan(fn, "RESTART_ULANG_FEED_MS")
    batas = _jalan(fn, "RESTART_BATAS_MS")
    diminta = MULAI + 6000
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {diminta}, true, {diminta + jarak - 1})") is False
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {diminta}, true, {diminta + jarak})") is True
    # Lewat 60 detik: pengulangan cepat berhenti, cekKamera (5 detik) yang meneruskan.
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {diminta}, true, {MULAI + batas + 1})") is False


@butuh_node
def test_line_yang_belum_terlihat_mati_tidak_diminta_ulang_terlalu_cepat():
    """Sebelum bukti proses lama hilang, stream baru bisa saja dilayani proses lama."""
    fn = ["batasBuktiRestart", "perluMintaUlangFeed"]
    batas = _jalan(fn, "RESTART_PASTI_MATI_MS")
    m = _tanda()
    assert _jalan(fn, f"perluMintaUlangFeed({m}, undefined, true, {MULAI + batas - 1})") is False
    assert _jalan(fn, f"perluMintaUlangFeed({m}, undefined, true, {MULAI + batas})") is True


def test_cek_kamera_dan_restart_memakai_satu_cara_minta_ulang():
    """Dua jalur yang meminta ulang stream sama-sama mencap waktunya: tanpa cap
    itu gambar dari stream baru tidak bisa dibedakan dari proses lama."""
    assert "mintaUlangFeed(img" in fungsi("cekKamera")
    minta = fungsi("mintaUlangFeed")
    assert "urlFeedBaru(" in minta and "_dimintaPada" in minta
    pantau = fungsi("pantauRestart")
    assert "perluMintaUlangFeed(" in pantau and "mintaUlangFeed(" in pantau
    assert "catatProbe(" in pantau


@butuh_node
def test_tanda_line_tanpa_kartu_dibuang():
    stub = f"""
const restartLine = {{ "line-9": {_tanda()} }};
const kartuLineDariKode = () => null;
const gambarSemuaRestart = () => {{}};
const probeLine = async () => "hidup";
let restartSibuk = false;
"""
    assert _jalan(["pantauRestart"], "(pantauRestart(), Object.keys(restartLine))", tambahan=stub) == []


def test_pemantau_restart_jalan_tiap_detik():
    assert "setInterval(pantauRestart, 1000)" in HTML


# ── yang dilihat di kotak kamera ─────────────────────────────────────────


@butuh_node
@pytest.mark.parametrize("bahasa,judul,detik", [
    ("id", "Line 2 sedang dinyalakan ulang", "12 detik"),
    ("en", "Line 2 is restarting", "12 s"),
])
def test_kotak_kamera_selama_restart(bahasa, judul, detik):
    """Spinner + judul + bar berjalan. Tidak ada hitungan detik lagi (permintaan
    operator 2026-09-29: "loadingnya jangan pake second")."""
    fn = ["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart"]
    html = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 12_400})", bahasa=bahasa)
    assert judul in html
    assert 'class="restart-putar"' in html
    assert 'class="restart-bar"' in html
    assert html.index("<b>") < html.index('class="restart-bar"'), "bar di bawah judul"
    assert "data-restart-detik" not in html
    assert detik not in html
    assert "RESTART_LAMA" not in html


def test_hitungan_detik_dicabut():
    assert "teksDetikRestart" not in HTML
    assert "data-restart-detik" not in HTML


@butuh_node
@pytest.mark.parametrize("bahasa,potongan", [
    ("id", ["Line 2 belum kembali", "Restart diminta pukul 21.13", "lewat 60 detik",
            "Cek tab Log dan terminal line itu"]),
    ("en", ["Line 2 has not come back", "Restart requested at 21:13", "After 60 s",
            "Check the Log tab and that line's terminal"]),
])
def test_lewat_60_detik_spinner_diganti_pesan_rinci(bahasa, potongan):
    fn = ["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart"]
    html = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 61_000})", bahasa=bahasa)
    for p in potongan:
        assert p in html.replace("&#39;", "'"), (p, html)
    assert "restart-putar" not in html
    assert "restart-bar" not in html
    assert "data-restart-detik" not in html
    assert 'role="alert"' in html
    # Line, jam, dan tindakan; tanpa kode galat (keputusan user 2026-10-01).
    assert "RESTART_LAMA" not in html


@butuh_node
def test_isi_kotak_tidak_berubah_tiap_detik_supaya_spinner_tidak_tersentak():
    """Isi kotak sama sepanjang keadaannya sama. Kalau berubah tiap detik,
    `tulisKalauBeda` menulis ulang spinner dan bar tiap detik dan putarannya
    mulai dari awal lagi."""
    fn = ["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart"]
    a = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 3000})")
    b = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 9000})")
    assert a == b
    c = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 70_000})")
    d = _jalan(fn, f"isiRestart('Line 2', {_tanda()}, {MULAI + 95_000})")
    assert c == d


@butuh_node
def test_nama_line_di_escape():
    html = _jalan(["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart"],
                  f"isiRestart('<b>x</b>', {_tanda()}, {MULAI})")
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_kotak_digambar_lewat_tulis_kalau_beda():
    fn = fungsi("gambarRestart")
    assert "tulisKalauBeda(slot, isiRestart(" in fn
    assert "innerHTML" not in fn


# ── "Kamera tidak tersambung" tidak ikut tampil selama spinner ────────────

KARTU_KELAS = """
const slot = { _terakhirDitulis: undefined, innerHTML: "" };
const kelas = new Set();
const kartu = {
  dataset: { line: "line-2" },
  classList: {
    add: (k) => kelas.add(k), remove: (k) => kelas.delete(k), contains: (k) => kelas.has(k),
    toggle: (k, on) => (on ? kelas.add(k) : kelas.delete(k), on),
  },
  querySelector: (sel) => (sel === ".slot-restart" ? slot : sel === ".nama" ? { textContent: "Line 2" } : null),
};
const tulisKalauBeda = (el, html) => { el._terakhirDitulis = html; el.innerHTML = html; };
"""
FN_GAMBAR = ["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart", "gambarRestart"]


@butuh_node
def test_selama_spinner_kartu_ditandai_sedang_restart_walau_kamera_putus():
    """cekKamera tetap menandai `putus` (line memang mati selama restart), tapi
    kartu juga ditandai `sedang-restart`, yang menyembunyikan tulisan itu."""
    hasil = _jalan(FN_GAMBAR, (
        f"(() => {{ kartu.classList.add('putus'); gambarRestart(kartu, {_tanda()}, {MULAI + 5000});"
        " return [...kelas].sort(); })()"), tambahan=KARTU_KELAS)
    assert hasil == ["putus", "sedang-restart"]


@pytest.mark.parametrize("opsi", [{}, {"batasMs": BATAS_HAPUS, "hapus": True}])
@butuh_node
def test_kotak_merah_dan_tanda_hilang_mengembalikan_tulisan_kamera_putus(opsi):
    """Lewat batas (kotak merah RESTART_LAMA) atau tanda dihapus (gambar datang):
    perilaku biasa kembali, jadi kamera yang benar-benar putus terbaca lagi."""
    m = _tanda(**opsi)
    batas = opsi.get("batasMs", 60_000)
    hasil = _jalan(FN_GAMBAR, (
        f"(() => {{ kartu.classList.add('putus'); const r = [];"
        f" gambarRestart(kartu, {m}, {MULAI + 1000}); r.push(kelas.has('sedang-restart'));"
        f" gambarRestart(kartu, {m}, {MULAI + batas}); r.push(kelas.has('sedang-restart'));"
        f" gambarRestart(kartu, {m}, {MULAI + 1000}); r.push(kelas.has('sedang-restart'));"
        f" gambarRestart(kartu, null, {MULAI + 2000}); r.push(kelas.has('sedang-restart'));"
        " r.push(kelas.has('putus')); return r; })()"), tambahan=KARTU_KELAS)
    assert hasil == [True, False, True, False, True]


def _css() -> str:
    return HTML.split("<style>", 1)[1].split("</style>", 1)[0]


def test_css_menyembunyikan_tulisan_kamera_putus_selama_restart():
    css = _css()
    aturan = re.search(r"\.card\.sedang-restart \.feed-putus\s*\{([^}]*)\}", css)
    assert aturan, "aturan .card.sedang-restart .feed-putus tidak ada"
    assert "display:none" in aturan.group(1).replace(" ", "")
    # Spesifisitasnya sama dengan `.card.putus .feed-putus`: yang menang yang belakangan.
    assert css.index(".card.putus .feed-putus") < aturan.start()


def test_kartu_line_punya_slot_restart_di_dalam_kotak_kamera():
    kartu = fungsi("kartuLine")
    feed = kartu.split('<div class="feed">', 1)[1].split("</div>", 1)[0]
    assert '<div class="slot-restart">' in kartu
    assert kartu.index('<div class="slot-restart">') > kartu.index('<div class="feed">')
    assert "<img" in feed


def test_tanda_tidak_bergantung_peran():
    """Operator yang menonton kotak kamera juga harus melihatnya."""
    for nama in ("tandaiRestart", "gambarRestart", "pantauRestart", "selesaikanRestart"):
        isi = fungsi(nama)
        assert "support" not in isi and "role" not in isi, nama


def test_spinner_css_murni_tanpa_gambar():
    css = _css()
    blok = css.split(".restart-putar", 1)[1].split("}", 1)[0]
    assert "animation:" in blok and "url(" not in blok
    assert ".feed .restart-kotak" in css


def test_bar_berjalan_css_murni_dan_ikut_reduced_motion():
    css = _css()
    bar = re.search(r"\.restart-bar::before\s*\{([^}]*)\}", css)
    assert bar, ".restart-bar::before tidak ada"
    assert "animation:" in bar.group(1) and "url(" not in bar.group(1)
    nama = re.search(r"animation:\s*([\w-]+)", bar.group(1)).group(1)
    assert f"@keyframes {nama}" in css
    # Gerak dimatikan untuk yang memintanya: aturan global mematikan semua animasi,
    # dan bar diam dibuat penuh supaya tidak terbaca "40% selesai".
    assert "@media (prefers-reduced-motion:reduce) { *, *::before, *::after { animation:none !important;" in css
    assert re.search(
        r"@media \(prefers-reduced-motion:reduce\)\s*\{\s*\.restart-bar::before\s*\{[^}]*width:100%", css
    ), "bar diam untuk reduced-motion tidak ada"


def test_kunci_kamus_ada_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("restartJudul", "restartHapusJudul", "restartDetik", "restartMenit",
                      "restartLamaJudul", "restartLamaRinci"):
            assert f"{kunci}:" in isi, (bahasa, kunci)


# ── hapus data: line menghapus foto saat boot, bisa bermenit-menit ────────


@butuh_node
def test_tanda_membawa_batasnya_sendiri():
    stub = "const restartLine = {}; const gambarSemuaRestart = () => {};"
    hasil = _jalan(["tandaiRestart"], (
        f"(tandaiRestart(['line-1'], {{}}, {MULAI}),"
        f" tandaiRestart(['line-2'], {{ batasMs: RESTART_HAPUS_BATAS_MS, hapus: true }}, {MULAI}),"
        " restartLine)"), tambahan=stub)
    assert hasil["line-1"] == {"mulai": MULAI, "turunPada": None, "batasMs": 60_000, "hapus": False}
    assert hasil["line-2"] == {"mulai": MULAI, "turunPada": None, "batasMs": BATAS_HAPUS, "hapus": True}


def test_hapus_data_ditandai_dengan_batas_sepuluh_menit():
    assert "const RESTART_HAPUS_BATAS_MS = 600000;" in HTML
    bahaya = fungsi("jalankanBahaya")
    assert 'tandaiRestart(lineDirestart(hasil), aksi === "restart" ? {} : RESTART_HAPUS)' in bahaya


@butuh_node
@pytest.mark.parametrize("bahasa,judul,lama", [
    ("id", "Line 2 sedang menghapus data lalu dinyalakan ulang", "lewat 10 menit"),
    ("en", "Line 2 is deleting its data, then restarting", "After 10 min"),
])
def test_hapus_data_tetap_spinner_sampai_sepuluh_menit(bahasa, judul, lama):
    fn = ["jamSinkron", "restartMasihDitunggu", "isiRestart", "teksBatasRestart"]
    m = _tanda(batasMs=BATAS_HAPUS, hapus=True)
    lima_menit = _jalan(fn, f"isiRestart('Line 2', {m}, {MULAI + 300_000})", bahasa=bahasa)
    assert judul in lima_menit and "restart-putar" in lima_menit
    habis = _jalan(fn, f"isiRestart('Line 2', {m}, {MULAI + BATAS_HAPUS})", bahasa=bahasa)
    assert "restart-kotak lama" in habis and lama in habis, habis
    assert "RESTART_LAMA" not in habis


@butuh_node
def test_hapus_data_tetap_diminta_ulang_lewat_60_detik():
    fn = ["batasBuktiRestart", "perluMintaUlangFeed"]
    m = _tanda(turunPada=MULAI + 4000, batasMs=BATAS_HAPUS, hapus=True)
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {MULAI + 5000}, true, {MULAI + 300_000})") is True
    assert _jalan(fn, f"perluMintaUlangFeed({m}, {MULAI + 5000}, true, {MULAI + BATAS_HAPUS + 1})") is False


def test_kotak_restart_menutup_video_di_belakangnya_sepenuhnya():
    """Operator 2026-09-29: cuma layar loading, bukan frame lama yang tembus samar."""
    aturan = re.search(r"\.feed \.restart-kotak \{([^}]*)\}", HTML).group(1)
    assert "background:#000" in aturan.replace(" ", "")
    assert "rgba(" not in aturan
