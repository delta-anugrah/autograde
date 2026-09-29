"""Penjaga AI mati (batch 2.1): komponen SUNGGUHAN dirangkai tanpa torch.

`FrameCaptureWorker` + `FrameProcessingWorker` asli (kamera dan pipeline palsu),
`PenjagaAi`, `PlcWorker` asli dengan klien PLC palsu, router `/health` asli,
dan di sisi konsol `LineClient` + `LineStatusWorker` asli lewat transport ASGI
(test terakhir, Task 7). Satu-satunya pengganti: rute `/internal/status` line
(yang asli menarik torch lewat `core.dependencies`), yang di sini membangun
jawaban dengan `ringkas_ai_dari_state` yang sama persis dengan controller aslinya.
"""
from __future__ import annotations

from ai_palsu import LinePalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.plc.pulse import PulseScheduler
from palmgrade.plc.worker import PlcWorker
from palmgrade.routes.health_ringan import buat_router_health
from palmgrade.services.health_service import HealthService

COIL_ERROR = 1002


class _KlienPlc:
    def __init__(self) -> None:
        self.tulis: list[tuple[int, bool]] = []

    def write_coil(self, coil, level):
        self.tulis.append((coil, level))
        return True

    def read_discrete_inputs(self, start, count):
        return [False] * count

    def close(self):
        pass


class _CfgPlc:
    plc_coil_ok, plc_coil_ng, plc_coil_error = 1000, 1001, COIL_ERROR
    plc_coil_alive = ()
    plc_alive_toggle_ms = 0
    plc_poll_ms = 200
    plc_di_count = 16
    plc_di_base = 1100
    plc_coil_manual = None


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


class Rakitan:
    def __init__(self) -> None:
        self.line = LinePalsu()
        self.klien_plc = _KlienPlc()
        self.plc = PlcWorker(
            client=self.klien_plc,
            scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=1),
            settings=_CfgPlc(),
            health_check=self.line.penjaga.sehat_untuk_plc,
        )
        self._tick = 0.0
        app = FastAPI()
        svc = HealthService(settings=self.line.settings, state=self.line.state,
                            camera=self.line.kamera, outbox=_Outbox())
        app.include_router(buat_router_health(lambda: svc))
        self.http = TestClient(app)

    def error_plc(self) -> bool:
        """Satu tick PLC; level terakhir yang DITULIS ke coil ERROR."""
        self._tick += 1.1           # lewat jadwal tulis ulang 1 detik
        self.plc.run_once(now=self._tick)
        return [v for c, v in self.klien_plc.tulis if c == COIL_ERROR][-1]


def test_cuda_rusak_menaikkan_error_503_lalu_pulih_menurunkannya():
    r = Rakitan()
    r.line.mulai()
    r.line.jalan(5)
    assert (r.error_plc(), r.http.get("/health").status_code) == (False, 200)

    r.line.pipeline.galat = RuntimeError("CUDA error: an illegal memory access was encountered")
    r.line.jalan(31)
    r.line.capture.run_once()
    assert (r.error_plc(), r.http.get("/health").status_code) == (True, 503)

    r.line.pipeline.galat = None
    r.line.jalan(1)
    assert (r.error_plc(), r.http.get("/health").status_code) == (False, 200)


def test_tenggang_start_lalu_ai_yang_tidak_pernah_menjawab():
    """Frame pertama menggantung di GPU: loop jalan, gambar masuk, tidak ada yang
    selesai. Selama tenggang: diam. Sesudahnya: alarm."""
    r = Rakitan()
    r.line.mulai()
    r.line.jalan(29, deteksi=False)
    assert r.error_plc() is False
    r.line.jalan(2, deteksi=False)
    assert r.error_plc() is True


def test_video_habis_bukan_ai_mati():
    r = Rakitan()
    r.line.mulai()
    r.line.jalan(5)
    r.line.kamera.habis = True
    r.line.jam.sekarang += 40        # tidak ada frame yang bisa diambil
    assert r.line.penjaga.nilai().keadaan.value == "sumber_diam"
    assert (r.error_plc(), r.http.get("/health").status_code) == (False, 200)


def test_kamera_putus_tetap_menaikkan_error_seperti_dulu():
    r = Rakitan()
    r.line.mulai()
    r.line.jalan(5)
    r.line.kamera.connected = False
    assert (r.error_plc(), r.http.get("/health").status_code) == (True, 200)
