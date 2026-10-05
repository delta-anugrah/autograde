"""`/health/detail` jujur (batch 3.6 + 3.7): fps terukur, umur gambar, disk,
lisensi, dan PLC yang benar-benar tersambung.

`get_health_detail()` mengimpor torch; di sini torch diganti modul palsu kecil
(`sys.modules`), jadi yang diuji adalah fungsi ASLINYA, bukan potongannya.
"""
from __future__ import annotations

import sys
import time
import types
from collections import namedtuple
from dataclasses import replace
from pathlib import Path

import pytest
from ai_palsu import LinePalsu

import palmgrade.plc as plc
from palmgrade.core.config import Settings
from palmgrade.domain.kesehatan_disk import GB
from palmgrade.domain.kesehatan_kamera import StatistikAliran
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.services.health_service import HealthService
from palmgrade.services.pemantau_disk import PemantauDisk

Usage = namedtuple("Usage", "total used free")


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


@pytest.fixture
def torch_palsu(monkeypatch):
    cuda = types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda _i: "-")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))


def _service(line: LinePalsu) -> HealthService:
    return HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())


def test_line_sehat_melaporkan_fps_terukur_dan_umur_gambar(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.jalan(12)                                  # satu gambar per detik jam palsu
    d = _service(line).get_health_detail()
    assert d.fps_kamera == pytest.approx(1.0, rel=0.05)
    assert d.frame_umur_detik == 1.0
    assert d.status == "ok"


def test_fps_nol_saat_gambar_berhenti_bukan_angka_lama(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.jalan(12)
    line.state.inference_fps = 7.5
    line.jam.sekarang += 42
    d = _service(line).get_health_detail()
    assert (d.fps_kamera, d.fps_deteksi, d.frame_umur_detik) == (0.0, 0.0, 43.0)


def test_status_tetap_ok_walau_frame_berhenti(torch_palsu):
    """Load-bearing di lapisan SERVICE (angka `ai.keadaan`), BUKAN kode HTTP:
    `HealthDetailSchema.status` datang dari `HealthService.get_health_detail()`,
    yang hardcode `"ok"` dan tidak pernah membaca `ai.keadaan`. Kode HTTP 503
    yang sesungguhnya dijaga terpisah oleh
    `test_health_503_hanya_untuk_ai_mati_dan_frame_berhenti` di
    `tests/unit/test_kesehatan_ai.py` (`kode_http_health()`), dan
    `docs/overview.md` aturan 32 menjelaskan kenapa `autograde reset-data` dan
    Danger Zone bergantung pada kode HTTP itu, bukan pada field `status` ini."""
    line = LinePalsu()
    line.mulai()
    line.jalan(5)
    line.kamera.mengirim = False
    line.jalan(40, deteksi=False)
    d = _service(line).get_health_detail()
    assert d.status == "ok"
    assert d.ai["keadaan"] == "frame_berhenti"


def test_disk_dari_pemantau_yang_dipasang(torch_palsu):
    line = LinePalsu()
    line.state.pemantau_disk = PemantauDisk(
        settings=replace(Settings(), r2_bucket=""), jalur=(Path("/app/artifacts"),),
        ukur=lambda _p: Usage(468 * GB, 458 * GB, 10 * GB),
    )
    d = _service(line).get_health_detail()
    assert (d.disk["tingkat"], d.disk["kode"], d.disk["bebas_gb"]) == ("peringatan", "DISK_HAMPIR_PENUH", 10.0)


def test_tanpa_pemantau_disk_none(torch_palsu):
    assert _service(LinePalsu()).get_health_detail().disk is None


def test_lisensi_line_dari_gerbang_grading(torch_palsu):
    line = LinePalsu(lic_enabled=True)
    line.state.license_exp = 0
    d = _service(line).get_health_detail()
    assert d.lisensi == {"aktif": True, "grading_diblokir": True, "berlaku_sampai": None}


def test_lisensi_token_valid_tidak_diblokir(torch_palsu):
    # `grading_blocked()` membandingkan `license_exp` dengan jam DINDING
    # (`time.time()`), bukan jam monotonic `RuntimeState.jam` yang dipakai fps.
    line = LinePalsu(lic_enabled=True)
    line.state.license_exp = int(time.time()) + 3600                # masih jauh dari tenggat
    d = _service(line).get_health_detail()
    assert d.lisensi == {
        "aktif": True,
        "grading_diblokir": False,
        "berlaku_sampai": line.state.license_exp,
    }


def test_lisensi_mati_tidak_pernah_memblokir(torch_palsu):
    """`lic_enabled=False` (bawaan PC dev/cloud, PC pabrik yang belum dilisensi):
    fitur lisensi mati sama sekali, apa pun isi `license_exp`."""
    line = LinePalsu(lic_enabled=False)
    line.state.license_exp = 0
    d = _service(line).get_health_detail()
    assert d.lisensi == {"aktif": False, "grading_diblokir": False, "berlaku_sampai": None}


def test_plc_connected_dari_klien_bukan_dari_plc_menyala(torch_palsu, monkeypatch):
    klien = types.SimpleNamespace(connected=False)
    worker = types.SimpleNamespace(client=klien, inputs=[False] * 12, dropped_submissions=0,
                                   scheduler=types.SimpleNamespace(dropped=0),
                                   settings=types.SimpleNamespace(plc_coil_manual=None))
    monkeypatch.setattr(plc, "_worker", worker, raising=False)
    line = LinePalsu()
    assert _service(line).get_health_detail().plc["connected"] is False
    klien.connected = True
    assert _service(line).get_health_detail().plc["connected"] is True


def test_skema_lama_tanpa_field_baru_tetap_sah():
    """Konsol versi ini membaca line versi lama: semua field baru punya bawaan."""
    d = HealthDetailSchema(status="ok", environment="t", camera_type="hikrobot", camera_connected=True,
                           gpu_available=False, gpu_device=None, machine_id="m", workers=[])
    assert (d.fps_kamera, d.fps_deteksi, d.frame_umur_detik, d.disk, d.lisensi) == (0.0, 0.0, None, None, None)


def test_suhu_kamera_dilaporkan(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.kamera.suhu = 47.3
    line.jalan(3)
    d = _service(line).get_health_detail()
    assert d.suhu_kamera_c == 47.3
    assert d.model_dump()["suhu_kamera_c"] == 47.3


def test_suhu_basi_jadi_none(torch_palsu):
    """Kamera dicabut sesudah bacaan bagus: 45 °C dari lima menit lalu bukan suhu sekarang."""
    line = LinePalsu()
    line.mulai()
    line.kamera.suhu = 47.3
    line.jalan(1)                          # terbaca di jam 1000, jam lanjut ke 1001
    line.jam.sekarang += 59                # umur tepat 60 dtk: masih sah
    assert _service(line).get_health_detail().suhu_kamera_c == 47.3
    line.jam.sekarang += 1                 # 61 dtk: basi
    assert _service(line).get_health_detail().suhu_kamera_c is None


def test_tanpa_sensor_suhu_none(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.jalan(3)
    assert _service(line).get_health_detail().suhu_kamera_c is None


def test_kesehatan_kamera_line_sehat(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.state.camera_fps_terukur = 1.0
    line.kamera.statistik = StatistikAliran(diterima=0, hilang=0)
    line.jalan(10)
    line.kamera.statistik = StatistikAliran(diterima=10, hilang=0)
    line.jalan(10)
    d = _service(line).get_health_detail()
    assert d.fps_kamera_target == 1.0
    assert d.fps_kamera_turun is False
    assert d.frame_hilang == {"hilang": 0, "total": 10, "persen": 0.0, "tingkat": "aman"}
    assert d.putus_kamera == {"jumlah": 0, "tingkat": "aman"}
    assert d.kamera_tingkat == "aman"


def test_laju_turun_dilaporkan_selama_gambar_mengalir(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.state.camera_fps_terukur = 2.0
    line.jalan(200)
    d = _service(line).get_health_detail()
    assert d.fps_kamera_turun is True
    assert d.kamera_tingkat == "waspada"
    # Frames stopped: the card already shows the last image in red, a stale "low" says nothing.
    line.jam.sekarang += 60
    assert _service(line).get_health_detail().fps_kamera_turun is False


def test_kamera_tanpa_sensor_suhu_dilaporkan(torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.kamera.suhu_didukung = False
    line.jalan(3)
    d = _service(line).get_health_detail()
    assert d.suhu_kamera_didukung is False
    assert d.suhu_kamera_c is None


def test_skema_lama_tanpa_field_kesehatan_kamera():
    d = HealthDetailSchema(status="ok", environment="t", camera_type="hikrobot", camera_connected=True,
                           gpu_available=False, gpu_device=None, machine_id="m", workers=[])
    assert (d.suhu_kamera_didukung, d.fps_kamera_target, d.fps_kamera_turun) == (None, None, False)
    assert (d.frame_hilang, d.putus_kamera, d.kamera_tingkat) == (None, None, None)
