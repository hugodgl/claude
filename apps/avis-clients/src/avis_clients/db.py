"""Accès SQLite : une connexion par requête web ou par job, migrations au démarrage."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.db import connect, migrate

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def migrate(self) -> list[str]:
        conn = self.connect()
        try:
            return migrate(conn, MIGRATIONS_DIR)
        finally:
            conn.close()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def log_event(
    conn: sqlite3.Connection,
    kind: str,
    *,
    account_id: int | None = None,
    establishment_id: int | None = None,
    **payload: Any,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO events (account_id, establishment_id, kind, payload_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (account_id, establishment_id, kind, json.dumps(payload, ensure_ascii=False, default=str),
             now_iso()),
        )
