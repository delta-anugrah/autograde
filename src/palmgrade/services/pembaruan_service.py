"""Batch 4.6: the console's half of "Update now". Reads and writes three small files in
UPDATE_DIR; the rules live in `domain/pembaruan.py`. Never Docker: the host watcher
does the install, this only leaves a marker for it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from ..domain.pembaruan import (
    KeadaanPembaruan,
    PembaruanBerjalan,
    baris_log_hasil,
    boleh_pasang,
    isi_permintaan,
    keadaan_pembaruan,
    urai_hasil,
    urai_permintaan,
    urai_status,
)

logger = logging.getLogger(__name__)

STATUS = "status.json"
PERMINTAAN = "request.json"
HASIL = "result.json"
#: Console-private: which outcome is already in the Log tab. On disk, not only in memory,
#: because the install restarts the console and the new process reads the same result.json.
TERCATAT = ".result-logged.json"


class PembaruanService:
    def __init__(
        self,
        folder: Path,
        versi_jalan: Callable[[], str],
        jam: Callable[[], datetime],
        buat_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._folder = folder
        self._versi_jalan = versi_jalan
        self._jam = jam
        self._buat_id = buat_id
        self._tulis = threading.Lock()
        self._catat = threading.Lock()
        self._tercatat: str | None = None
        #: Held by the install route for the whole check-and-write, and by an assign only
        #: long enough to register itself in `_ditugaskan`: no truck can slip in between
        #: "no truck on any line" and the marker landing, and no assign waits behind another
        #: line's network call (a dead line answers after 10 s).
        self.kunci = asyncio.Lock()
        self._ditugaskan: Counter[str] = Counter()

    def _baca(self, nama: str) -> str | None:
        try:
            return (self._folder / nama).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("Berkas pembaruan %s tidak terbaca: %s", nama, exc)
            return None

    def keadaan(self) -> KeadaanPembaruan:
        keadaan = keadaan_pembaruan(
            urai_status(self._baca(STATUS)),
            urai_permintaan(self._baca(PERMINTAAN)),
            urai_hasil(self._baca(HASIL)),
            self._versi_jalan(),
            self._jam(),
        )
        self._catat_hasil(keadaan.hasil)
        return keadaan

    def _catat_hasil(self, hasil: dict | None) -> None:
        """Log a final outcome once (user decision 2026-10-02: screen and Log tab only)."""
        baris = baris_log_hasil(hasil)
        if baris is None:
            return
        kunci = f"{hasil['state']}|{hasil['target']}|{hasil['at']}"
        with self._catat:
            if self._tercatat == kunci or self._kunci_tercatat_di_disk() == kunci:
                self._tercatat = kunci
                return
            level, pesan = baris
            logger.log(logging.getLevelName(level), pesan)
            self._tercatat = kunci
            try:
                self._tulis_atomik(TERCATAT, {"kunci": kunci})
            except OSError as exc:
                # Memory still stops a repeat in this process; a restart may log it once more.
                logger.warning("Catatan hasil pembaruan tidak tertulis: %s", exc)

    def _kunci_tercatat_di_disk(self) -> str | None:
        isi = self._baca(TERCATAT)
        try:
            data = json.loads(isi) if isi else None
        except ValueError:
            return None
        return data.get("kunci") if isinstance(data, dict) else None

    def sedang_berjalan(self) -> bool:
        return self.keadaan().berjalan

    @asynccontextmanager
    async def menugaskan(self, line_code: str) -> AsyncIterator[None]:
        """Wrap an assign: refused while an install runs, visible to install until it ends."""
        async with self.kunci:
            if await asyncio.to_thread(self.sedang_berjalan):
                raise PembaruanBerjalan()
            self._ditugaskan[line_code] += 1
        try:
            yield
        finally:
            self._ditugaskan[line_code] -= 1
            if self._ditugaskan[line_code] <= 0:
                del self._ditugaskan[line_code]

    def line_sedang_ditugaskan(self) -> list[str]:
        """Lines whose assign is still waiting for the line to answer."""
        return sorted(self._ditugaskan)

    def pasang(self, target: str, bertruk: list[str], oleh: str) -> dict:
        with self._tulis:
            boleh_pasang(self.keadaan(), target, bertruk)
            id_ = self._buat_id()
            self._tulis_atomik(PERMINTAAN, isi_permintaan(id_, target, oleh, self._jam()))
        # WARNING, not INFO: the Log tab stores WARNING and above, and who pressed it matters
        # there (same as the piston button).
        logger.warning("Pembaruan %s diminta oleh %s dari konsol (id %s)", target, oleh, id_)
        return {"id": id_, "target": target}

    def _tulis_atomik(self, nama: str, isi: dict) -> None:
        sementara = self._folder / f".{nama}.{uuid.uuid4().hex}.tmp"
        sementara.write_text(json.dumps(isi), encoding="utf-8")
        os.replace(sementara, self._folder / nama)
