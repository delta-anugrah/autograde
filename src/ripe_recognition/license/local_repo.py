from __future__ import annotations

import hashlib
import time
from pathlib import Path

import aiosqlite

from .types import LocalState


class LicenseLocalRepo:
    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS license_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    token_jws TEXT,
                    last_sync_at INTEGER,
                    max_seen_server_time INTEGER NOT NULL DEFAULT 0,
                    hash_chain_prev TEXT,
                    hash_chain_curr TEXT
                )
            """)
            await db.execute(
                "INSERT OR IGNORE INTO license_state (id) VALUES (1)"
            )
            await db.commit()

    async def read(self) -> LocalState:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM license_state WHERE id=1") as cur:
                row = await cur.fetchone()
        if not row:
            return LocalState(None, None, 0, None, None)
        return LocalState(
            token_jws=row["token_jws"],
            last_sync_at=row["last_sync_at"],
            max_seen_server_time=int(row["max_seen_server_time"] or 0),
            hash_chain_prev=row["hash_chain_prev"],
            hash_chain_curr=row["hash_chain_curr"],
        )

    def _next_hash(self, prev: str | None, token: str, ts: int) -> str:
        h = hashlib.sha256()
        h.update((prev or "").encode())
        h.update(b"|")
        h.update(token.encode())
        h.update(b"|")
        h.update(str(ts).encode())
        return h.hexdigest()

    async def write_token(self, token_jws: str, server_time: int) -> None:
        now = int(time.time())
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT hash_chain_curr FROM license_state WHERE id=1"
            ) as cur:
                row = await cur.fetchone()
            prev = row["hash_chain_curr"] if row else None
            curr = self._next_hash(prev, token_jws, now)
            await db.execute(
                """UPDATE license_state
                   SET token_jws=?, last_sync_at=?, hash_chain_prev=?, hash_chain_curr=?,
                       max_seen_server_time=MAX(max_seen_server_time, ?)
                   WHERE id=1""",
                (token_jws, now, prev, curr, server_time),
            )
            await db.commit()
