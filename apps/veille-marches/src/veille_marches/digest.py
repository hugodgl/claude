"""Digest quotidien par abonné : sélection des avis nouveaux, score par abonné, rendu HTML + texte, envoi."""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.mail import Email, Mailer

from . import db
from .accounts import account_url
from .dates import days_until, local, utcnow
from .filtering import MatchResult, match_notice
from .models import LLMSummary, Notice, Subscriber
from .rendering import render
from .scoring import RuleScore, final_score, rules_score
from .settings import VMSettings

log = logging.getLogger(__name__)


@dataclass
class DigestItem:
    notice: Notice
    summary: LLMSummary
    match: MatchResult
    rules: RuleScore
    score: int
    days_left: int | None
    llm_used: bool

    @property
    def flags(self) -> list[str]:
        seen: list[str] = []
        for f in self.rules.flags:
            if f not in seen:
                seen.append(f)
        return seen


@dataclass
class Digest:
    subscriber: Subscriber
    date: datetime
    priority: list[DigestItem] = field(default_factory=list)
    others: list[DigestItem] = field(default_factory=list)

    @property
    def items(self) -> list[DigestItem]:
        return self.priority + self.others

    @property
    def total(self) -> int:
        return len(self.priority) + len(self.others)


@dataclass
class DigestOutcome:
    digest: Digest
    subject: str
    html: str
    text: str
    sent: bool = False
    message_id: str | None = None
    files: list[Path] = field(default_factory=list)
    error: str | None = None   # envoi en échec : rien d'enregistré, l'abonné sera resservi au prochain passage


def build_digest(conn: sqlite3.Connection, subscriber: Subscriber, settings: VMSettings,
                 now: datetime | None = None) -> Digest | None:
    """Retourne le digest de l'abonné, ou None s'il n'y a rien de nouveau (zéro email vide)."""
    now = now or utcnow()
    since = now - timedelta(days=settings.digest_lookback_days)
    delivered = db.delivered_notice_ids(conn, subscriber.id) if subscriber.id is not None else set()
    items: list[DigestItem] = []
    for notice, summary, llm_provider in db.summarized_notices(conn, since=since):
        if notice.id in delivered:
            continue
        m = match_notice(notice, subscriber, settings)
        if not m.matched:
            continue
        if notice.deadline_at is not None and notice.deadline_at < now:
            continue
        buyer_seen = (db.buyer_notice_count(conn, notice.buyer_name, exclude_id=notice.id) > 0
                      or db.buyer_award_count(conn, notice.buyer_name) > 0)
        rs = rules_score(notice, m, buyer_seen=buyer_seen, now=now)
        llm_used = bool(llm_provider) and llm_provider != "none"
        score = final_score(rs.total, summary.verdict if llm_used else None)
        items.append(DigestItem(notice, summary, m, rs, score, days_until(notice.deadline_at, now), llm_used))
    if not items:
        return None
    items.sort(key=lambda it: (-it.score, it.notice.deadline_at or datetime.max.replace(tzinfo=now.tzinfo)))
    digest = Digest(subscriber=subscriber, date=now)
    for it in items:
        (digest.priority if it.score >= settings.priority_threshold else digest.others).append(it)
    return digest


def render_digest(digest: Digest, settings: VMSettings) -> tuple[str, str, str]:
    """Retourne (objet, html, texte)."""
    d = local(digest.date)
    date_label = f"{d.day:02d}/{d.month:02d}/{d.year}"
    if digest.priority:
        subject = (f"{settings.product_name} {date_label} : {digest.total} nouveau(x) marché(s), "
                   f"{len(digest.priority)} à regarder en priorité")
    else:
        subject = f"{settings.product_name} {date_label} : {digest.total} nouveau(x) marché(s)"
    ctx = {"digest": digest, "settings": settings, "subject": subject, "date_label": date_label,
           "threshold": settings.priority_threshold, "account_url": settings_account_url(settings, digest.subscriber)}
    return subject, render("digest.html.j2", **ctx), render("digest.txt.j2", **ctx)


def settings_account_url(settings: VMSettings, subscriber: Subscriber) -> str | None:
    """Lien signé vers l'espace abonné, seulement si une clé stable est configurée (sinon le lien mourrait)."""
    if not settings.app_secret_key or subscriber.id is None:
        return None
    return account_url(settings, subscriber.id)


def _safe_filename(email: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", email.lower())


def write_previews(out_dir: Path, email: str, html: str, text: str) -> list[Path]:
    """Écrit `<email nettoyé>.html` et `.txt` (sans `with_suffix`, qui remplacerait le `.fr` de l'adresse)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(email)
    paths = [out_dir / f"{stem}.html", out_dir / f"{stem}.txt"]
    paths[0].write_text(html, encoding="utf-8")
    paths[1].write_text(text, encoding="utf-8")
    return paths


def send_or_record_error(mailer: Mailer, email: Email, sender: str, outcome: Any, log_label: str) -> bool:
    """Envoie ; en cas d'échec, note l'erreur sur `outcome` sans interrompre la tournée des autres abonnés."""
    try:
        outcome.message_id = mailer.send(email, sender=sender)
    except Exception as e:  # noqa: BLE001 - un envoi en échec ne doit pas priver les abonnés suivants
        log.exception("%s non envoyé à %s", log_label, email.to[0])
        outcome.error = str(e) or e.__class__.__name__
        return False
    outcome.sent = True
    return True


def send_digests(conn: sqlite3.Connection, settings: VMSettings, mailer: Mailer | None = None, *,
                 subscriber_email: str | None = None, send: bool = False, dry_run: bool = False,
                 now: datetime | None = None) -> list[DigestOutcome]:
    """Construit les digests des abonnés actifs.

    - `send=True` : envoie via le mailer et enregistre les deliveries (jamais deux fois le même avis) ;
    - sinon, sans `dry_run` : écrit les aperçus HTML/texte dans `OUT_DIR` (rien n'est enregistré) ;
    - `dry_run=True` : ne fait que construire et retourner (la CLI affiche).
    """
    now = now or utcnow()
    subscribers = db.list_subscribers(conn, active_only=True)
    if subscriber_email:
        subscribers = [s for s in subscribers if s.email == subscriber_email.strip().lower()]
    outcomes: list[DigestOutcome] = []
    for sub in subscribers:
        digest = build_digest(conn, sub, settings, now)
        if digest is None:
            continue
        subject, html, text = render_digest(digest, settings)
        outcome = DigestOutcome(digest, subject, html, text)
        if send:
            if mailer is None:
                raise RuntimeError("mailer requis pour l'envoi")
            email = Email(to=[sub.email], subject=subject, html=html, text=text, reply_to=settings.reply_to)
            if send_or_record_error(mailer, email, settings.mail_from, outcome, "digest"):
                db.record_deliveries(conn, sub.id, [(it.notice.id, it.score) for it in digest.items], now)
        elif not dry_run:
            outcome.files = write_previews(Path(settings.out_dir) / "digests" / now.strftime("%Y-%m-%d"), sub.email,
                                           html, text)
        outcomes.append(outcome)
    return outcomes
