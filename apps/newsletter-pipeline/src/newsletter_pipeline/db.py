"""Accès SQLite : ouverture + migrations via le socle, puis petites fonctions de dépôt."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.db import connect, migrate

from .settings import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def open_db(settings: Settings) -> sqlite3.Connection:
    conn = connect(settings.db_path)
    migrate(conn, MIGRATIONS_DIR)
    return conn


# ------------------------------------------------------------------ sources
def upsert_source(conn: sqlite3.Connection, spec: dict[str, Any]) -> int:
    now = now_iso()
    patterns = json.dumps(spec.get("include_patterns") or [], ensure_ascii=False)
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (spec["name"],)).fetchone()
    with conn:
        if row:
            conn.execute(
                """UPDATE sources SET url = ?, kind = ?, category = ?, lang = ?, weight = ?, active = ?,
                   verify = ?, include_patterns = ?, updated_at = ? WHERE id = ?""",
                (spec["url"], spec["kind"], spec["category"], spec["lang"], spec["weight"],
                 int(spec["active"]), int(spec["verify"]), patterns, now, row["id"]),
            )
            return int(row["id"])
        cur = conn.execute(
            """INSERT INTO sources (name, url, kind, category, lang, weight, active, verify, include_patterns,
                                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (spec["name"], spec["url"], spec["kind"], spec["category"], spec["lang"], spec["weight"],
             int(spec["active"]), int(spec["verify"]), patterns, now, now),
        )
        return int(cur.lastrowid)


def list_sources(conn: sqlite3.Connection, *, active_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM sources"
    if active_only:
        sql += " WHERE active = 1"
    return conn.execute(sql + " ORDER BY category, name").fetchall()


def get_source(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()


def mark_source_fetched(conn: sqlite3.Connection, source_id: int, error: str | None) -> None:
    with conn:
        conn.execute(
            "UPDATE sources SET last_fetched_at = ?, last_error = ?, updated_at = ? WHERE id = ?",
            (now_iso(), error[:500] if error else None, now_iso(), source_id),
        )


# ------------------------------------------------------------------ items
def item_exists(conn: sqlite3.Connection, url: str, title_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM items WHERE url = ? OR title_hash = ? LIMIT 1", (url, title_hash)
    ).fetchone()
    return row is not None


def insert_item(conn: sqlite3.Connection, source_id: int, item: dict[str, Any]) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO items (source_id, url, title, title_hash, published_at, author, summary,
                                  content_text, content_hash, fetched_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
            (source_id, item["url"], item["title"], item["title_hash"], item.get("published_at"),
             item.get("author"), item.get("summary"), item.get("content_text"), item.get("content_hash"),
             now_iso()),
        )
        return int(cur.lastrowid)


def unscored_items(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT i.*, s.name AS source_name, s.weight AS source_weight, s.category AS source_category
           FROM items i JOIN sources s ON s.id = i.source_id
           WHERE i.status = 'new' AND i.score IS NULL
           ORDER BY i.fetched_at DESC, i.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def update_item_score(conn: sqlite3.Connection, item_id: int, score: float, score_json: dict[str, Any],
                      theme: str) -> None:
    with conn:
        conn.execute(
            "UPDATE items SET score = ?, score_json = ?, theme = ? WHERE id = ?",
            (score, json.dumps(score_json, ensure_ascii=False), theme, item_id),
        )


def candidate_items(conn: sqlite3.Connection, *, min_published: str | None = None) -> list[sqlite3.Row]:
    """Items classés, encore disponibles (new ou selected), les mieux notés d'abord."""
    sql = """SELECT i.*, s.name AS source_name, s.category AS source_category
             FROM items i JOIN sources s ON s.id = i.source_id
             WHERE i.score IS NOT NULL AND i.status IN ('new', 'selected')"""
    params: list[Any] = []
    if min_published:
        sql += " AND (i.published_at IS NULL OR i.published_at >= ?)"
        params.append(min_published)
    sql += " ORDER BY i.score DESC, i.published_at DESC, i.id DESC"
    return conn.execute(sql, params).fetchall()


def set_items_status(conn: sqlite3.Connection, ids: list[int], status: str,
                     issue_number: int | None = None) -> None:
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    with conn:
        if issue_number is None:
            conn.execute(f"UPDATE items SET status = ? WHERE id IN ({marks})", (status, *ids))
        else:
            conn.execute(
                f"UPDATE items SET status = ?, used_in_issue = ? WHERE id IN ({marks})",
                (status, issue_number, *ids),
            )


def get_items(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT i.*, s.name AS source_name FROM items i JOIN sources s ON s.id = i.source_id
            WHERE i.id IN ({marks})""",
        ids,
    ).fetchall()
    order = {item_id: pos for pos, item_id in enumerate(ids)}
    return sorted(rows, key=lambda r: order[r["id"]])


# ------------------------------------------------------------------ issues
def save_issue(conn: sqlite3.Connection, number: int, **fields: Any) -> None:
    now = now_iso()
    existing = conn.execute("SELECT number FROM issues WHERE number = ?", (number,)).fetchone()
    if "item_ids" in fields and not isinstance(fields["item_ids"], str):
        fields["item_ids"] = json.dumps(fields["item_ids"])
    if "content_json" in fields and not isinstance(fields["content_json"], str):
        fields["content_json"] = json.dumps(fields["content_json"], ensure_ascii=False)
    with conn:
        if existing:
            sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
            conn.execute(f"UPDATE issues SET {sets} WHERE number = ?", (*fields.values(), now, number))
        else:
            cols = ["number", *fields.keys(), "created_at", "updated_at"]
            marks = ",".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO issues ({', '.join(cols)}) VALUES ({marks})",
                (number, *fields.values(), now, now),
            )


def get_issue(conn: sqlite3.Connection, number: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM issues WHERE number = ?", (number,)).fetchone()


def last_issue_number(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(number) AS n FROM issues").fetchone()
    return int(row["n"] or 0)


def list_issues(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM issues ORDER BY number").fetchall()
