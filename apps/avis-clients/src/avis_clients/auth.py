"""Connexion par lien magique et sessions signées (cookie)."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import timedelta

from core.mail import Email, Mailer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .db import now_iso, parse_iso, utcnow
from .models import Account
from .repo import get_account
from .settings import AppSettings
from .templating import render

SESSION_COOKIE = "avis_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_magic_link(conn: sqlite3.Connection, email: str, ttl_s: int) -> str:
    """Crée un lien magique et retourne le jeton en clair (seul le hachage est stocké)."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with conn:
        conn.execute(
            "INSERT INTO magic_links (email, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (email.lower().strip(), hash_token(token), now.isoformat(timespec="seconds"),
             (now + timedelta(seconds=ttl_s)).isoformat(timespec="seconds")),
        )
    return token


def consume_magic_link(conn: sqlite3.Connection, token: str) -> str | None:
    """Retourne l'email si le jeton est valide, non utilisé et non expiré, puis le marque utilisé.

    Le marquage est une seule requête conditionnelle : deux requêtes simultanées avec le même lien
    ne peuvent pas toutes deux ouvrir une session."""
    now = now_iso()
    with conn:
        cur = conn.execute(
            "UPDATE magic_links SET used_at = ? WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
            (now, hash_token(token), now),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute("SELECT email FROM magic_links WHERE token_hash = ?", (hash_token(token),)).fetchone()
    return row["email"] if row else None


def recent_magic_link_exists(conn: sqlite3.Connection, email: str, within_s: int) -> bool:
    """Vrai si un lien a déjà été émis pour cette adresse il y a moins de `within_s` secondes (anti-rafale)."""
    since = (utcnow() - timedelta(seconds=within_s)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT 1 FROM magic_links WHERE email = ? AND created_at > ? LIMIT 1", (email.lower().strip(), since)
    ).fetchone()
    return row is not None


def create_session(
    conn: sqlite3.Connection, account_id: int, max_age_s: int, user_agent: str | None = None
) -> str:
    session_id = secrets.token_urlsafe(32)
    now = utcnow()
    with conn:
        conn.execute(
            "INSERT INTO sessions (id, account_id, created_at, expires_at, user_agent)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, account_id, now.isoformat(timespec="seconds"),
             (now + timedelta(seconds=max_age_s)).isoformat(timespec="seconds"), (user_agent or "")[:200]),
        )
        conn.execute("UPDATE accounts SET last_login_at = ? WHERE id = ?", (now_iso(), account_id))
    return session_id


def get_session_account(conn: sqlite3.Connection, session_id: str) -> Account | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    expires = parse_iso(row["expires_at"])
    if expires is None or expires < utcnow():
        delete_session(conn, session_id)
        return None
    return get_account(conn, row["account_id"])


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


class SessionSigner:
    """Signe l'identifiant de session placé dans le cookie (itsdangerous, horodaté)."""

    def __init__(self, secret: str, max_age_s: int):
        self._serializer = URLSafeTimedSerializer(secret, salt="avis-clients-session")
        self.max_age_s = max_age_s

    def sign(self, session_id: str) -> str:
        return self._serializer.dumps(session_id)

    def unsign(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._serializer.loads(value, max_age=self.max_age_s)
        except (BadSignature, SignatureExpired):
            return None


def send_magic_link_email(mailer: Mailer, settings: AppSettings, email: str, token: str) -> str:
    url = f"{settings.app_base_url.rstrip('/')}/auth/{token}"
    html = render("emails/magic_link.html", url=url, app_name=settings.app_name,
                  ttl_minutes=settings.magic_link_ttl_s // 60)
    text = (f"Bonjour,\n\nVoici votre lien de connexion à {settings.app_name} :\n{url}\n\n"
            f"Il est valable {settings.magic_link_ttl_s // 60} minutes et ne sert qu'une fois.\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.")
    mailer.send(Email(to=[email], subject=f"Votre lien de connexion à {settings.app_name}",
                      html=html, text=text), sender=settings.mail_from)
    return url
