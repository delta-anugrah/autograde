"""Bridge from `logging` to `LogStore`, so a fault outlives a restart.

The common story at a mill is "it errored, I restarted, it's fine now" — and
that is exactly when `docker logs` is already empty. This handler is what
keeps the trace around for whoever finally gets in over AnyDesk.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from typing import Any, Protocol

from ..domain.log_redaksi import redact

_STORED_LEVELS = frozenset({"ERROR", "CRITICAL", "WARNING"})


class _LogSink(Protocol):
    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None: ...


class SqliteLogHandler(logging.Handler):
    """Write ERROR/WARNING to a `LogStore`-shaped sink. Never raises to the caller."""

    def __init__(self, store: _LogSink, *, now: Any = time.time) -> None:
        super().__init__(level=logging.WARNING)
        self._store = store
        self._now = now
        self._already_complained = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelname not in _STORED_LEVELS:
            return
        try:
            detail = self._format_exception(record) if record.exc_info else None
            self._store.write(
                "ERROR" if record.levelname == "CRITICAL" else record.levelname,
                record.name,
                redact(record.getMessage()),
                redact(detail) if detail else None,
                now=self._now(),
            )
        except Exception:
            # Swallowed on purpose: a line must not die because its logging aid
            # failed. Complained once to stderr so a permanent failure still
            # shows in `docker logs` instead of going silent forever.
            if not self._already_complained:
                self._already_complained = True
                print(
                    "event log could not be written; the Log screen will stay empty",
                    file=sys.stderr,
                )

    @staticmethod
    def _format_exception(record: logging.LogRecord) -> str:
        return "".join(traceback.format_exception(*record.exc_info))


def install_log_sink(store: _LogSink) -> SqliteLogHandler:
    """Attach the handler to the root logger. Returns it so a test can detach it."""
    handler = SqliteLogHandler(store)
    logging.getLogger().addHandler(handler)
    return handler
