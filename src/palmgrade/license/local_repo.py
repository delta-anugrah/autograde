from __future__ import annotations

from pathlib import Path

import aiosqlite


class LicenseLocalRepo:
    """Penanda batas atas jam mesin ini — satu angka, satu baris SQLite.

    Dulu repo ini juga menyimpan token JWS + rantai hash anti-tamper. Token
    sekarang datang dari env (`LICENSE_TOKEN`) dan sudah bertanda tangan
    Ed25519: menyalinnya ke SQLite tidak menambah keamanan apa pun, cuma bikin
    dua sumber kebenaran yang bisa berbeda.

    Yang tersisa justru bagian yang tidak bisa dititipkan ke token: detik Unix
    tertinggi yang pernah dilihat mesin ini. Tanpa ini, seluruh sistem
    langganan bisa dijebol cukup dengan memundurkan tanggal di BIOS.

    File lama tetap terbaca apa adanya — `CREATE TABLE IF NOT EXISTS` tidak
    menyentuh tabel yang sudah ada, dan kolom yang kita baca tidak berubah nama.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS license_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    max_seen_server_time INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.execute("INSERT OR IGNORE INTO license_state (id) VALUES (1)")
            await db.commit()

    async def read_max_seen(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT max_seen_server_time FROM license_state WHERE id=1"
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] else 0

    async def ratchet(self, now: int) -> int:
        """Naikkan penanda ke `now` kalau lebih besar. Kembalikan nilai final."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE license_state
                   SET max_seen_server_time = MAX(max_seen_server_time, ?)
                   WHERE id=1""",
                (now,),
            )
            await db.commit()
        return await self.read_max_seen()
