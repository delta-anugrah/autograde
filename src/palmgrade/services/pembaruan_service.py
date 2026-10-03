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
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..domain.pembaruan import (
    KeadaanPembaruan,
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
        #: Held by the install route AND the assign-truck route, so a truck cannot be
        #: assigned between "no truck on any line" and the marker landing on disk.
        self.kunci = asyncio.Lock()

    def _baca(self, nama: str) -> str | None:
        try:
            return (self._folder / nama).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("Berkas pembaruan %s tidak terbaca: %s", nama, exc)
            return None

    def keadaan(self) -> KeadaanPembaruan:
        return keadaan_pembaruan(
            urai_status(self._baca(STATUS)),
            urai_permintaan(self._baca(PERMINTAAN)),
            urai_hasil(self._baca(HASIL)),
            self._versi_jalan(),
            self._jam(),
        )

    def sedang_berjalan(self) -> bool:
        return self.keadaan().berjalan

    def pasang(self, target: str, bertruk: list[str], oleh: str) -> dict:
        with self._tulis:
            boleh_pasang(self.keadaan(), target, bertruk)
            id_ = self._buat_id()
            self._tulis_atomik(PERMINTAAN, isi_permintaan(id_, target, oleh, self._jam()))
        logger.info("Pembaruan %s diminta oleh %s (id %s)", target, oleh, id_)
        return {"id": id_, "target": target}

    def _tulis_atomik(self, nama: str, isi: dict) -> None:
        sementara = self._folder / f".{nama}.{uuid.uuid4().hex}.tmp"
        sementara.write_text(json.dumps(isi), encoding="utf-8")
        os.replace(sementara, self._folder / nama)
