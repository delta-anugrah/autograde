"""Line palsu + data contoh untuk test Danger Zone (unit, e2e, integrasi).

Satu tempat, dipakai tiga lapis test: kalau `LineClient` mendapat method baru
yang dipanggil `BahayaService`, cukup satu line palsu yang harus mengikutinya.
"""
from __future__ import annotations

import time

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)
HASH = hash_password("sandi-bawaan-uji")


class LinePalsu:
    """Tiga line yang sehat, kecuali diubah per test."""

    def __init__(self) -> None:
        self.detail = {
            ln.line_code: {"outbox_pending": 0, "current_assignment_id": None} for ln in LINES
        }
        self.mati: set[str] = set()
        self.merekam: set[str] = set()
        self.tolak_hapus: set[str] = set()
        self.perintah: list[tuple[str, str]] = []
        self.hidup_sisa: dict[str, int] = {}
        self.saat_hidup_dicek = None

    def _cek(self, line: LineEndpoint) -> None:
        if line.line_code in self.mati:
            raise LineUnavailable("LINE_TIDAK_MENJAWAB", f"{line.line_code} mati", line=line.name)

    async def health_detail(self, line):
        self._cek(line)
        return dict(self.detail[line.line_code])

    async def rekam_berkas(self, line):
        self._cek(line)
        return {"line_code": line.line_code, "berkas": 2, "bytes": 1000,
                "merekam": line.line_code in self.merekam}

    async def hapus_data(self, line, *, mode, diminta_oleh):
        self._cek(line)
        if line.line_code in self.tolak_hapus:
            raise LinePlcTolak(409, '{"detail":{"kode":"truk_terpasang"}}')
        self.perintah.append(("hapus_data", line.line_code))
        self.hidup_sisa[line.line_code] = 2  # masih menjawab dua kali, lalu mati
        return {"status": "menghapus"}

    async def rekam_hapus(self, line):
        self._cek(line)
        if line.line_code in self.merekam:
            raise LinePlcTolak(409, '{"detail":{"kode":"sedang_merekam"}}')
        self.perintah.append(("rekam_hapus", line.line_code))
        return {"line_code": line.line_code, "berkas": 2, "bytes": 1000}

    async def restart(self, line):
        self._cek(line)
        self.perintah.append(("restart", line.line_code))

    async def hidup(self, line):
        if self.saat_hidup_dicek:
            self.saat_hidup_dicek(line)
        sisa = self.hidup_sisa.get(line.line_code, 0)
        if sisa > 0:
            self.hidup_sisa[line.line_code] = sisa - 1
            return True
        return False


def isi_data(store: ConsoleStore) -> None:
    with store._lock, store._db:
        store._db.execute(
            "INSERT INTO inspections (event_id, machine_id, line_code, work_date, timestamp, "
            "ripeness_status, capture_type, received_at) VALUES ('e1', 'm-1', 'line-1', "
            "'2026-09-25', '2026-09-25T01:00:00Z', 'ACC', 'auto', ?)", (time.time(),),
        )
        store._db.execute("INSERT INTO trucks (id, plate_number) VALUES ('t1', 'B1234XY')")
    store.set_state("setelan_grading", '{"conf_threshold": 0.6}')
    oid = store.upsert_operator_manual(
        {"email": "ani@pks.id", "full_name": "Ani", "password_hash": HASH}
    )
    store.create_session("tok", oid, now=time.time(), ttl_s=3600)


def hitung(store: ConsoleStore, tabel: str) -> int:
    with store._lock:
        return store._db.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]
