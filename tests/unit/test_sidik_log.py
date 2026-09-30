"""Sidik penggabungan tab Log (batch 3.3): id yang berganti tidak memecah satu galat,
galat yang BERBEDA tidak pernah tergabung.

Dua arah salahnya sama mahal: tidak tergabung = banjir satu galat mendorong galat
lain keluar dari layar; tergabung keliru = HTTP 404 dan 500, atau line-1 dan line-2,
terbaca satu masalah dan yang kedua tidak pernah dicari.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.sidik_log import jenis_galat, normalkan_pesan, ringkas_galat
from palmgrade.repositories.log_repository import LogStore, _fingerprint


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Penugasan 3f2a9c1e-5b7d-4e1a-9c3f-2b6d4c8e7b01 gagal diteruskan",
            "Penugasan a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02 gagal diteruskan",
        ),
        ("Folder truk 3f2a9c1e tidak bisa dibuat", "Folder truk 9d2b6a1e tidak bisa dibuat"),
        ("Tulis foto lambat: 1.52 s", "Tulis foto lambat: 0.97 s"),
        ("Event 1727680000.123 ditolak", "Event 1727680003.456 ditolak"),
        ("Baris outbox 1234567 gagal", "Baris outbox 7654321 gagal"),
    ],
)
def test_id_yang_berganti_menghasilkan_sidik_yang_sama(a, b):
    assert normalkan_pesan(a) == normalkan_pesan(b)
    assert _fingerprint("ERROR", "x", a) == _fingerprint("ERROR", "x", b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("AutoERP menjawab HTTP 404", "AutoERP menjawab HTTP 500"),
        ("line http://localhost:8001 tidak menjawab", "line http://localhost:8002 tidak menjawab"),
        ("PLC 192.168.3.39:1025 terputus", "PLC 192.168.3.40:1025 terputus"),
        ("[Errno 111] Connection refused", "[Errno 113] No route to host"),
        ("Versi v1.19.0 terpasang", "Versi v1.20.0 terpasang"),
        ("Truk BE 1234 AB tidak dikenal", "Truk BG 1234 AB tidak dikenal"),
        ("coil 1000 gagal ditulis", "coil 1001 gagal ditulis"),
        ("antrean 12345 baris", "antrean 12346 baris"),
    ],
)
def test_galat_yang_berbeda_tidak_pernah_tergabung(a, b):
    assert _fingerprint("ERROR", "x", a) != _fingerprint("ERROR", "x", b)


def test_kata_biasa_berhuruf_hex_tidak_disentuh():
    assert normalkan_pesan("deadbeef facade decade") == "deadbeef facade decade"


def test_pesan_tanpa_id_sidiknya_tidak_berubah_dari_versi_lama():
    """Baris yang ditulis versi lama dan baris baru untuk pesan yang sama tetap satu
    sidik: pesan tanpa id tidak diubah normalisasi sama sekali."""
    pesan = "AutoERP terputus: [Errno 111] Connection refused"
    assert normalkan_pesan(pesan) == pesan


def test_logstore_menggabungkan_galat_yang_cuma_beda_id(tmp_path):
    store = LogStore(tmp_path / "log.db")
    for i, assign in enumerate(("3f2a9c1e", "9d2b6a1e", "a7e2f4c9")):
        store.write("ERROR", "palmgrade.x", f"Folder truk {assign} tidak bisa dibuat", None, now=1000.0 + i)
    hasil = store.read(level=None, search=None, limit=10, offset=0)
    assert hasil["total"] == 1
    # Pesan yang disimpan tetap milik kejadian pertama, bukan versi yang dinormalkan.
    assert hasil["items"][0]["message"] == "Folder truk 3f2a9c1e tidak bisa dibuat"
    assert hasil["items"][0]["count"] == 3


def test_logstore_tidak_menggabungkan_kode_http_yang_berbeda(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "palmgrade.x", "AutoERP menjawab HTTP 404", None, now=1000.0)
    store.write("ERROR", "palmgrade.x", "AutoERP menjawab HTTP 500", None, now=1001.0)
    assert store.read(level=None, search=None, limit=10, offset=0)["total"] == 2


_TB_KEY = 'Traceback (most recent call last):\n  File "x.py", line 1, in f\nKeyError: \'state\'\n'
_TB_INTEG = (
    'Traceback (most recent call last):\n  File "y.py", line 9, in g\n'
    "sqlite3.IntegrityError: UNIQUE constraint failed: weighings.id\n"
)
_ASGI = "Exception in ASGI application\n"


def _tb(kelas_pesan: str, *, berkas: str = "/app/src/palmgrade/routes/console.py", baris: int = 12) -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "/usr/local/lib/python3.11/site-packages/starlette/routing.py", line 74, in app\n'
        "    response = await f(request)\n"
        f'  File "{berkas}", line {baris}, in simpan\n'
        "    return store.simpan(data)\n"
        f"{kelas_pesan}\n"
    )


def test_jenis_galat_cuma_nama_kelas():
    """Yang keluar pabrik (Discord) cuma nama kelasnya, bukan isi pesannya."""
    assert jenis_galat(_TB_KEY) == "KeyError"
    assert jenis_galat(_TB_INTEG) == "sqlite3.IntegrityError"
    assert jenis_galat("Traceback (most recent call last):\nKeyboardInterrupt\n") == "KeyboardInterrupt"
    assert jenis_galat("baris bebas: bukan traceback") == ""
    assert jenis_galat(None) == ""


def test_jenis_galat_pesan_banyak_baris_tidak_membocorkan_baris_berikutnya():
    """Review wave 2: `ValueError: bad\nB1234XY` dulu mengembalikan `B1234XY`, sebuah
    plat, yang lalu tampil di Discord."""
    assert jenis_galat(_tb("ValueError: bad\nB1234XY")) == "ValueError"
    assert jenis_galat(_tb("ValueError: bad\n  indented: tail\nlast line")) == "ValueError"


def test_jenis_galat_galat_berantai_memakai_akar_penyebabnya():
    """Kelas galat berantai diambil dari kepala blok PERTAMA (akar penyebab, dicetak lebih
    dulu): teks lain tidak pernah dibaca sebagai kelas (probe wave 4 di bawah). Frame
    pembedanya dicari di SELURUH detail: frame `palmgrade/` terakhir."""
    berantai = (
        _tb("KeyError: 'a'")
        + "\nThe above exception was the direct cause of the following exception:\n\n"
        + _tb("RuntimeError: gagal menyimpan\nB9999ZZ", berkas="/app/src/palmgrade/services/x.py")
    )
    assert jenis_galat(berantai) == "KeyError"
    assert ringkas_galat(berantai) == "KeyError@palmgrade/services/x.py:12"


def test_jenis_galat_kepala_yang_bukan_nama_kelas_kosong():
    assert jenis_galat(_tb("bukan kelas: huruf kecil")) == ""
    assert jenis_galat("B1234XY\n") == ""              # tanpa traceback sama sekali


def test_ringkas_galat_kelas_dan_frame_terakhir_bukan_teks_galatnya():
    """Review wave 2: sidik memakai kelas + frame terakhir, jadi galat yang sama dengan
    plat, hitungan pendek, jam, atau jalur berbeda di teksnya tetap satu baris."""
    a = _tb("ValueError: truk B1234XY ditolak jam 10:15, sisa 3 dari /media/a.mp4")
    b = _tb("ValueError: truk D5678AB ditolak jam 11:42, sisa 7 dari /media/b.mp4")
    assert ringkas_galat(a) == ringkas_galat(b) == "ValueError@palmgrade/routes/console.py:12"
    assert ringkas_galat(None) == ""
    assert ringkas_galat("   \n") == ""


def test_ringkas_galat_kelas_atau_tempat_berbeda_tetap_beda():
    dasar = _tb("ValueError: x")
    assert ringkas_galat(dasar) != ringkas_galat(_tb("KeyError: x"))
    assert ringkas_galat(dasar) != ringkas_galat(_tb("ValueError: x", baris=40))
    assert ringkas_galat(dasar) != ringkas_galat(_tb("ValueError: x", berkas="/app/src/palmgrade/services/y.py"))


def test_logstore_galat_berulang_dengan_plat_berbeda_satu_baris(tmp_path):
    store = LogStore(tmp_path / "log.db")
    for i, plat in enumerate(("B1234XY", "D5678AB", "BE9012CD")):
        store.write("ERROR", "palmgrade.x", "Simpan timbangan gagal",
                    _tb(f"ValueError: truk {plat} ditolak jam 10:1{i}"), now=100.0 + i)
    (baris,) = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert baris["count"] == 3


def test_pesan_sama_galat_berbeda_dua_sidik():
    assert _fingerprint("ERROR", "uvicorn.error", _ASGI, _TB_KEY) != _fingerprint(
        "ERROR", "uvicorn.error", _ASGI, _TB_INTEG
    )


def test_pesan_tanpa_traceback_sidiknya_sama_dengan_versi_lama():
    """Baris lama dan baru tanpa traceback tetap satu sidik sesudah upgrade."""
    assert _fingerprint("ERROR", "x", "a", None) == _fingerprint("ERROR", "x", "a")


def test_logstore_500_berbeda_dalam_satu_jendela_jadi_dua_baris(tmp_path):
    """uvicorn menulis tiap 500 dengan pesan tetap "Exception in ASGI application".
    Dua galat berbeda dalam 60 detik dulu jadi satu baris dengan traceback yang
    pertama saja: galat kedua hilang dari mana pun."""
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "uvicorn.error", _ASGI, _TB_KEY, now=100.0)
    store.write("ERROR", "uvicorn.error", _ASGI, _TB_INTEG, now=130.0)
    store.write("ERROR", "uvicorn.error", _ASGI, _TB_KEY, now=140.0)
    items = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert sorted((i["count"], i["detail"].strip().splitlines()[-1]) for i in items) == [
        (1, "sqlite3.IntegrityError: UNIQUE constraint failed: weighings.id"),
        (2, "KeyError: 'state'"),
    ]


# ── Review wave 3 ──


def _tb_lib(route: str, baris: int) -> str:
    """Galat yang dilempar pustaka: frame terakhir di pydantic, bukan di kode kita."""
    return (
        "Traceback (most recent call last):\n"
        f'  File "/app/src/palmgrade/routes/{route}", line {baris}, in simpan\n'
        "    data = Model(**isi)\n"
        '  File "/usr/local/lib/python3.11/site-packages/pydantic/main.py", line 212, in __init__\n'
        "    validated_self = self.__pydantic_validator__.validate_python(data)\n"
        "pydantic_core._pydantic_core.ValidationError: 1 validation error for Model\n"
        "plat\n  Field required\n"
    )


def test_ringkas_galat_memakai_frame_kode_kita_bukan_frame_pustaka():
    """Dua 500 berbeda dari rute berbeda yang sama-sama berakhir di pydantic dulu jadi satu
    baris: traceback yang kedua hilang."""
    a, b = _tb_lib("a.py", 10), _tb_lib("b.py", 50)
    assert ringkas_galat(a) == "pydantic_core._pydantic_core.ValidationError@palmgrade/routes/a.py:10"
    assert ringkas_galat(a) != ringkas_galat(b)
    assert ringkas_galat(a) == ringkas_galat(_tb_lib("a.py", 10))


def test_ringkas_galat_tanpa_frame_kode_kita_memakai_frame_terakhir():
    tb = (
        "Traceback (most recent call last):\n"
        '  File "/usr/local/lib/python3.11/site-packages/uvicorn/x.py", line 5, in a\n'
        "    b()\n"
        '  File "/usr/local/lib/python3.11/site-packages/httpx/y.py", line 9, in b\n'
        "    raise ConnectError\n"
        "httpx.ConnectError: refused\n"
    )
    assert ringkas_galat(tb) == "httpx.ConnectError@httpx/y.py:9"


def test_logstore_dua_rute_berbeda_galat_pustaka_sama_tetap_dua_baris(tmp_path):
    store = LogStore(tmp_path / "log.db")
    store.write("ERROR", "uvicorn.error", _ASGI, _tb_lib("a.py", 10), now=100.0)
    store.write("ERROR", "uvicorn.error", _ASGI, _tb_lib("b.py", 50), now=110.0)
    store.write("ERROR", "uvicorn.error", _ASGI, _tb_lib("a.py", 10), now=120.0)
    items = store.read(level=None, search=None, limit=10, offset=0)["items"]
    assert sorted(i["count"] for i in items) == [1, 2]


def test_baris_berbentuk_frame_di_dalam_pesan_galat_tidak_jadi_nama_kelas():
    """Probe review wave 3: teks pesan yang kebetulan berbentuk frame tidak boleh membuat
    baris sesudahnya (sebuah plat) terbaca sebagai nama kelas."""
    probe = _tb('RuntimeError: child failed\n  File "z.py", line 3, in q\nB1234XY')
    assert jenis_galat(probe) == "RuntimeError"
    assert ringkas_galat(probe) == "RuntimeError@palmgrade/routes/console.py:12"


def test_traceback_utuh_di_dalam_pesan_galat_tidak_jadi_nama_kelas():
    """Pesan yang memuat keluaran traceback proses lain: penandanya tidak didahului pemisah
    rantai, jadi bukan traceback milik galat ini."""
    probe = _tb(
        "RuntimeError: child failed\nTraceback (most recent call last):\n"
        '  File "z.py", line 3, in q\nB1234XY'
    )
    assert jenis_galat(probe) == "RuntimeError"


def test_traceback_yang_kepalanya_terpotong_tetap_punya_frame_tanpa_kelas():
    """`potong_detail` menyimpan ekor traceback yang panjang: penandanya bisa ikut terpotong.
    Sesudah sinkron ulang kelas sengaja kosong (keputusan wave 5), frame tetap terbaca."""
    terpotong = (
        "...(dipotong)\n"
        "    x()\n"
        '  File "/app/src/palmgrade/workers/a.py", line 5, in f\n'
        "    y()\n"
        "KeyError: 1\n"
    )
    assert jenis_galat(terpotong) == ""
    assert ringkas_galat(terpotong) == "@palmgrade/workers/a.py:5"



# ── Review wave 4 ──


def _traceback_panjang(ekor_pesan: int) -> str:
    """Traceback ASLI (`traceback.format_exception`) lebih dari 8.000 karakter: 150 frame
    di berkas `palmgrade/`, pesan galat dua baris yang panjang baris keduanya diatur."""
    import traceback

    kode = "\n".join(
        [f"def fungsi_yang_namanya_cukup_panjang_{i}():\n    fungsi_yang_namanya_cukup_panjang_{i + 1}()"
         for i in range(150)]
        + ["def fungsi_yang_namanya_cukup_panjang_150():\n    raise ValueError(PESAN)"]
    )
    ruang: dict = {"PESAN": "truk B1234XY ditolak\n" + "m" * ekor_pesan}
    exec(compile(kode, "/app/src/palmgrade/workers/panjang.py", "exec"), ruang)
    try:
        ruang["fungsi_yang_namanya_cukup_panjang_0"]()
    except ValueError as exc:
        return "".join(traceback.format_exception(exc))
    raise AssertionError("tidak melempar")


def test_traceback_panjang_yang_dipotong_di_mana_pun_tetap_punya_sidik():
    """Review wave 4: `potong_detail` memotong di OFFSET KARAKTER, jadi baris pertama
    sesudah tanda potong biasanya potongan frame yang tidak menjorok. Parser lama
    menganggapnya kepala blok dan sidiknya kosong untuk 94 dari 120 potongan."""
    from palmgrade.domain.log_line import PANJANG_DETAIL_MAKS, potong_detail

    diuji = 0
    for ekor in range(0, 360, 3):
        asli = _traceback_panjang(ekor)
        assert len(asli) > PANJANG_DETAIL_MAKS
        terpotong = potong_detail(asli)
        if "ValueError: truk" not in terpotong or 'palmgrade/workers/panjang.py"' not in terpotong:
            continue
        diuji += 1
        # Kepala blok pertama ikut terpotong (perlu sinkron ulang ke frame utuh): kelas
        # sengaja kosong, frame pembedanya tetap benar jadi sidiknya tidak kosong.
        assert jenis_galat(terpotong) == "", ekor
        assert ringkas_galat(terpotong) == "@palmgrade/workers/panjang.py:302", ekor
    assert diuji == 120


def test_rantai_palsu_di_dalam_pesan_galat_terakhir_tidak_dibaca():
    """Probe review wave 4: pesan galat terakhir yang memuat rantai tiruan lengkap (pemisah,
    penanda, frame, lalu plat) tidak boleh membuat plat terbaca sebagai nama kelas."""
    probe = _tb(
        "RuntimeError: wrap\n\nThe above exception was the direct cause of the following exception:"
        '\n\nTraceback (most recent call last):\n  File "/tmp/x.py", line 9, in g\nB1234XY: plate'
    )
    assert jenis_galat(probe) == "RuntimeError"
    assert ringkas_galat(probe) == "RuntimeError@palmgrade/routes/console.py:12"


def test_detail_20000_baris_selesai_jauh_di_bawah_satu_detik():
    """Dipanggil di dalam panggilan logging: detail sepanjang apa pun harus linear."""
    import time

    pemisah = "\nThe above exception was the direct cause of the following exception:\n\n"
    blok = 'Traceback (most recent call last):\n  File "/app/src/palmgrade/a.py", line 1, in f\nKeyError: 1\n'
    raksasa = pemisah.join([blok] * 4000)          # sekitar 20.000 baris, 4.000 penanda
    assert raksasa.count("\n") >= 20000
    mulai = time.perf_counter()
    for _ in range(3):
        ringkas_galat(raksasa)
        jenis_galat(raksasa)
    assert time.perf_counter() - mulai < 1.0



# ── Review wave 5 (keputusan koordinator): kelas dari blok pertama, frame dari seluruh detail ──


def _jalankan(berkas: dict[str, str], masuk: str) -> str:
    """Kompilasi beberapa "berkas" palmgrade di satu ruang nama, jalankan `masuk`, dan
    kembalikan traceback ASLI-nya (`traceback.format_exception`)."""
    import traceback

    ruang: dict = {}
    for jalur, kode in berkas.items():
        exec(compile(kode, jalur, "exec"), ruang)
    try:
        ruang[masuk]()
    except Exception as exc:  # noqa: BLE001, yang diuji justru traceback-nya
        return "".join(traceback.format_exception(exc))
    raise AssertionError("tidak melempar")


def test_httpx_connect_error_dari_dua_rute_berbeda_tetap_dua_sidik():
    """ConnectError httpx ASLI (berantai dari httpcore) dari dua rute berbeda. Wave 4
    menyatukan keduanya jadi `httpcore.ConnectError@httpcore/_exceptions.py:14`."""
    kode = (
        "import httpx\n"
        "def {nama}():\n"
        "    httpx.Client(timeout=1).get('http://127.0.0.1:1/')\n"
    )
    a = _jalankan({"/app/src/palmgrade/routes/timbangan.py": kode.format(nama="timbang")}, "timbang")
    b = _jalankan({"/app/src/palmgrade/routes/lisensi.py": kode.format(nama="lisensi")}, "lisensi")
    assert "The above exception was the direct cause" in a
    assert ringkas_galat(a).endswith("@palmgrade/routes/timbangan.py:3")
    assert ringkas_galat(b).endswith("@palmgrade/routes/lisensi.py:3")
    assert ringkas_galat(a) != ringkas_galat(b)


def test_raise_from_di_dua_rute_lewat_helper_yang_sama_tetap_dua_sidik():
    bantu = "def bantu():\n    raise ValueError('x')\n"
    rute = (
        "class {kelas}(Exception):\n    pass\n"
        "def {nama}():\n"
        "    try:\n        bantu()\n"
        "    except ValueError as e:\n        raise {kelas}('gagal') from e\n"
    )
    a = _jalankan({"/app/src/palmgrade/domain/bantu.py": bantu,
                   "/app/src/palmgrade/routes/a.py": rute.format(kelas="SimpanGagal", nama="a")}, "a")
    b = _jalankan({"/app/src/palmgrade/domain/bantu.py": bantu,
                   "/app/src/palmgrade/routes/b.py": rute.format(kelas="KirimGagal", nama="b")}, "b")
    assert ringkas_galat(a) == "ValueError@palmgrade/routes/a.py:7"
    assert ringkas_galat(b) == "ValueError@palmgrade/routes/b.py:7"


def test_sinkron_ulang_sesudah_potongan_tidak_pernah_menghasilkan_kelas():
    """Detail yang terpotong SEBELUM kepala blok pertamanya: yang terbaca sesudah sinkron
    ulang bisa teks pesan galat (di sini keluaran proses anak yang memuat plat). Kelas
    kosong; sidik boleh berisi frame, tapi tidak pernah platnya."""
    from palmgrade.domain.log_line import potong_detail

    pesan = "stderr anak:\n" + "x" * 9000 + '\n  File "/tmp/x.py", line 9, in g\nB1234XY: plate\n' + "y" * 100
    kode = "def jalan():\n    raise RuntimeError(PESAN)\n"
    ruang_berkas = {"/app/src/palmgrade/workers/anak.py": f"PESAN = {pesan!r}\n" + kode}
    terpotong = potong_detail(_jalankan(ruang_berkas, "jalan"))
    assert terpotong.startswith("...(dipotong)")
    assert jenis_galat(terpotong) == ""
    assert "B1234XY" not in ringkas_galat(terpotong)
