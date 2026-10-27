"""Brief hebdomadaire d'attribution (DECP) : qui a gagné quoi dans la zone de l'abonné, montants, acheteurs actifs,
titulaires récurrents. Réservé au plan Pro par défaut."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from core.mail import Email, Mailer

from . import db
from .dates import utcnow
from .models import Award, Subscriber
from .rendering import render
from .settings import VMSettings

HISTORY_DAYS = 365


@dataclass
class Counter:
    name: str
    count: int = 0
    amount: float = 0.0
    recent: int = 0   # dans la période du brief


@dataclass
class Brief:
    subscriber: Subscriber
    since: datetime
    until: datetime
    awards: list[Award] = field(default_factory=list)
    by_dept: dict[str, list[Award]] = field(default_factory=dict)
    total_amount: float = 0.0
    with_amount: int = 0
    top_buyers: list[Counter] = field(default_factory=list)
    recurring_holders: list[Counter] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.awards)


@dataclass
class BriefOutcome:
    brief: Brief
    subject: str
    html: str
    text: str
    sent: bool = False
    message_id: str | None = None
    files: list[Path] = field(default_factory=list)


def _aggregate(awards: list[Award], key, recent_ids: set[int]) -> list[Counter]:
    counters: dict[str, Counter] = {}
    for a in awards:
        name = key(a)
        if not name:
            continue
        c = counters.setdefault(name, Counter(name))
        c.count += 1
        c.amount += a.amount or 0.0
        if a.id in recent_ids:
            c.recent += 1
    return sorted(counters.values(), key=lambda c: (-c.count, -c.amount, c.name))


def build_brief(conn: sqlite3.Connection, subscriber: Subscriber, settings: VMSettings, *,
                since_days: int = 7, now: datetime | None = None) -> Brief | None:
    now = now or utcnow()
    since = now - timedelta(days=since_days)
    recent = db.list_awards(conn, since=since, departments=subscriber.departments or None,
                            cpv_prefixes=subscriber.cpv_prefixes or None)
    if not recent:
        return None
    history = db.list_awards(conn, since=now - timedelta(days=HISTORY_DAYS), departments=subscriber.departments or None,
                             cpv_prefixes=subscriber.cpv_prefixes or None)
    recent_ids = {a.id for a in recent}
    brief = Brief(subscriber=subscriber, since=since, until=now, awards=recent)
    by_dept: dict[str, list[Award]] = defaultdict(list)
    for a in recent:
        by_dept[a.dept or "zone non précisée"].append(a)
        if a.amount is not None:
            brief.total_amount += a.amount
            brief.with_amount += 1
    brief.by_dept = dict(sorted(by_dept.items()))
    brief.top_buyers = _aggregate(history, lambda a: a.buyer_name, recent_ids)[:8]
    brief.recurring_holders = [c for c in _aggregate(history, lambda a: a.holder_label, recent_ids)
                               if c.count >= 2][:8]
    return brief


def render_brief(brief: Brief, settings: VMSettings) -> tuple[str, str, str]:
    period = f"du {brief.since.day:02d}/{brief.since.month:02d} au {brief.until.day:02d}/{brief.until.month:02d}/{brief.until.year}"
    subject = f"{settings.product_name} — brief de la semaine : {brief.count} attribution(s) {period}"
    ctx = {"brief": brief, "settings": settings, "subject": subject, "period": period}
    return subject, render("brief.html.j2", **ctx), render("brief.txt.j2", **ctx)


def send_briefs(conn: sqlite3.Connection, settings: VMSettings, mailer: Mailer | None = None, *,
                since_days: int = 7, send: bool = False, dry_run: bool = False, subscriber_email: str | None = None,
                all_plans: bool = False, now: datetime | None = None) -> list[BriefOutcome]:
    now = now or utcnow()
    subscribers = db.list_subscribers(conn, active_only=True)
    if subscriber_email:
        subscribers = [s for s in subscribers if s.email == subscriber_email.strip().lower()]
    if not all_plans:
        subscribers = [s for s in subscribers if s.plan == "pro"]
    outcomes: list[BriefOutcome] = []
    for sub in subscribers:
        brief = build_brief(conn, sub, settings, since_days=since_days, now=now)
        if brief is None:
            continue
        subject, html, text = render_brief(brief, settings)
        outcome = BriefOutcome(brief, subject, html, text)
        if send:
            if mailer is None:
                raise RuntimeError("mailer requis pour l'envoi")
            outcome.message_id = mailer.send(
                Email(to=[sub.email], subject=subject, html=html, text=text, reply_to=settings.reply_to),
                sender=settings.mail_from)
            outcome.sent = True
        elif not dry_run:
            out_dir = Path(settings.out_dir) / "briefs" / now.strftime("%Y-%m-%d")
            out_dir.mkdir(parents=True, exist_ok=True)
            base = out_dir / sub.email.replace("@", "_at_")
            base.with_suffix(".html").write_text(html, encoding="utf-8")
            base.with_suffix(".txt").write_text(text, encoding="utf-8")
            outcome.files = [base.with_suffix(".html"), base.with_suffix(".txt")]
        outcomes.append(outcome)
    return outcomes
