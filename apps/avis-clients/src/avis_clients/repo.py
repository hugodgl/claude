"""Fonctions d'accès aux données (SQL simple, pas d'ORM)."""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import unicodedata
from datetime import timedelta
from typing import Any, Iterable
from urllib.parse import quote

from .db import month_bounds_utc, normalize_iso, now_iso, utcnow
from .models import Account, Establishment, Review, ReviewRequest, ReviewSource

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or "")) and len(email) <= 254


def _update(conn: sqlite3.Connection, table: str, row_id: int, fields: dict[str, Any]) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), row_id))


# ------------------------------------------------------------------------------------------
# Comptes
# ------------------------------------------------------------------------------------------
def get_account(conn: sqlite3.Connection, account_id: int) -> Account | None:
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return Account.from_row(row) if row else None


def get_account_by_email(conn: sqlite3.Connection, email: str) -> Account | None:
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email.lower().strip(),)).fetchone()
    return Account.from_row(row) if row else None


def get_or_create_account(conn: sqlite3.Connection, email: str, trial_days: int) -> tuple[Account, bool]:
    email = email.lower().strip()
    existing = get_account_by_email(conn, email)
    if existing:
        return existing, False
    now = utcnow()
    with conn:
        conn.execute(
            "INSERT INTO accounts (email, created_at, plan, trial_ends_at) VALUES (?, ?, 'none', ?)",
            (email, now.isoformat(timespec="seconds"),
             (now + timedelta(days=trial_days)).isoformat(timespec="seconds")),
        )
    return get_account_by_email(conn, email), True  # type: ignore[return-value]


def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    return [Account.from_row(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")]


def update_account(conn: sqlite3.Connection, account_id: int, **fields: Any) -> None:
    _update(conn, "accounts", account_id, fields)


def find_account_by_stripe(
    conn: sqlite3.Connection, *, customer_id: str | None = None, subscription_id: str | None = None
) -> Account | None:
    if customer_id:
        row = conn.execute("SELECT * FROM accounts WHERE stripe_customer_id = ?", (customer_id,)).fetchone()
        if row:
            return Account.from_row(row)
    if subscription_id:
        row = conn.execute(
            "SELECT * FROM accounts WHERE stripe_subscription_id = ?", (subscription_id,)
        ).fetchone()
        if row:
            return Account.from_row(row)
    return None


# ------------------------------------------------------------------------------------------
# Établissements
# ------------------------------------------------------------------------------------------
def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:40] or "etablissement"


def unique_slug(conn: sqlite3.Connection, name: str) -> str:
    base = slugify(name)
    slug = base
    while conn.execute("SELECT 1 FROM establishments WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def review_url_for_place(place_id: str) -> str:
    return f"https://search.google.com/local/writereview?placeid={quote(place_id.strip(), safe='')}"


def create_establishment(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    name: str,
    google_place_id: str | None,
    review_url: str,
    tone_profile: dict[str, Any],
    request_template: str,
    google_location_name: str | None = None,
    notification_email: str | None = None,
) -> Establishment:
    slug = unique_slug(conn, name)
    with conn:
        cur = conn.execute(
            "INSERT INTO establishments (account_id, name, slug, google_place_id, google_location_name,"
            " review_url, tone_profile_json, request_template, notification_email, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, name.strip(), slug, (google_place_id or "").strip() or None, google_location_name,
             review_url, json.dumps(tone_profile, ensure_ascii=False), request_template,
             notification_email, now_iso()),
        )
    if google_location_name:
        sync_google_source(conn, int(cur.lastrowid), google_location_name)
    return get_establishment(conn, cur.lastrowid)  # type: ignore[return-value]


def get_establishment(
    conn: sqlite3.Connection, establishment_id: int, account_id: int | None = None
) -> Establishment | None:
    row = conn.execute("SELECT * FROM establishments WHERE id = ?", (establishment_id,)).fetchone()
    if not row or (account_id is not None and row["account_id"] != account_id):
        return None
    return Establishment.from_row(row)


def get_establishment_by_slug(conn: sqlite3.Connection, slug: str) -> Establishment | None:
    row = conn.execute("SELECT * FROM establishments WHERE slug = ?", (slug,)).fetchone()
    return Establishment.from_row(row) if row else None


def get_establishment_by_location(conn: sqlite3.Connection, location_name: str) -> Establishment | None:
    """Établissement déjà relié à cette fiche Google (une fiche ne peut appartenir qu'à un établissement)."""
    row = conn.execute("SELECT * FROM establishments WHERE google_location_name = ? ORDER BY id LIMIT 1",
                       (location_name,)).fetchone()
    return Establishment.from_row(row) if row else None


def list_establishments(conn: sqlite3.Connection, account_id: int | None = None) -> list[Establishment]:
    if account_id is None:
        rows = conn.execute("SELECT * FROM establishments ORDER BY id")
    else:
        rows = conn.execute("SELECT * FROM establishments WHERE account_id = ? ORDER BY id", (account_id,))
    return [Establishment.from_row(r) for r in rows]


def update_establishment(conn: sqlite3.Connection, establishment_id: int, **fields: Any) -> None:
    """Met à jour l'établissement ; `google_location_name` est répercuté dans `review_sources` (la colonne
    reste la saisie du commerçant, la table des sources est ce que le poll parcourt)."""
    if "tone_profile" in fields:
        fields["tone_profile_json"] = json.dumps(fields.pop("tone_profile"), ensure_ascii=False)
    if "google_location_name" in fields:
        # d'abord la source (peut lever SourceConflict), pour ne pas laisser la colonne pointer vers une
        # fiche reliée à un autre établissement
        sync_google_source(conn, establishment_id, fields["google_location_name"])
    _update(conn, "establishments", establishment_id, fields)


def delete_establishment(conn: sqlite3.Connection, establishment_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM establishments WHERE id = ?", (establishment_id,))


# ------------------------------------------------------------------------------------------
# Sources d'avis (une par plateforme et par établissement)
# ------------------------------------------------------------------------------------------
class SourceConflict(ValueError):
    """L'identifiant externe est déjà relié à un autre établissement (isolation entre comptes)."""


def get_source(conn: sqlite3.Connection, establishment_id: int, platform: str) -> ReviewSource | None:
    row = conn.execute("SELECT * FROM review_sources WHERE establishment_id = ? AND platform = ?",
                       (establishment_id, platform)).fetchone()
    return ReviewSource.from_row(row) if row else None


def get_source_by_id(conn: sqlite3.Connection, source_id: int) -> ReviewSource | None:
    row = conn.execute("SELECT * FROM review_sources WHERE id = ?", (source_id,)).fetchone()
    return ReviewSource.from_row(row) if row else None


def get_source_by_external(conn: sqlite3.Connection, platform: str, external_id: str) -> ReviewSource | None:
    """Source déjà reliée à cet identifiant externe, tous comptes confondus (un identifiant = un établissement)."""
    row = conn.execute("SELECT * FROM review_sources WHERE platform = ? AND external_id = ?",
                       (platform, external_id)).fetchone()
    return ReviewSource.from_row(row) if row else None


def list_sources(conn: sqlite3.Connection, establishment_id: int | None = None,
                 platform: str | None = None) -> list[ReviewSource]:
    where, params = [], []
    if establishment_id is not None:
        where.append("establishment_id = ?")
        params.append(establishment_id)
    if platform:
        where.append("platform = ?")
        params.append(platform)
    sql = "SELECT * FROM review_sources" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY establishment_id, CASE platform WHEN 'google' THEN 0 WHEN 'facebook' THEN 1 ELSE 2 END"
    return [ReviewSource.from_row(r) for r in conn.execute(sql, params)]


def list_sources_for_establishments(conn: sqlite3.Connection, establishment_ids: Iterable[int]) -> list[ReviewSource]:
    ids = list(establishment_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM review_sources WHERE establishment_id IN ({marks})"
                        " ORDER BY establishment_id, platform", ids)
    return [ReviewSource.from_row(r) for r in rows]


def upsert_source(
    conn: sqlite3.Connection,
    *,
    establishment_id: int,
    platform: str,
    external_id: str,
    display_name: str | None = None,
    public_url: str | None = None,
    credentials_enc: str | None = None,
) -> ReviewSource:
    """Crée ou remplace la source de cette plateforme pour l'établissement (statut remis à `active`).
    Lève `SourceConflict` si l'identifiant externe est relié à un autre établissement."""
    other = get_source_by_external(conn, platform, external_id)
    if other and other.establishment_id != establishment_id:
        raise SourceConflict(f"Cette source {platform} est déjà reliée à un autre établissement.")
    now = now_iso()
    try:
        with conn:
            conn.execute(
                "INSERT INTO review_sources (establishment_id, platform, external_id, display_name, public_url,"
                " credentials_enc, status, last_synced_at, last_error, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'active', NULL, NULL, ?, ?)"
                " ON CONFLICT(establishment_id, platform) DO UPDATE SET external_id = excluded.external_id,"
                " display_name = excluded.display_name, public_url = excluded.public_url,"
                " credentials_enc = excluded.credentials_enc, status = 'active', last_synced_at = NULL,"
                " last_error = NULL, updated_at = excluded.updated_at",
                (establishment_id, platform, external_id, display_name, public_url, credentials_enc, now, now),
            )
    except sqlite3.IntegrityError as e:  # course entre deux liaisons simultanées du même identifiant
        raise SourceConflict(f"Cette source {platform} est déjà reliée à un autre établissement.") from e
    return get_source(conn, establishment_id, platform)  # type: ignore[return-value]


def delete_source(conn: sqlite3.Connection, establishment_id: int, platform: str) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM review_sources WHERE establishment_id = ? AND platform = ?",
                           (establishment_id, platform))
    return cur.rowcount > 0


def mark_source_synced(conn: sqlite3.Connection, source_id: int) -> None:
    _update(conn, "review_sources", source_id,
            {"status": "active", "last_synced_at": now_iso(), "last_error": None, "updated_at": now_iso()})


def mark_source_error(conn: sqlite3.Connection, source_id: int, error: str) -> None:
    _update(conn, "review_sources", source_id,
            {"status": "error", "last_error": (error or "")[:300], "updated_at": now_iso()})


def sync_google_source(conn: sqlite3.Connection, establishment_id: int, location_name: str | None) -> None:
    """Miroir de `establishments.google_location_name` dans `review_sources` : vide → source retirée."""
    location_name = (location_name or "").strip() or None
    if location_name is None:
        delete_source(conn, establishment_id, "google")
        return
    current = get_source(conn, establishment_id, "google")
    if current and current.external_id == location_name:
        return
    try:
        upsert_source(conn, establishment_id=establishment_id, platform="google", external_id=location_name)
    except SourceConflict:
        raise SourceConflict("Cette fiche Google est déjà reliée à un autre établissement.") from None


# ------------------------------------------------------------------------------------------
# Avis
# ------------------------------------------------------------------------------------------
def get_review(conn: sqlite3.Connection, review_id: int) -> Review | None:
    row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    return Review.from_row(row) if row else None


def find_review(
    conn: sqlite3.Connection, establishment_id: int, platform: str, external_id: str
) -> Review | None:
    row = conn.execute(
        "SELECT * FROM reviews WHERE establishment_id = ? AND platform = ? AND external_id = ?",
        (establishment_id, platform, external_id),
    ).fetchone()
    return Review.from_row(row) if row else None


def insert_review(
    conn: sqlite3.Connection,
    *,
    establishment_id: int,
    platform: str,
    external_id: str,
    external_name: str | None,
    author: str | None,
    rating: int,
    text: str | None,
    created_at: str,
    updated_at: str | None,
    reply_text: str | None = None,
    reply_status: str = "none",
    reply_published_at: str | None = None,
    rating_note: str | None = None,
) -> Review:
    # INSERT OR IGNORE : deux polls simultanés (job + bouton « Synchroniser ») ne doivent ni planter
    # ni dupliquer ; les horodatages Google (« Z », millisecondes) sont ramenés au format commun.
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO reviews (establishment_id, platform, external_id, external_name, author,"
            " rating, text, created_at, updated_at, fetched_at, reply_text, reply_status, reply_published_at,"
            " rating_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (establishment_id, platform, external_id, external_name, author, rating, text,
             normalize_iso(created_at) or created_at, normalize_iso(updated_at), now_iso(), reply_text,
             reply_status, normalize_iso(reply_published_at), rating_note),
        )
    if cur.rowcount == 0:
        existing = find_review(conn, establishment_id, platform, external_id)
        if existing is None:
            raise sqlite3.IntegrityError("insertion de l'avis refusée par une contrainte")
        return existing
    return get_review(conn, cur.lastrowid)  # type: ignore[return-value]


def update_review(conn: sqlite3.Connection, review_id: int, **fields: Any) -> None:
    _update(conn, "reviews", review_id, fields)


def list_reviews(
    conn: sqlite3.Connection,
    establishment_ids: Iterable[int],
    *,
    status: str | None = None,
    platform: str | None = None,
    limit: int = 200,
) -> list[Review]:
    ids = list(establishment_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    sql = f"SELECT * FROM reviews WHERE establishment_id IN ({marks})"
    params: list[Any] = list(ids)
    if status:
        sql += " AND reply_status = ?"
        params.append(status)
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [Review.from_row(r) for r in conn.execute(sql, params)]


def list_reviews_in_month(conn: sqlite3.Connection, establishment_id: int, month: str) -> list[Review]:
    """`month` au format AAAA-MM, borné dans le fuseau métier (un avis à 00:30 à Paris le 1er compte
    dans le nouveau mois, pas dans le précédent comme avec un découpage UTC)."""
    start, end = month_bounds_utc(month)
    rows = conn.execute(
        "SELECT * FROM reviews WHERE establishment_id = ? AND created_at >= ? AND created_at < ?"
        " ORDER BY created_at",
        (establishment_id, start, end),
    )
    return [Review.from_row(r) for r in rows]


def count_reviews_by_status(conn: sqlite3.Connection, establishment_ids: Iterable[int]) -> dict[str, int]:
    ids = list(establishment_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT reply_status, COUNT(*) AS n FROM reviews WHERE establishment_id IN ({marks})"
        " GROUP BY reply_status",
        ids,
    )
    return {r["reply_status"]: r["n"] for r in rows}


# ------------------------------------------------------------------------------------------
# Demandes d'avis, STOP
# ------------------------------------------------------------------------------------------
def insert_review_request(
    conn: sqlite3.Connection,
    *,
    establishment_id: int,
    channel: str,
    recipient: str,
    first_name: str | None,
    message: str,
    status: str,
    provider: str | None = None,
    provider_message_id: str | None = None,
    error: str | None = None,
    sent_at: str | None = None,
) -> ReviewRequest:
    with conn:
        cur = conn.execute(
            "INSERT INTO review_requests (establishment_id, channel, recipient, first_name, message,"
            " sent_at, status, provider, provider_message_id, error, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (establishment_id, channel, recipient, first_name, message, sent_at, status, provider,
             provider_message_id, error, now_iso()),
        )
    row = conn.execute("SELECT * FROM review_requests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return ReviewRequest.from_row(row)


def list_review_requests(
    conn: sqlite3.Connection, establishment_ids: Iterable[int], limit: int = 50
) -> list[ReviewRequest]:
    ids = list(establishment_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM review_requests WHERE establishment_id IN ({marks})"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        [*ids, limit],
    )
    return [ReviewRequest.from_row(r) for r in rows]


def count_messages_in_month(conn: sqlite3.Connection, account_id: int, month: str) -> int:
    """Messages SMS / WhatsApp décomptés du quota pour le mois `AAAA-MM` du fuseau métier."""
    start, end = month_bounds_utc(month)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM review_requests rr JOIN establishments e ON e.id = rr.establishment_id"
        " WHERE e.account_id = ? AND rr.channel IN ('sms', 'whatsapp')"
        " AND rr.status IN ('sent', 'dry-run') AND rr.created_at >= ? AND rr.created_at < ?",
        (account_id, start, end),
    ).fetchone()
    return int(row["n"])


def last_request_account_for_phone(conn: sqlite3.Connection, phone: str) -> int | None:
    row = conn.execute(
        "SELECT e.account_id FROM review_requests rr JOIN establishments e ON e.id = rr.establishment_id"
        " WHERE rr.recipient = ? ORDER BY rr.created_at DESC LIMIT 1",
        (phone,),
    ).fetchone()
    return int(row["account_id"]) if row else None


def is_opted_out(conn: sqlite3.Connection, phone: str, account_id: int | None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM optouts WHERE phone = ? AND (account_id IS NULL OR account_id = ?) LIMIT 1",
        (phone, account_id),
    ).fetchone()
    return row is not None


def add_optout(conn: sqlite3.Connection, phone: str, account_id: int | None, source: str) -> bool:
    """Ajoute un numéro à la liste STOP (portée : un compte, ou globale si account_id est None)."""
    exists = conn.execute(
        "SELECT 1 FROM optouts WHERE phone = ? AND account_id IS ?", (phone, account_id)
    ).fetchone()
    if exists:
        return False
    with conn:
        conn.execute(
            "INSERT INTO optouts (account_id, phone, source, created_at) VALUES (?, ?, ?, ?)",
            (account_id, phone, source, now_iso()),
        )
    return True


def remove_optout(conn: sqlite3.Connection, phone: str, account_id: int | None) -> bool:
    """Retire un numéro de la liste STOP du compte (ou de la liste globale si account_id est None)."""
    with conn:
        cur = conn.execute("DELETE FROM optouts WHERE phone = ? AND account_id IS ?", (phone, account_id))
    return cur.rowcount > 0


def list_optouts(conn: sqlite3.Connection, account_id: int | None) -> list[sqlite3.Row]:
    """Liste STOP d'un compte (ses propres oppositions uniquement : les oppositions globales restent
    appliquées à l'envoi mais ne sont pas exposées aux commerçants) ; tout avec account_id=None (CLI)."""
    if account_id is None:
        return list(conn.execute("SELECT * FROM optouts ORDER BY created_at DESC"))
    return list(conn.execute(
        "SELECT * FROM optouts WHERE account_id = ? ORDER BY created_at DESC", (account_id,),
    ))


# ------------------------------------------------------------------------------------------
# Messages privés, journal
# ------------------------------------------------------------------------------------------
def insert_private_message(
    conn: sqlite3.Connection, establishment_id: int, sender_name: str | None, sender_contact: str | None,
    message: str,
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO private_messages (establishment_id, sender_name, sender_contact, message,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (establishment_id, sender_name, sender_contact, message, now_iso()),
        )
    return int(cur.lastrowid)


def list_private_messages(conn: sqlite3.Connection, establishment_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM private_messages WHERE establishment_id = ? ORDER BY created_at DESC LIMIT ?",
        (establishment_id, limit),
    ))


def list_events(conn: sqlite3.Connection, account_id: int | None = None, limit: int = 30,
                exclude_kinds: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Derniers événements ; `exclude_kinds` écarte par exemple les vues de page publique du fil d'activité."""
    excluded = list(exclude_kinds)
    where, params = [], []
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    if excluded:
        where.append(f"kind NOT IN ({','.join('?' * len(excluded))})")
        params.extend(excluded)
    sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    rows = conn.execute(sql, [*params, limit])
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            d["payload"] = {}
        out.append(d)
    return out
