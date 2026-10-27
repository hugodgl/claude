"""Espace abonné sans mot de passe : liens signés (HMAC, durée limitée) et emails de bienvenue / de connexion."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.mail import Email, Mailer

from .catalog import PERIODS, PLANS, department_label, next_digest_at, next_weekly_brief_at
from .dates import utcnow
from .models import Subscriber
from .rendering import render
from .settings import VMSettings

log = logging.getLogger(__name__)
_TOKEN_SALT = b"veille-marches:compte"


class TokenError(ValueError):
    def __init__(self, reason: str, expired: bool = False):
        super().__init__(reason)
        self.expired = expired


_runtime_secret: str | None = None


def secret_key(settings: VMSettings) -> str:
    """Clé de signature : APP_SECRET_KEY, sinon une clé aléatoire par processus (les liens meurent au redémarrage)."""
    global _runtime_secret
    if settings.app_secret_key:
        return settings.app_secret_key
    if _runtime_secret is None:
        _runtime_secret = secrets.token_hex(32)
        log.warning("APP_SECRET_KEY absent : clé de session temporaire, les liens « espace abonné » "
                    "ne survivront pas au redémarrage")
    return _runtime_secret


def _sign(key: str, payload: bytes) -> str:
    mac = hmac.new(key.encode("utf-8"), _TOKEN_SALT + b"." + payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def make_account_token(settings: VMSettings, subscriber_id: int, *, now: datetime | None = None,
                       days: int | None = None) -> str:
    """`<id>.<expiration>.<signature>` : lisible, court, vérifiable sans base de données."""
    now = now or utcnow()
    expires = int((now + timedelta(days=days if days is not None else settings.account_link_days)).timestamp())
    payload = f"{int(subscriber_id)}.{expires}".encode("ascii")
    return f"{payload.decode('ascii')}.{_sign(secret_key(settings), payload)}"


def read_account_token(settings: VMSettings, token: str | None, *, now: datetime | None = None) -> int:
    """Retourne l'identifiant d'abonné, ou lève TokenError (signature invalide ou lien expiré)."""
    if not token:
        raise TokenError("lien manquant")
    parts = token.strip().split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        raise TokenError("lien invalide")
    payload = f"{parts[0]}.{parts[1]}".encode("ascii")
    if not hmac.compare_digest(_sign(secret_key(settings), payload), parts[2]):
        raise TokenError("lien invalide")
    if int(parts[1]) < int((now or utcnow()).timestamp()):
        raise TokenError("lien expiré", expired=True)
    return int(parts[0])


def account_url(settings: VMSettings, subscriber_id: int, *, now: datetime | None = None) -> str:
    return f"{settings.base_url}/compte?token={make_account_token(settings, subscriber_id, now=now)}"


@dataclass
class Recap:
    """Récapitulatif des réglages, partagé par l'email de bienvenue, la page merci et l'espace abonné."""

    plan_name: str
    period_label: str
    price_label: str
    cpv: str
    departments: list[str]
    amount_range: str
    first_digest: datetime
    first_brief: datetime | None


def recap_for(sub: Subscriber, now: datetime | None = None) -> Recap:
    now = now or utcnow()
    plan = PLANS.get(sub.plan, PLANS["essentiel"])
    if sub.amount_min is None and sub.amount_max is None:
        amount = "tous montants"
    elif sub.amount_max is None:
        amount = f"à partir de {sub.amount_min:,.0f} € HT".replace(",", " ")
    elif sub.amount_min is None:
        amount = f"jusqu'à {sub.amount_max:,.0f} € HT".replace(",", " ")
    else:
        amount = f"de {sub.amount_min:,.0f} à {sub.amount_max:,.0f} € HT".replace(",", " ")
    unit = "an" if sub.billing_period == "yearly" else "mois"
    return Recap(
        plan_name=plan.name, period_label=PERIODS.get(sub.billing_period, sub.billing_period),
        price_label=f"{plan.price(sub.billing_period)} € HT / {unit}",
        cpv=", ".join(sub.cpv_prefixes) or "non précisés",
        departments=[department_label(d) for d in sub.departments] or ["toute la France"],
        amount_range=amount, first_digest=next_digest_at(now),
        first_brief=next_weekly_brief_at(now) if sub.plan == "pro" else None,
    )


def send_welcome_email(settings: VMSettings, mailer: Mailer, sub: Subscriber, *, now: datetime | None = None) -> str:
    now = now or utcnow()
    ctx = {"settings": settings, "sub": sub, "recap": recap_for(sub, now), "account_url": account_url(settings, sub.id,
                                                                                                       now=now)}
    subject = f"Bienvenue sur {settings.product_name} : vos premières alertes arrivent"
    email = Email(to=[sub.email], subject=subject, html=render("welcome.html.j2", subject=subject, **ctx),
                  text=render("welcome.txt.j2", subject=subject, **ctx), reply_to=settings.reply_to)
    return mailer.send(email, sender=settings.mail_from)


def send_account_link_email(settings: VMSettings, mailer: Mailer, sub: Subscriber, *,
                            now: datetime | None = None) -> str:
    now = now or utcnow()
    ctx = {"settings": settings, "sub": sub, "account_url": account_url(settings, sub.id, now=now),
           "days": settings.account_link_days}
    subject = f"{settings.product_name} : votre lien d'accès"
    email = Email(to=[sub.email], subject=subject, html=render("account_link.html.j2", subject=subject, **ctx),
                  text=render("account_link.txt.j2", subject=subject, **ctx), reply_to=settings.reply_to)
    return mailer.send(email, sender=settings.mail_from)
