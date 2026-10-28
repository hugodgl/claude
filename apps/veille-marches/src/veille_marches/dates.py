"""Dates : analyse tolérante des formats rencontrés dans les API et formatage français."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_TED_DATE_TZ = re.compile(r"^(\d{4}-\d{2}-\d{2})([+-]\d{2}:\d{2}|Z)$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def local(dt: datetime) -> datetime:
    """Heure de Paris pour l'affichage et les jours calendaires (les dates sont stockées en UTC : une date limite
    « 5 novembre à minuit » est 23 h UTC la veille)."""
    return dt.astimezone(PARIS) if dt.tzinfo else dt


def parse_dt(value) -> datetime | None:
    """Convertit une date d'API en datetime UTC « aware ». Retourne None si vide ou illisible.

    Formats acceptés : ISO 8601 (avec ou sans heure et fuseau), `2026-10-20+02:00` (TED),
    `20261020` (TED compact), objets date/datetime.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    m = _COMPACT.match(text)
    if m:
        text = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _TED_DATE_TZ.match(text)
    if m:
        text = m.group(1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def days_until(deadline: datetime | None, now: datetime | None = None) -> int | None:
    if deadline is None:
        return None
    now = now or utcnow()
    return (local(deadline).date() - local(now).date()).days


def fr_date(dt: datetime | None, with_time: bool = False) -> str:
    if dt is None:
        return "non précisée"
    dt = local(dt)
    text = f"{dt.day:02d}/{dt.month:02d}/{dt.year}"
    if with_time and (dt.hour or dt.minute):
        text += f" {dt.hour:02d}h{dt.minute:02d}"
    return text


FR_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
FR_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre")


def fr_long_date(dt: datetime | None, with_time: bool = False) -> str:
    """`mardi 28 octobre 2026`, ou `mardi 28 octobre 2026 vers 7 h` (heure locale du datetime)."""
    if dt is None:
        return "non précisée"
    dt = local(dt)
    text = f"{FR_WEEKDAYS[dt.weekday()]} {dt.day} {FR_MONTHS[dt.month - 1]} {dt.year}"
    if with_time:
        text += f" vers {dt.hour} h" + (f"{dt.minute:02d}" if dt.minute else "")
    return text


def since_date(days: int, now: datetime | None = None) -> date:
    return ((now or utcnow()) - timedelta(days=days)).date()


def fr_amount(amount: float | None) -> str:
    if amount is None:
        return "montant non précisé"
    if amount >= 1_000_000:
        millions = f"{amount / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{millions} M€ HT".replace(".", ",")
    if amount >= 1_000:
        return f"{amount / 1_000:.0f} k€ HT"
    return f"{amount:.0f} € HT"
