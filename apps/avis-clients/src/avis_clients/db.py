"""Accès SQLite : une connexion par requête web ou par job, migrations au démarrage."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.db import connect, migrate

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DEFAULT_TIMEZONE = "Europe/Paris"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_iso(value: str | None) -> str | None:
    """Ramène un horodatage (RFC 3339 Google avec « Z » et millisecondes, ou ISO) au format commun `now_iso()`."""
    dt = parse_iso(value)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else value


def local_tz(name: str | None = None) -> tzinfo:
    """Fuseau métier (défaut Europe/Paris) ; repli sur UTC si la base de fuseaux est absente."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("fuseau horaire %s introuvable : UTC utilisé", name)
        return timezone.utc


def local_month(now: datetime | None = None, tz_name: str | None = None) -> str:
    """Mois courant (AAAA-MM) dans le fuseau métier, pas en UTC."""
    return (now or utcnow()).astimezone(local_tz(tz_name)).strftime("%Y-%m")


def month_bounds_utc(month: str, tz_name: str | None = None) -> tuple[str, str]:
    """Bornes [début, fin[ du mois `AAAA-MM` du fuseau métier, en ISO UTC comparable aux colonnes de la base."""
    year, m = int(month[:4]), int(month[5:7])
    tz = local_tz(tz_name)
    start = datetime(year, m, 1, tzinfo=tz)
    end = datetime(year + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(year, m + 1, 1, tzinfo=tz)
    fmt = lambda d: d.astimezone(timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    return fmt(start), fmt(end)


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
