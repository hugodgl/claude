"""Ouverture de la base SQLite de l'app avec migrations."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from core.db import connect, migrate

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn, MIGRATIONS_DIR)
    return conn


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
