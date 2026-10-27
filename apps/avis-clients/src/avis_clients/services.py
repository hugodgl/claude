"""Conteneur des services partagés (web et CLI) : réglages, base, mail, LLM, SMS, Google, Stripe."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.llm import LLM, get_llm
from core.mail import Mailer, get_mailer

from .auth import SessionSigner
from .billing import StripeGateway
from .db import Database
from .gbp import ReviewsClient, build_gbp_client
from .settings import AppSettings, get_settings
from .sms import SMSSender, build_sms_sender


@dataclass
class Services:
    settings: AppSettings
    db: Database
    mailer: Mailer
    llm: LLM
    sms: SMSSender
    gbp: ReviewsClient
    stripe: StripeGateway
    signer: SessionSigner


def build_services(settings: AppSettings | None = None, **overrides: Any) -> Services:
    s = settings or get_settings()
    values: dict[str, Any] = dict(
        settings=s,
        db=Database(s.resolved_db_path),
        mailer=get_mailer(s),
        llm=get_llm(s),
        sms=build_sms_sender(s),
        gbp=build_gbp_client(s),
        stripe=StripeGateway(s),
        signer=SessionSigner(s.session_secret, s.session_max_age_s),
    )
    values.update(overrides)
    return Services(**values)
