"""Accès SQLite : connexion + migrations, et requêtes du domaine (avis, abonnés, résumés, envois, attributions)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.db import connect, migrate

from .dates import parse_dt, to_iso, utcnow
from .models import Award, LLMSummary, Notice, Subscriber

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn, MIGRATIONS_DIR)
    return conn


def _loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


# --------------------------------------------------------------------------------------------
# Avis
# --------------------------------------------------------------------------------------------
def row_to_notice(row: sqlite3.Row) -> Notice:
    return Notice(
        id=row["id"],
        source=row["source"],
        source_id=row["source_id"],
        title=row["title"],
        buyer_name=row["buyer_name"],
        buyer_dept=row["buyer_dept"],
        departments=_loads(row["departments"], []),
        cpv_codes=_loads(row["cpv_codes"], []),
        description=row["description"],
        estimated_amount=row["estimated_amount"],
        published_at=parse_dt(row["published_at"]),
        deadline_at=parse_dt(row["deadline_at"]),
        procedure_type=row["procedure_type"],
        url=row["url"],
        raw=_loads(row["raw"], {}),
    )


def upsert_notice(conn: sqlite3.Connection, n: Notice, now: datetime | None = None) -> bool:
    """Insère l'avis ; s'il existe déjà (source + id), met à jour les champs normalisés. Retourne True si inséré."""
    existing = conn.execute(
        "SELECT id FROM notices WHERE source = ? AND source_id = ?", (n.source, n.source_id)
    ).fetchone()
    values = (
        n.title, n.buyer_name, n.buyer_dept, json.dumps(n.departments), json.dumps(n.cpv_codes),
        n.description, n.estimated_amount, to_iso(n.published_at), to_iso(n.deadline_at),
        n.procedure_type, n.url, n.raw_json(),
    )
    with conn:
        if existing:
            conn.execute(
                "UPDATE notices SET title=?, buyer_name=?, buyer_dept=?, departments=?, cpv_codes=?, description=?,"
                " estimated_amount=?, published_at=?, deadline_at=?, procedure_type=?, url=?, raw=? WHERE id=?",
                (*values, existing["id"]),
            )
            n.id = existing["id"]
            return False
        cur = conn.execute(
            "INSERT INTO notices (source, source_id, title, buyer_name, buyer_dept, departments, cpv_codes,"
            " description, estimated_amount, published_at, deadline_at, procedure_type, url, raw, collected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (n.source, n.source_id, *values, (now or utcnow()).isoformat()),
        )
        n.id = cur.lastrowid
        return True


def get_notice(conn: sqlite3.Connection, notice_id: int) -> Notice | None:
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return row_to_notice(row) if row else None


def list_notices(conn: sqlite3.Connection, *, since: datetime | None = None, limit: int | None = None,
                 source: str | None = None) -> list[Notice]:
    sql = "SELECT * FROM notices WHERE 1=1"
    params: list[Any] = []
    if since is not None:
        sql += " AND (published_at IS NULL OR published_at >= ?)"
        params.append(since.isoformat())
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY published_at DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [row_to_notice(r) for r in conn.execute(sql, params)]


def notices_without_summary(conn: sqlite3.Connection, *, since: datetime | None = None,
                            limit: int | None = None) -> list[Notice]:
    sql = ("SELECT n.* FROM notices n LEFT JOIN summaries s ON s.notice_id = n.id"
           " WHERE s.id IS NULL")
    params: list[Any] = []
    if since is not None:
        sql += " AND (n.published_at IS NULL OR n.published_at >= ?)"
        params.append(since.isoformat())
    sql += " ORDER BY n.published_at DESC, n.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [row_to_notice(r) for r in conn.execute(sql, params)]


def notices_with_fallback_summary(conn: sqlite3.Connection, *, since: datetime | None = None,
                                  limit: int | None = None) -> list[Notice]:
    """Avis déjà en base dont le résumé a été produit sans LLM (aucun abonné ne correspondait à l'époque)."""
    sql = "SELECT n.* FROM notices n JOIN summaries s ON s.notice_id = n.id WHERE s.llm_provider = 'none'"
    params: list[Any] = []
    if since is not None:
        sql += " AND (n.published_at IS NULL OR n.published_at >= ?)"
        params.append(since.isoformat())
    sql += " ORDER BY n.published_at DESC, n.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [row_to_notice(r) for r in conn.execute(sql, params)]


def buyer_notice_count(conn: sqlite3.Connection, buyer_name: str | None, exclude_id: int | None = None) -> int:
    if not buyer_name:
        return 0
    sql = "SELECT COUNT(*) AS c FROM notices WHERE lower(buyer_name) = lower(?)"
    params: list[Any] = [buyer_name]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return int(conn.execute(sql, params).fetchone()["c"])


def buyer_award_count(conn: sqlite3.Connection, buyer_name: str | None) -> int:
    if not buyer_name:
        return 0
    return int(conn.execute("SELECT COUNT(*) AS c FROM awards WHERE lower(buyer_name) = lower(?)",
                            (buyer_name,)).fetchone()["c"])


# --------------------------------------------------------------------------------------------
# Abonnés
# --------------------------------------------------------------------------------------------
def row_to_subscriber(row: sqlite3.Row) -> Subscriber:
    return Subscriber(
        id=row["id"], email=row["email"], label=row["label"], company=row["company"],
        cpv_prefixes=_loads(row["cpv_prefixes"], []), departments=_loads(row["departments"], []),
        amount_min=row["amount_min"], amount_max=row["amount_max"], plan=row["plan"],
        billing_period=row["billing_period"] or "monthly", active=bool(row["active"]), status=row["status"],
        stripe_customer_id=row["stripe_customer_id"], stripe_subscription_id=row["stripe_subscription_id"],
        checkout_session_id=row["checkout_session_id"], created_at=parse_dt(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]),
    )


def add_subscriber(conn: sqlite3.Connection, s: Subscriber, now: datetime | None = None) -> Subscriber:
    ts = (now or utcnow()).isoformat()
    status = s.status if s.status != "active" or s.active else "disabled"
    with conn:
        cur = conn.execute(
            "INSERT INTO subscribers (email, label, company, cpv_prefixes, departments, amount_min, amount_max, plan,"
            " billing_period, active, status, stripe_customer_id, stripe_subscription_id, checkout_session_id,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s.email.strip().lower(), s.label, s.company, json.dumps(s.cpv_prefixes), json.dumps(s.departments),
             s.amount_min, s.amount_max, s.plan, s.billing_period, int(s.active), status, s.stripe_customer_id,
             s.stripe_subscription_id, s.checkout_session_id, ts, ts),
        )
    return get_subscriber(conn, cur.lastrowid)


SUBSCRIBER_COLUMNS = {
    "label", "company", "cpv_prefixes", "departments", "amount_min", "amount_max", "plan", "billing_period",
    "active", "status", "stripe_customer_id", "stripe_subscription_id", "checkout_session_id",
}


def update_subscriber(conn: sqlite3.Connection, subscriber_id: int, now: datetime | None = None,
                      **fields: Any) -> Subscriber:
    """Met à jour les colonnes données (listes sérialisées en JSON, booléens en 0/1) et retourne l'abonné."""
    unknown = set(fields) - SUBSCRIBER_COLUMNS
    if unknown:
        raise ValueError(f"colonnes inconnues : {', '.join(sorted(unknown))}")
    if fields:
        assignments, params = [], []
        for key, value in fields.items():
            if isinstance(value, (list, tuple)):
                value = json.dumps(list(value))
            elif isinstance(value, bool):
                value = int(value)
            assignments.append(f"{key} = ?")
            params.append(value)
        assignments.append("updated_at = ?")
        params.append((now or utcnow()).isoformat())
        params.append(subscriber_id)
        with conn:
            conn.execute(f"UPDATE subscribers SET {', '.join(assignments)} WHERE id = ?", params)
    return get_subscriber(conn, subscriber_id)


def find_subscriber_by_stripe(conn: sqlite3.Connection, *, customer_id: str | None = None,
                              subscription_id: str | None = None) -> Subscriber | None:
    if subscription_id:
        row = conn.execute("SELECT * FROM subscribers WHERE stripe_subscription_id = ?", (subscription_id,)).fetchone()
        if row:
            return row_to_subscriber(row)
    if customer_id:
        row = conn.execute("SELECT * FROM subscribers WHERE stripe_customer_id = ?", (customer_id,)).fetchone()
        if row:
            return row_to_subscriber(row)
    return None


def get_subscriber_by_checkout_session(conn: sqlite3.Connection, session_id: str) -> Subscriber | None:
    if not session_id:
        return None
    row = conn.execute("SELECT * FROM subscribers WHERE checkout_session_id = ?", (session_id,)).fetchone()
    return row_to_subscriber(row) if row else None


def record_stripe_event(conn: sqlite3.Connection, event_id: str, event_type: str,
                        now: datetime | None = None) -> bool:
    """Enregistre l'identifiant d'événement ; retourne False s'il a déjà été vu (idempotence)."""
    with conn:
        cur = conn.execute("INSERT OR IGNORE INTO stripe_events (id, type, received_at) VALUES (?, ?, ?)",
                           (event_id, event_type, (now or utcnow()).isoformat()))
    return cur.rowcount > 0


def set_stripe_event_result(conn: sqlite3.Connection, event_id: str, result: str) -> None:
    with conn:
        conn.execute("UPDATE stripe_events SET result = ? WHERE id = ?", (result, event_id))


def forget_stripe_event(conn: sqlite3.Connection, event_id: str) -> None:
    """Oublie un événement dont l'application a échoué, pour que le rejeu de Stripe soit traité et non `duplicate`."""
    with conn:
        conn.execute("DELETE FROM stripe_events WHERE id = ?", (event_id,))


def get_subscriber(conn: sqlite3.Connection, subscriber_id: int) -> Subscriber:
    return row_to_subscriber(conn.execute("SELECT * FROM subscribers WHERE id = ?", (subscriber_id,)).fetchone())


def find_subscriber(conn: sqlite3.Connection, subscriber_id: int | None) -> Subscriber | None:
    if subscriber_id is None:
        return None
    row = conn.execute("SELECT * FROM subscribers WHERE id = ?", (subscriber_id,)).fetchone()
    return row_to_subscriber(row) if row else None


def get_subscriber_by_email(conn: sqlite3.Connection, email: str) -> Subscriber | None:
    row = conn.execute("SELECT * FROM subscribers WHERE email = ?", (email.strip().lower(),)).fetchone()
    return row_to_subscriber(row) if row else None


def list_subscribers(conn: sqlite3.Connection, *, active_only: bool = False,
                     with_stripe_subscription: bool = False) -> list[Subscriber]:
    sql = "SELECT * FROM subscribers WHERE 1=1"
    if active_only:
        sql += " AND active = 1"
    if with_stripe_subscription:
        sql += " AND stripe_subscription_id IS NOT NULL"
    sql += " ORDER BY id"
    return [row_to_subscriber(r) for r in conn.execute(sql)]


def set_subscriber_active(conn: sqlite3.Connection, email: str, active: bool, now: datetime | None = None) -> bool:
    """Activation manuelle (CLI) : `active` décide des envois, `status` passe à active / disabled."""
    with conn:
        cur = conn.execute("UPDATE subscribers SET active = ?, status = ?, updated_at = ? WHERE email = ?",
                           (int(active), "active" if active else "disabled", (now or utcnow()).isoformat(),
                            email.strip().lower()))
    return cur.rowcount > 0


# --------------------------------------------------------------------------------------------
# Résumés et scores
# --------------------------------------------------------------------------------------------
def save_summary(conn: sqlite3.Connection, notice_id: int, summary: LLMSummary, *, score: int, rules_score: int,
                 llm_provider: str | None, now: datetime | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO summaries (notice_id, summary_json, score, rules_score, llm_verdict, llm_provider, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(notice_id) DO UPDATE SET summary_json=excluded.summary_json, score=excluded.score,"
            " rules_score=excluded.rules_score, llm_verdict=excluded.llm_verdict, llm_provider=excluded.llm_provider,"
            " created_at=excluded.created_at",
            (notice_id, summary.model_dump_json(), score, rules_score, summary.verdict, llm_provider,
             (now or utcnow()).isoformat()),
        )


def get_summary(conn: sqlite3.Connection, notice_id: int) -> tuple[LLMSummary, dict[str, Any]] | None:
    row = conn.execute("SELECT * FROM summaries WHERE notice_id = ?", (notice_id,)).fetchone()
    if not row:
        return None
    summary = LLMSummary.model_validate(_loads(row["summary_json"], {}))
    meta = {"score": row["score"], "rules_score": row["rules_score"], "llm_verdict": row["llm_verdict"],
            "llm_provider": row["llm_provider"], "created_at": row["created_at"]}
    return summary, meta


def summarized_notices(conn: sqlite3.Connection, *, since: datetime | None = None
                       ) -> list[tuple[Notice, LLMSummary, str | None]]:
    """Avis disposant d'un résumé (donc scorés), les plus récents d'abord : (avis, résumé, fournisseur LLM)."""
    sql = ("SELECT n.*, s.summary_json, s.llm_provider FROM notices n JOIN summaries s ON s.notice_id = n.id"
           " WHERE 1=1")
    params: list[Any] = []
    if since is not None:
        sql += " AND (n.published_at IS NULL OR n.published_at >= ?)"
        params.append(since.isoformat())
    sql += " ORDER BY n.published_at DESC, n.id DESC"
    out = []
    for row in conn.execute(sql, params):
        out.append((row_to_notice(row), LLMSummary.model_validate(_loads(row["summary_json"], {})),
                    row["llm_provider"]))
    return out


# --------------------------------------------------------------------------------------------
# Envois
# --------------------------------------------------------------------------------------------
def delivered_notice_ids(conn: sqlite3.Connection, subscriber_id: int) -> set[int]:
    return {r["notice_id"] for r in conn.execute("SELECT notice_id FROM deliveries WHERE subscriber_id = ?",
                                                 (subscriber_id,))}


def record_deliveries(conn: sqlite3.Connection, subscriber_id: int, items: list[tuple[int, int]],
                      now: datetime | None = None) -> None:
    """`items` : liste de (notice_id, score)."""
    ts = (now or utcnow()).isoformat()
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO deliveries (subscriber_id, notice_id, sent_at, score) VALUES (?, ?, ?, ?)",
            [(subscriber_id, nid, ts, score) for nid, score in items],
        )


# --------------------------------------------------------------------------------------------
# Attributions
# --------------------------------------------------------------------------------------------
def row_to_award(row: sqlite3.Row) -> Award:
    return Award(
        id=row["id"], source=row["source"], source_id=row["source_id"], title=row["title"],
        buyer_name=row["buyer_name"], buyer_id=row["buyer_id"], holder_name=row["holder_name"],
        holder_id=row["holder_id"], amount=row["amount"], cpv_code=row["cpv_code"], dept=row["dept"],
        place_code=row["place_code"], place_type=row["place_type"], procedure_type=row["procedure_type"],
        notified_at=parse_dt(row["notified_at"]), data_published_at=parse_dt(row["data_published_at"]),
        duration_months=row["duration_months"], raw=_loads(row["raw"], {}),
    )


def upsert_award(conn: sqlite3.Connection, a: Award, now: datetime | None = None) -> bool:
    existing = conn.execute("SELECT id FROM awards WHERE source = ? AND source_id = ?",
                            (a.source, a.source_id)).fetchone()
    values = (a.title, a.buyer_name, a.buyer_id, a.holder_name, a.holder_id, a.amount, a.cpv_code, a.dept,
              a.place_code, a.place_type, a.procedure_type, to_iso(a.notified_at), to_iso(a.data_published_at),
              a.duration_months, a.raw_json())
    with conn:
        if existing:
            conn.execute(
                "UPDATE awards SET title=?, buyer_name=?, buyer_id=?, holder_name=?, holder_id=?, amount=?, cpv_code=?,"
                " dept=?, place_code=?, place_type=?, procedure_type=?, notified_at=?, data_published_at=?,"
                " duration_months=?, raw=? WHERE id=?",
                (*values, existing["id"]),
            )
            a.id = existing["id"]
            return False
        cur = conn.execute(
            "INSERT INTO awards (source, source_id, title, buyer_name, buyer_id, holder_name, holder_id, amount,"
            " cpv_code, dept, place_code, place_type, procedure_type, notified_at, data_published_at,"
            " duration_months, raw, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (a.source, a.source_id, *values, (now or utcnow()).isoformat()),
        )
        a.id = cur.lastrowid
        return True


def list_awards(conn: sqlite3.Connection, *, since: datetime | None = None, departments: list[str] | None = None,
                cpv_prefixes: list[str] | None = None, limit: int | None = None) -> list[Award]:
    sql = "SELECT * FROM awards WHERE 1=1"
    params: list[Any] = []
    if since is not None:
        sql += " AND (COALESCE(notified_at, data_published_at) >= ? OR data_published_at >= ?)"
        params += [since.isoformat(), since.isoformat()]
    if departments:
        sql += " AND dept IN (" + ",".join("?" for _ in departments) + ")"
        params += departments
    if cpv_prefixes:
        sql += " AND (" + " OR ".join("cpv_code LIKE ?" for _ in cpv_prefixes) + ")"
        params += [p + "%" for p in cpv_prefixes]
    sql += " ORDER BY COALESCE(notified_at, data_published_at) DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [row_to_award(r) for r in conn.execute(sql, params)]


# --------------------------------------------------------------------------------------------
# Journal de collecte et statistiques
# --------------------------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, source: str, now: datetime | None = None) -> int:
    with conn:
        cur = conn.execute("INSERT INTO collect_runs (source, started_at) VALUES (?, ?)",
                           (source, (now or utcnow()).isoformat()))
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, *, fetched: int, inserted: int, error: str | None = None,
               now: datetime | None = None) -> None:
    with conn:
        conn.execute("UPDATE collect_runs SET finished_at = ?, fetched = ?, inserted = ?, error = ? WHERE id = ?",
                     ((now or utcnow()).isoformat(), fetched, inserted, error, run_id))


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str, *params) -> Any:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    by_source = {r["source"]: r["c"] for r in conn.execute(
        "SELECT source, COUNT(*) AS c FROM notices GROUP BY source")}
    runs = [dict(r) for r in conn.execute(
        "SELECT source, started_at, finished_at, fetched, inserted, error FROM collect_runs"
        " ORDER BY id DESC LIMIT 10")]
    return {
        "notices": one("SELECT COUNT(*) FROM notices") or 0,
        "notices_by_source": by_source,
        "notices_unknown_dept": one("SELECT COUNT(*) FROM notices WHERE buyer_dept IS NULL AND departments = '[]'")
        or 0,
        "notices_without_cpv": one("SELECT COUNT(*) FROM notices WHERE cpv_codes = '[]'") or 0,
        "summaries": one("SELECT COUNT(*) FROM summaries") or 0,
        "pending_summaries": one(
            "SELECT COUNT(*) FROM notices n LEFT JOIN summaries s ON s.notice_id = n.id WHERE s.id IS NULL") or 0,
        "subscribers_active": one("SELECT COUNT(*) FROM subscribers WHERE active = 1") or 0,
        "subscribers_total": one("SELECT COUNT(*) FROM subscribers") or 0,
        "subscribers_pending": one("SELECT COUNT(*) FROM subscribers WHERE status = 'pending_payment'") or 0,
        "stripe_events": one("SELECT COUNT(*) FROM stripe_events") or 0,
        "deliveries": one("SELECT COUNT(*) FROM deliveries") or 0,
        "last_delivery": one("SELECT MAX(sent_at) FROM deliveries"),
        "awards": one("SELECT COUNT(*) FROM awards") or 0,
        "last_published": one("SELECT MAX(published_at) FROM notices"),
        "runs": runs,
    }
