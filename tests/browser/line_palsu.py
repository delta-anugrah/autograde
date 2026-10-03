"""A camera line that answers the console without a camera, a model or a PLC.

It serves what the console and the screen ask a line for during the browser flows:
`/health`, a healthy `/internal/status` (no alarms, AI alive, the shape
`LineStatusWorker` reads), a `/health/detail` for the Status tab's Diagnostics card, the camera feed (one PNG frame, enough for the card to count
as connected) and the commands the tests trigger (`/internal/assignment`,
`/internal/setelan`, `/internal/camera/reconnect`; the last one can be told to answer late
or as a video line, `atur_sambung_ulang`). Everything else is 404, which is what an older line image answers,
and the screen must word that without a script error. Every POST is recorded.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from harness import port_bebas

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
STATUS_SEHAT = {
    "piston": {"requested": False, "confirmed_open": False},
    "alarms": [],
    "unggah": None,
    "ai": {"mati": False},
    "ffb_source": None,
}
# What the Diagnostics card needs from a healthy Hikrobot line; the console passes it through.
DETAIL_SEHAT = {
    "camera_connected": True,
    "fps_kamera": 14.9,
    "fps_deteksi": 7.2,
    "frame_umur_detik": 0.1,
    "suhu_kamera_c": 47.3,
    "workers": [{"name": "capture", "alive": True}],
}
_PERINTAH = ("/internal/assignment", "/internal/setelan")
_SAMBUNG_ULANG = "/internal/camera/reconnect"


class _Penjawab(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        jalur = urlsplit(self.path).path
        if jalur == "/api/video_feed":
            self._kirim(200, PNG_1PX, "image/png")
        elif jalur == "/health":
            self._json(200, {"status": "ok"})
        elif jalur == "/internal/status":
            self._json(200, STATUS_SEHAT)
        elif jalur == "/health/detail":
            self._json(200, DETAIL_SEHAT)
        else:
            self._json(404, {"detail": "Not Found"})

    def do_POST(self) -> None:
        panjang = int(self.headers.get("content-length") or 0)
        isi = json.loads(self.rfile.read(panjang) or b"{}")
        jalur = urlsplit(self.path).path
        self.server.diterima.append((jalur, isi))
        if jalur in _PERINTAH:
            self._json(200, {"status": "ok"})
        elif jalur == _SAMBUNG_ULANG:
            time.sleep(self.server.sambung_ulang_jeda)
            if self.server.sambung_ulang_tanpa_kamera:
                self._json(409, {"detail": {"kode": "kamera_tanpa_sambung_ulang", "pesan": "video"}})
            else:
                self._json(202, {"status": "requested"})
        else:
            self._json(404, {"detail": "Not Found"})

    def _json(self, status: int, isi: dict) -> None:
        self._kirim(status, json.dumps(isi).encode(), "application/json")

    def _kirim(self, status: int, isi: bytes, jenis: str) -> None:
        self.send_response(status)
        self.send_header("content-type", jenis)
        self.send_header("content-length", str(len(isi)))
        self.end_headers()
        self.wfile.write(isi)

    def log_message(self, *_args) -> None:  # keep pytest output readable
        return


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int) -> None:
        super().__init__(("127.0.0.1", port), _Penjawab)
        self.diterima: list[tuple[str, dict]] = []
        self.sambung_ulang_jeda = 0.0
        self.sambung_ulang_tanpa_kamera = False


class LinePalsu:
    def __init__(self, kode: str, server: _Server) -> None:
        self.kode = kode
        self._server = server
        self.port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def mulai(cls, kode: str) -> LinePalsu:
        return cls(kode, _Server(port_bebas()))

    @property
    def diterima(self) -> list[tuple[str, dict]]:
        return self._server.diterima

    def atur_sambung_ulang(self, *, jeda: float = 0.0, tanpa_kamera: bool = False) -> None:
        """How the next reconnect requests are answered: `jeda` seconds late, or 409 as a
        video or photo line. The lines live for the whole session: reset it afterwards."""
        self._server.sambung_ulang_jeda = jeda
        self._server.sambung_ulang_tanpa_kamera = tanpa_kamera

    def berhenti(self) -> None:
        self._server.shutdown()
        self._server.server_close()
