"""Access log uvicorn tanpa banjir polling (batch 3.3).

Konsol menanyai `/internal/status` tiap line SETIAP DETIK, tiap layar konsol yang
terbuka menanyai `/api/console/state` tiap 2 detik, dan healthcheck compose
mengetuk `/health` tiap 30 detik. Masing-masing satu baris access log: ±86 ribu
baris per hari per line, dan satu permintaan yang benar-benar penting tenggelam
di antaranya.

Yang dibisukan HANYA jawaban sukses (< 400) atas GET/HEAD ke jalur di
`JALUR_POLLING_SENYAP`. Jalur yang sama yang menjawab 4xx/5xx tetap tertulis
(itu justru yang dicari), dan POST ke jalur yang sama (mis. tombol simpan
timbangan) tetap tertulis karena itu tindakan orang, bukan polling.

Satu konstanta untuk line DAN konsol: jalurnya tidak bertabrakan, dan satu daftar
berarti menambah jalur polling baru cukup satu baris di sini.
"""

from __future__ import annotations

import logging

#: Jalur yang ditanya berulang oleh mesin, bukan dibuka orang. Tambahkan jalur
#: polling baru di sini, satu baris, tanpa menyentuh apa pun yang lain.
JALUR_POLLING_SENYAP: frozenset[str] = frozenset(
    {
        # Line
        "/health",  # healthcheck compose (30 dtk), cekKamera konsol (5 dtk); konsol juga punya /health
        "/health/detail",  # Diagnostik dan Uji PLC konsol lewat DevService (5 dtk, 1 dtk)
        "/internal/status",  # LineStatusWorker konsol, tiap detik, tiap line
        "/internal/plc",  # Uji PLC konsol (1 dtk)
        "/internal/outbox",  # Antrean line konsol (5 dtk)
        "/internal/rekam/status",  # Rekam Video konsol (3 dtk)
        "/internal/log",  # TarikLogLineWorker konsol, tiap 10 dtk, tiap line (batch 3.2)
        # Konsol
        "/api/console/state",  # layar operator, 2 dtk per layar yang terbuka
        "/api/console/weighings",  # tab Timbangan, 15 dtk
        "/api/console/trucks",  # daftar truk, 60 dtk
        "/api/console/riwayat",  # tab Rekap, 15 dtk selama rentangnya memuat hari ini (CSV-nya tidak)
        "/api/console/dev/diagnostik",  # Status dan Uji PLC (5 dtk, 1 dtk)
        "/api/console/dev/antrean/line",  # Antrean line (5 dtk)
        "/api/console/dev/rekam",  # Rekam Video (3 dtk)
    }
)

_METODE_BACA = frozenset({"GET", "HEAD"})


def polling_sukses(args: object) -> bool:
    """True kalau argumen access log uvicorn ini polling yang berhasil.

    Bentuknya milik uvicorn (`h11_impl`/`httptools_impl`):
    `(client_addr, method, path_with_query, http_version, status_code)`. Bentuk lain
    apa pun dianggap BUKAN polling: lebih baik satu baris berlebih daripada satu
    baris penting yang hilang karena uvicorn mengubah formatnya.
    """
    if not isinstance(args, tuple) or len(args) != 5:
        return False
    _klien, metode, jalur, _versi, status = args
    if not (isinstance(metode, str) and isinstance(jalur, str) and isinstance(status, int)):
        return False
    return (
        metode in _METODE_BACA
        and status < 400
        and jalur.split("?", 1)[0] in JALUR_POLLING_SENYAP
    )


class SaringAksesPolling(logging.Filter):
    """Filter untuk logger `uvicorn.access`: buang polling yang sukses, sisanya lewat."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not polling_sukses(record.args)


#: Potongan pesan uvicorn (0.34 `Server.shutdown`) saat SIGTERM masih menemukan
#: koneksi terbuka sesudah `--timeout-graceful-shutdown 1`.
PESAN_TENGGANG_TUTUP = "timeout graceful shutdown exceeded"


class TurunkanTenggangTutup(logging.Filter):
    """Filter untuk logger `uvicorn.error`: tenggang tutup yang habis jadi INFO.

    Layar konsol SELALU membuka `/api/video_feed` (MJPEG tanpa akhir), jadi tiap
    restart atau upgrade line menulis "Cancel 1 running task(s), timeout graceful
    shutdown exceeded" di ERROR. Itu jalan normal (services/penutup_line.py), bukan
    galat: tetap di `docker logs`, tapi tidak masuk tab Log dan Discord. Galat
    uvicorn lain tidak disentuh.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and PESAN_TENGGANG_TUTUP in str(record.msg):
            record.levelno = logging.INFO
            record.levelname = logging.getLevelName(logging.INFO)
        return True
