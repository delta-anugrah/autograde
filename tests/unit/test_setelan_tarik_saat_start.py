"""Line mengambil setelan grading dari konsol saat start.

Override hidup di `RuntimeState`, jadi hilang bersama prosesnya. Tanpa tarikan
ini, satu `docker compose up` di tengah shift diam-diam mengembalikan ambang
`.env` — dan tidak ada yang tahu sampai tonase harian terlihat aneh.

Yang dikunci di sini adalah sifat-sifat yang bikin fitur ini aman, bukan jalur
HTTP-nya (itu sudah dibuktikan lawan konsol sungguhan):

- gagal = diam dan pakai `.env`, BUKAN gagal start. Urutan start container tidak
  dijamin, jadi konsol yang belum hidup saat line start itu kejadian normal.
- `sumber == "env"` tidak menimpa apa pun: konsol yang belum pernah diubah dari
  layar memang mengembalikan nilai `.env`, dan menimpanya dengan angka yang sama
  cuma bikin log membingungkan.
"""
from __future__ import annotations

import pathlib


def _sumber_main() -> str:
    """Dibaca sebagai teks: `main.py` menarik cv2 dan torch, dan CI sengaja jalan
    tanpa keduanya (CLAUDE.md § Tests)."""
    berkas = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "main.py"
    )
    return berkas.read_text(encoding="utf-8")


def _fungsi_tarik() -> str:
    return _sumber_main().split("async def _tarik_setelan_grading(")[1].split("\ndef ")[0]


def test_dipanggil_sesudah_state_ada_dan_sebelum_worker_menyala():
    """Kalau dipanggil sebelum `state` dibuat -> UnboundLocalError dan line tidak
    start sama sekali. Kalau sesudah worker menyala, janjang pertama sempat
    digrading dengan ambang yang salah."""
    s = _sumber_main()
    i_state = s.index("state = get_runtime_state()")
    i_tarik = s.index("await _tarik_setelan_grading(settings, state)")
    assert i_state < i_tarik, "state harus ada dulu"

    # Worker deteksi dirakit sesudahnya.
    i_worker = s.index("FrameProcessingWorker(")
    assert i_tarik < i_worker, "setelan harus terpasang sebelum grading jalan"


def test_gagal_tidak_menjatuhkan_line():
    """`except Exception` yang sengaja lebar: jaringan putus, konsol belum hidup,
    JSON aneh — semuanya berujung pakai `.env`, bukan line yang menolak start."""
    f = _fungsi_tarik()
    assert "except Exception" in f
    assert "raise" not in f.split("except Exception")[1]


def test_status_bukan_200_tidak_menimpa():
    f = _fungsi_tarik()
    assert "res.status_code != 200" in f
    assert "return" in f.split("res.status_code != 200")[1][:200]


def test_sumber_env_dilewati():
    """Konsol yang belum pernah diubah mengembalikan nilai `.env`; menimpanya
    dengan angka yang sama tidak salah, tapi membuat log berbohong soal ada
    setelan dari konsol."""
    f = _fungsi_tarik()
    assert 'data.get("sumber") != "konsol"' in f


def test_nilai_dari_konsol_tetap_divalidasi():
    """Konsol sudah memvalidasi saat menyimpan, tapi line tidak boleh percaya
    begitu saja: berkas DB bisa diedit tangan, dan angka nol yang lolos ke sini
    mematikan penjaga ukuran sepanjang shift."""
    f = _fungsi_tarik()
    assert "bersihkan_setelan(" in f


def test_lane_mesin_bukan_lane_operator():
    """Line tidak punya sesi operator. Endpoint-nya harus di `ingest_router`
    (x-webhook-secret), bukan di lane `/api/console/dev/*` yang butuh login."""
    konsol = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "routes" / "console.py"
    ).read_text(encoding="utf-8")
    assert '@ingest_router.get("/internal/setelan")' in konsol

    blok = konsol.split('@ingest_router.get("/internal/setelan")')[1][:700]
    assert "x_webhook_secret" in blok
    assert "Support" not in blok, "lane mesin tidak boleh minta role operator"


def test_timeout_dipatok():
    """Tanpa timeout, konsol yang menggantung menahan startup line selamanya —
    dan itu line yang tidak pernah menggrading apa pun."""
    f = _fungsi_tarik()
    assert "timeout=" in f


def test_fungsinya_async():
    """Lifespan meng-`await` ini. Kalau suatu saat jadi sinkron, startup pecah."""
    assert "async def _tarik_setelan_grading(" in _sumber_main()
