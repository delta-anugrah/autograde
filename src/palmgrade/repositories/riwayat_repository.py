"""Query tab Riwayat: grading lintas hari, baca saja, di koneksi SQLite sendiri.

Kenapa bukan `ConsoleStore`: kelas itu memegang SATU koneksi di balik SATU lock,
dan setiap janjang yang dikirim line menunggu lock itu. Riwayat sebulan bisa
memindai jutaan baris; di balik lock yang sama, ingest janjang dari tiga line
tertahan berdetik-detik. SQLite mode WAL membiarkan pembaca dan penulis jalan
bersamaan, jadi di sini tiap panggilan membuka koneksi baca-saja sendiri dan
tidak pernah menyentuh lock konsol. Rute yang memakainya `def` (thread pool),
jadi loop yang melayani layar dan line juga tidak ikut menunggu.

Hitungannya sengaja SAMA PERSIS dengan `ConsoleStore.summary`/`truck_recap`
(verdict dari `ripeness_status`, kelas dari `grade_class`, TP = `tp_confidence >
0.8`): satu hari di tab ini harus sama dengan tab Rekap hari itu, dan operator
akan membandingkan keduanya.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..domain.plate import normalisasi_plat
from ..domain.riwayat import ANGKA as _ANGKA
from ..domain.riwayat import FilterRiwayat
from .console_repository import SOURCE_FACTS

_HASIL_SQL = {
    "ripe": "i.grade_class = 'Ripe'",
    "unripe": "i.grade_class = 'Unripe'",
    "jk": "i.grade_class = 'JK'",
    "tp": "i.tp_confidence > 0.8",
}

_HITUNG = """COUNT(*) AS total,
    SUM(CASE WHEN i.ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
    SUM(CASE WHEN i.ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
    SUM(CASE WHEN i.grade_class = 'Ripe'   THEN 1 ELSE 0 END) AS ripe,
    SUM(CASE WHEN i.grade_class = 'Unripe' THEN 1 ELSE 0 END) AS unripe,
    SUM(CASE WHEN i.grade_class = 'JK'     THEN 1 ELSE 0 END) AS jk,
    SUM(CASE WHEN i.grade_class IS NULL THEN 1 ELSE 0 END) AS tanpa_kelas,
    SUM(CASE WHEN i.tp_confidence > 0.8 THEN 1 ELSE 0 END) AS tp"""


# Kolom janjang yang dibaca layar dan CSV, disebut satu per satu: `erp_state`
# dan kolom yang kelak ditambah tidak ikut keluar sebagai JSON tanpa sengaja.
_KOLOM_JANJANG = """i.event_id, i.line_code, i.work_date, i.timestamp, i.ripeness_status,
    i.grade_class, i.tp_confidence, i.capture_type, i.image_path, i.truck_id,
    t.plate_number, s.name AS supplier_name, """ + SOURCE_FACTS

_JOIN_TRUK = """LEFT JOIN trucks t ON t.id = i.truck_id
    LEFT JOIN suppliers s ON s.id = t.supplier_id"""

# Baris per putaran `fetchmany` saat CSV dialirkan: cukup besar supaya tidak
# bolak-balik, cukup kecil supaya sebulan data tidak pernah utuh di memori.
_POTONG = 500


def _angka(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """SUM atas nol baris adalah NULL; layar dan CSV butuh nol."""
    hasil = dict(row)
    for kolom in _ANGKA:
        if kolom in hasil:
            hasil[kolom] = int(hasil[kolom] or 0)
    return hasil


class RiwayatStore:
    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)

    @contextmanager
    def _baca(self) -> Iterator[sqlite3.Connection]:
        """Koneksi baca-saja baru. `check_same_thread=False`: CSV dialirkan
        Starlette lewat thread pool, dan potongan berikutnya bisa diminta dari
        thread lain. Aman, karena satu koneksi cuma pernah dibaca satu pengalir."""
        db = sqlite3.connect(
            f"{self._path.resolve().as_uri()}?mode=ro", uri=True, timeout=10,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    # ------------------------------------------------------------ saringan

    @staticmethod
    def _truk_cocok(db: sqlite3.Connection, fragmen: str) -> list[str]:
        """Id truk yang platnya (dinormalkan) memuat potongan itu.

        Dicocokkan di Python dengan `normalisasi_plat`, aturan yang sama dengan
        timbangan dan scan QR: SQLite tidak punya regex, dan `REPLACE` berlapis
        di SQL akan jadi aturan kedua yang bisa berbeda diam-diam.
        """
        cocok = []
        for row in db.execute("SELECT id, plate_number FROM trucks"):
            try:
                if fragmen in normalisasi_plat(row["plate_number"] or ""):
                    cocok.append(row["id"])
            except ValueError:
                continue
        return cocok

    def _saring(
        self, db: sqlite3.Connection, f: FilterRiwayat, *, pakai_hasil: bool, kolom_truk: str
    ) -> tuple[str, list[Any]]:
        """Klausa WHERE yang sama untuk halaman, hitungannya, dan CSV.

        Dibangun sekali dan dipakai bersama: hitungan yang menyaring beda dengan
        barisnya menghasilkan "halaman 4 dari 1".
        """
        where = ["i.work_date BETWEEN ? AND ?"]
        params: list[Any] = [f.dari, f.sampai]
        if f.line_code:
            where.append("i.line_code = ?")
            params.append(f.line_code)
        if f.plat:
            ids = self._truk_cocok(db, f.plat)
            if not ids:
                where.append("0")
            else:
                where.append(f"{kolom_truk} IN ({','.join('?' * len(ids))})")
                params += ids
        if pakai_hasil and f.hasil:
            where.append(_HASIL_SQL[f.hasil])
        return " AND ".join(where), params

    def _neto(
        self, db: sqlite3.Connection, f: FilterRiwayat, *, per: str
    ) -> dict[Any, float | None]:
        """Neto timbangan per hari (`per="hari"`) atau per (hari, truk).

        Dijumlah di query sendiri lalu disandingkan di Python, bukan di-JOIN ke
        query janjang: satu truk bisa punya dua tiket sehari, dan JOIN itu
        mengalikan janjang dengan tiket (aturan 17). Tiket yang belum timbang
        keluar tidak punya neto dan tidak dihitung nol.
        """
        where = ["w.work_date BETWEEN ? AND ?"]
        params: list[Any] = [f.dari, f.sampai]
        if f.plat:
            ids = self._truk_cocok(db, f.plat)
            if not ids:
                return {}
            where.append(f"w.truck_id IN ({','.join('?' * len(ids))})")
            params += ids
        kunci = "w.work_date" if per == "hari" else "w.work_date, w.truck_id"
        rows = db.execute(
            f"""SELECT {kunci}, SUM(w.net_kg) AS neto FROM weighings w
                WHERE {' AND '.join(where)} GROUP BY {kunci}""",
            params,
        ).fetchall()
        if per == "hari":
            return {r["work_date"]: r["neto"] for r in rows}
        return {(r["work_date"], r["truck_id"]): r["neto"] for r in rows}

    # ------------------------------------------------- per hari + ringkasan

    def _hari(self, db: sqlite3.Connection, f: FilterRiwayat) -> list[dict[str, Any]]:
        """Satu baris per hari kerja, terbaru dulu. Paling banyak 31 baris.

        Ringkasan periode dijumlah dari baris ini, bukan query kedua: satu pindaian
        rentang, bukan dua. `truk` = truk berbeda per hari, jadi jumlahnya sama
        dengan jumlah kunjungan (hari, truk) di periode itu.
        """
        where, params = self._saring(db, f, pakai_hasil=False, kolom_truk="i.truck_id")
        rows = [
            _angka(r)
            for r in db.execute(
                f"""SELECT i.work_date, {_HITUNG}, COUNT(DISTINCT i.truck_id) AS truk
                    FROM inspections i WHERE {where}
                    GROUP BY i.work_date ORDER BY i.work_date DESC""",
                params,
            )
        ]
        for row in rows:
            row["truk"] = int(row.get("truk") or 0)
            row["neto_kg"] = None
        # Neto itu berat truk, bukan milik satu line: disaring per line, angkanya bohong.
        if f.line_code:
            return rows
        neto = self._neto(db, f, per="hari")
        ada = {row["work_date"] for row in rows}
        for row in rows:
            row["neto_kg"] = neto.get(row["work_date"])
        # Hari dengan tiket timbang tapi nol janjang tetap satu baris: kamera mati
        # seharian justru yang perlu terlihat, dan jumlah baris harus sama dengan
        # ringkasannya.
        rows += [
            {"work_date": hari, **dict.fromkeys(_ANGKA, 0), "truk": 0, "neto_kg": nilai}
            for hari, nilai in neto.items()
            if hari not in ada
        ]
        rows.sort(key=lambda r: r["work_date"], reverse=True)
        return rows

    def hari(self, f: FilterRiwayat) -> list[dict[str, Any]]:
        """Semua hari di rentang, terbaru dulu (paling banyak 31 baris), jadi dikirim
        utuh dan tidak perlu dibagi halaman di server."""
        with self._baca() as db:
            return self._hari(db, f)

    # --------------------------------------------------------------- per truk

    def truk(self, f: FilterRiwayat) -> list[dict[str, Any]]:
        """Satu baris per (hari, truk), terbaru dulu, dengan neto hari itu.

        Dikirim utuh, dibagi halaman di layar: sebulan paling banyak beberapa ribu
        baris, sedangkan mengelompokkan ulang sebulan janjang untuk tiap klik
        halaman makan detik (terukur ~2 dtk untuk 620 ribu janjang).

        Dikelompokkan seperti `truck_recap` per hari: janjang sebelum truk dipasang
        jadi satu baris tanpa nama, tidak dibuang. Dikelompokkan DULU, baru
        digabung ke truk dan supplier: gabungan per janjang berarti jutaan
        pencarian untuk sebulan, per kelompok cuma ratusan.
        """
        with self._baca() as db:
            where, params = self._saring(db, f, pakai_hasil=False, kolom_truk="i.truck_id")
            rows = [
                _angka(r)
                for r in db.execute(
                    f"""SELECT g.*, t.plate_number, s.name AS supplier_name, {SOURCE_FACTS}
                        FROM (SELECT i.work_date, i.truck_id, {_HITUNG},
                                     MIN(i.timestamp) AS mulai, MAX(i.timestamp) AS selesai
                              FROM inspections i WHERE {where}
                              GROUP BY i.work_date, i.truck_id) g
                        LEFT JOIN trucks t ON t.id = g.truck_id
                        LEFT JOIN suppliers s ON s.id = t.supplier_id
                        ORDER BY g.work_date DESC, g.selesai DESC""",
                    params,
                )
            ]
            neto = self._neto(db, f, per="truk")
        for row in rows:
            row["neto_kg"] = neto.get((row["work_date"], row["truck_id"])) if row["truck_id"] else None
        return rows

    # ------------------------------------------------------------ per janjang

    def _sql_janjang(self, where: str) -> str:
        # `work_date DESC, timestamp DESC`, bukan `timestamp DESC` saja: urutan
        # pertama ikut indeks (work_date, ...), jadi halaman pertama cuma perlu
        # mengurutkan janjang hari terakhir, bukan sebulan penuh.
        return f"""SELECT {_KOLOM_JANJANG}
                   FROM inspections i {_JOIN_TRUK}
                   WHERE {where}
                   ORDER BY i.work_date DESC, i.timestamp DESC"""

    def janjang(
        self, f: FilterRiwayat, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self._baca() as db:
            where, params = self._saring(db, f, pakai_hasil=True, kolom_truk="i.truck_id")
            total = db.execute(
                f"SELECT COUNT(*) FROM inspections i WHERE {where}", params
            ).fetchone()[0]
            rows = [
                dict(r)
                for r in db.execute(self._sql_janjang(where) + " LIMIT ? OFFSET ?", [*params, limit, offset])
            ]
        return rows, int(total)

    def semua_janjang(self, f: FilterRiwayat) -> Iterator[dict[str, Any]]:
        with self._baca() as db:
            where, params = self._saring(db, f, pakai_hasil=True, kolom_truk="i.truck_id")
            kursor = db.execute(self._sql_janjang(where), params)
            while potong := kursor.fetchmany(_POTONG):
                for r in potong:
                    yield dict(r)
