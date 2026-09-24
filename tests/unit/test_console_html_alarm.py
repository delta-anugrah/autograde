"""Pita alarm PLC di console.html, dua lapis — pola yang sama dengan
`test_console_lama_proses.py`:

- **invarian teks**, selalu jalan (juga di CI tanpa node): pita ada di HTML,
  digambar tiap refresh, tiap kode alarm dari domain punya terjemahan di KEDUA
  bahasa. Satu kode tanpa terjemahan tampil sebagai kunci mentah "alarm_estop"
  di layar pabrik.
- **perilaku `gabungAlarm`**, dijalankan sungguhan lewat node kalau ada. Dedup
  adalah satu-satunya logika non-sepele di jalur ini dan rusaknya senyap:
  ketiga line membaca blok M yang SAMA, jadi tanpa dedup satu motor fault
  tampil tiga kali dan operator mengira ada tiga motor mati.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from palmgrade.domain.plc_alarm import ALARM_CODES

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_pita_alarm_ada_di_atas_kartu_line():
    assert HTML.index('id="pita-alarm"') < HTML.index('<div id="lines"></div>')


def test_pita_alarm_digambar_tiap_refresh():
    refresh = HTML.split("async function refresh() {", 1)[1].split("\n}\n", 1)[0]
    assert "gambarPitaAlarm(s.lines)" in refresh


def test_setiap_kode_alarm_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [c for c in ALARM_CODES if f"alarm_{c}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_pita_alarm_memakai_esc_bukan_innerhtml_mentah():
    fn = HTML.split("function gambarPitaAlarm(", 1)[1].split("\n}\n", 1)[0]
    assert "esc(" in fn


def test_kartu_uji_plc_tanpa_daftar_bit():
    """Daftar `M1100 MOTOR 1 = Off ...` di tiap kartu line dicabut (permintaan
    2026-09-24): tiga kartu memuat 16 baris yang sama persis, dan tabel alamat di
    bawah tombol sudah menyebut peran tiap M. Yang boleh hidup di kartu cuma
    tombol coil."""
    fn = HTML.split("function kartuPlc(", 1)[1].split("\n}\n", 1)[0]
    assert "data-plc-di" not in fn
    assert "data-plc-coil" in fn
    assert "function isiDiPlc(" not in HTML
    assert "function namaBitPlc(" not in HTML


# ── perilaku gabungAlarm: butuh node, skip di CI ───────────────────────────

NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


def _fungsi(nama: str) -> str:
    """Body of one top-level function, up to the first line that closes it."""
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _gabung(lines) -> list:
    """Jalankan `gabungAlarm` yang SUNGGUHAN dari console.html, bukan salinannya.

    Disalin ke test, fungsinya akan terus lulus setelah yang di layar diubah.
    """
    skrip = _fungsi("gabungAlarm") + f"\nconsole.log(JSON.stringify(gabungAlarm({json.dumps(lines)})));"
    keluaran = subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    return json.loads(keluaran)


@butuh_node
def test_alarm_yang_sama_dari_tiga_line_tampil_sekali():
    """Inti dedup. Ketiga line membaca blok M yang SAMA dari satu PLC, jadi
    MOTOR 3 fault muncul di ketiga jawaban. Tanpa dedup, operator membaca
    "MOTOR 3 FAULT MOTOR 3 FAULT MOTOR 3 FAULT" dan mengira tiga motor mati."""
    satu = {"plc": {"alarms": [{"code": "motor_fault", "n": 3}]}}
    assert _gabung([satu, satu, satu]) == [{"code": "motor_fault", "n": 3}]


@butuh_node
def test_motor_berbeda_tidak_ikut_didedup():
    # Kunci dedup memakai kode+nomor. Kalau cuma kode, MOTOR 5 hilang ditelan MOTOR 3.
    lines = [
        {"plc": {"alarms": [{"code": "motor_fault", "n": 3}]}},
        {"plc": {"alarms": [{"code": "motor_fault", "n": 5}]}},
    ]
    assert _gabung(lines) == [{"code": "motor_fault", "n": 3}, {"code": "motor_fault", "n": 5}]


@butuh_node
def test_estop_tanpa_nomor_tetap_terdedup():
    # `n` undefined - kunci dedup tidak boleh jadi "undefined" yang berbeda tiap kali.
    satu = {"plc": {"alarms": [{"code": "estop"}]}}
    assert _gabung([satu, satu]) == [{"code": "estop"}]


@butuh_node
def test_line_mati_dan_line_tanpa_plc_tidak_menyumbang_alarm():
    """`reachable:false` tidak punya `alarms`, dan line asing tidak punya `plc`
    sama sekali. Keduanya harus terbaca tenang, bukan melempar."""
    assert _gabung([{"plc": {"reachable": False}}, {}, {"plc": {"alarms": []}}]) == []


@butuh_node
def test_daftar_line_kosong_atau_null_aman():
    assert _gabung([]) == []
    skrip = _fungsi("gabungAlarm") + "\nconsole.log(JSON.stringify(gabungAlarm(null)));"
    keluar = subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    assert json.loads(keluar) == []


# ── tab Uji PLC ikut memuat ulang sendiri ───────────────────────────────────


def test_tab_uji_plc_punya_timer_muat_ulang():
    """Tanpa timer, `muatPlc()` cuma jalan sekali saat tab dibuka: bit motor
    dan E-stop di layar jadi foto lama sampai operator pindah tab dan kembali.
    Terbaca di pabrik sebagai "PLC-nya delay" (Lampung 2026-09-23), padahal
    PlcWorker sudah membaca blok M tiap 200 ms.
    """
    blok = HTML.split("function bukaTabDev(", 1)[1].split("\n}\n", 1)[0]
    assert "plcTimer = setInterval(segarkanPlc" in blok, "tab PLC tidak punya timer"
    assert "clearInterval(plcTimer)" in blok, "timer PLC tidak dihentikan saat pindah tab"


def test_timer_uji_plc_tidak_membangun_ulang_kartu():
    """Lampung 2026-09-24: tab PLC Test "berkedip". Sebabnya timer memanggil
    `muatPlc()` yang menulis ulang innerHTML seluruh kartu tiap detik: tombol
    kosong sampai jawaban /dev/plc datang, lalu muncul lagi. Timer harus lewat
    `segarkanPlc()`, yang tidak menyentuh `$("plc-kartu").innerHTML` selama daftar
    line-nya sama, dan hanya menulis isi kartu kalau berubah."""
    blok = HTML.split("function bukaTabDev(", 1)[1].split("\n}\n", 1)[0]
    assert "setInterval(muatPlc" not in blok
    segar = HTML.split("async function segarkanPlc(", 1)[1].split("\n}\n", 1)[0]
    assert '$("plc-kartu").innerHTML' not in segar
    assert "return muatPlc()" in segar, "daftar line berubah harus tetap membangun ulang"
    satu = HTML.split("async function muatPlcSatuLine(", 1)[1].split("\n}\n", 1)[0]
    assert "tulisKalauBeda(" in satu
    assert ".innerHTML =" not in satu
    # Pembandingnya string terakhir yang ditulis, BUKAN el.innerHTML: browser
    # menyerialkan ulang DOM sehingga innerHTML tak pernah sama dengan template
    # dan tombol tetap diganti tiap detik (terukur 15 kali / 5 detik).
    tulis = HTML.split("function tulisKalauBeda(", 1)[1].split("\n}\n", 1)[0]
    assert "el.innerHTML !==" not in tulis and "el.innerHTML ===" not in tulis
    assert "_terakhirDitulis" in tulis


def test_timer_uji_plc_lebih_rapat_dari_diagnostik():
    """Diagnostik 5 s karena isinya keadaan yang berubah pelan. Layar PLC dipakai
    saat commissioning sambil orang menekan tombol di panel — jeda 5 detik di situ
    terasa seperti sinyalnya tidak sampai."""
    blok = HTML.split("function bukaTabDev(", 1)[1].split("\n}\n", 1)[0]
    plc = int(re.search(r"plcTimer = setInterval\(segarkanPlc, (\d+)\)", blok).group(1))
    diag = int(re.search(r"diagnostikTimer = setInterval\(muatDiagnostik, (\d+)\)", blok).group(1))
    assert plc < diag, f"timer PLC ({plc} ms) tidak lebih rapat dari diagnostik ({diag} ms)"


# ── layar Uji PLC: nama jelas di tombol + tabel alamat ──────────────────────


def test_tombol_uji_coil_menyebut_peran_bukan_cuma_nomor():
    """"Test coil 1000" tidak mengatakan apa-apa ke orang yang memegang panel.
    Yang dibaca harus "CAMERA 1 OK" + alamat M-nya, supaya cocok dengan daftar
    yang dipegang tim PLC tanpa perlu membuka dokumen."""
    fn = HTML.split("function isiCoilPlc(", 1)[1].split("\n}\n", 1)[0]
    assert "peranCoil(" in fn, "tombol tidak memakai peranCoil()"
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("coilOk:", "coilNg:", "coilError:", "coilPiston:"):
            assert kunci in isi, f"KAMUS.{bahasa} tanpa {kunci}"


@butuh_node
def test_nomor_kamera_dari_KODE_LINE_bukan_dihitung_dari_alamat():
    """Nomor kamera datang dari `line-2`, bukan dari jarak base ke 1000.

    Menghitungnya dari alamat membuat label ikut salah begitu blok alamat
    bukan 1000-an — persis yang terjadi di konsol dev (base 0): ketiga line
    menulis "Camera 1". Kode line sudah ada di tangan konsol; tidak ada
    alasan menebaknya dari angka yang dimiliki panel.
    """
    fn = _fungsi("peranCoil")
    skrip = (
        "const KAMUS={id:{coilOk:'Kamera {n} OK',coilNg:'Kamera {n} NG',"
        "coilError:'Kamera {n} Error',coilPiston:'Piston manual'}};"
        "let bahasa='id'; const t=(k)=>KAMUS[bahasa][k] ?? k;\n" + fn +
        "\nconsole.log(JSON.stringify(["
        # alamat Lampung
        "peranCoil(1000,1000,'line-1'), peranCoil(1004,1003,'line-2'),"
        "peranCoil(1008,1006,'line-3'),"
        # base dev (0/3/6) — nomornya harus TETAP ikut kode line
        "peranCoil(0,0,'line-1'), peranCoil(4,3,'line-2'), peranCoil(8,6,'line-3'),"
        # line asing / piston
        "peranCoil(9,0,'line-1'), peranCoil(0,0,'mesin-aneh')]));"
    )
    hasil = json.loads(subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip())
    assert hasil == [
        "Kamera 1 OK", "Kamera 2 NG", "Kamera 3 Error",
        "Kamera 1 OK", "Kamera 2 NG", "Kamera 3 Error",
        "Piston manual", "Kamera 1 OK",
    ]


def test_tabel_alamat_ada_di_bawah_konfirmasi():
    # Referensi untuk developer/teknisi: seluruh peta M dalam satu layar.
    assert HTML.index('id="plc-peta"') > HTML.index('id="plc-konfirmasi"')
    for alamat in ("M1000", "M1009", "M1100", "M1111"):
        assert alamat in HTML, f"{alamat} tidak ada di tabel alamat"


def test_tabel_alamat_menyebut_arah_pc_dan_plc():
    peta = HTML.split('id="plc-peta"', 1)[1].split("</section>", 1)[0]
    assert "M1008" in peta and "M1110" in peta, "tabel alamat tidak lengkap"


# ── warna tombol: hijau OK, merah NG/Error ─────────────────────────────────


def test_tombol_ok_diberi_kelas_hijau_ng_dan_error_merah():
    """Warna dibaca lebih cepat daripada tulisan saat tangan sedang di panel.
    Kelasnya diturunkan dari OFFSET (base+0 = OK), bukan dari nomor alamat."""
    fn = HTML.split("function isiCoilPlc(", 1)[1].split("\n}\n", 1)[0]
    assert "kelasCoil(" in fn, "tombol tidak memakai kelasCoil()"
    assert ".uji-coil.ok" in HTML, "CSS untuk tombol OK (hijau) tidak ada"


@butuh_node
def test_kelas_warna_mengikuti_offset_bukan_nomor_alamat():
    fn = _fungsi("kelasCoil")
    skrip = fn + (
        "\nconsole.log(JSON.stringify(["
        # Lampung: 1000 OK, 1001 NG, 1002 ERROR
        "kelasCoil(1000,1000), kelasCoil(1001,1000), kelasCoil(1002,1000),"
        # camera 2: 1003 OK walau angkanya ganjil
        "kelasCoil(1003,1003), kelasCoil(1004,1003),"
        # base dev: 0 tetap OK
        "kelasCoil(0,0), kelasCoil(1,0),"
        # piston / di luar tiga offset
        "kelasCoil(1010,1000)]));"
    )
    hasil = json.loads(subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip())
    assert hasil == ["ok", "", "", "ok", "", "ok", "", ""]
