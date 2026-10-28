"""Conteneur des services partagés (web et CLI) : réglages, base, mail, LLM, SMS, plateformes d'avis, Stripe."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.llm import LLM, get_llm
from core.mail import Mailer, get_mailer

from .auth import SessionSigner
from .billing import StripeGateway
from .crypto import TokenCipher
from .db import Database
from .facebook import build_facebook_client
from .gbp import GoogleAdapter, ReviewsClient, build_gbp_client
from .platforms import PlatformClient
from .settings import AppSettings, get_settings
from .sms import SMSSender, build_sms_sender
from .tripadvisor import build_tripadvisor_client


@dataclass
class Services:
    settings: AppSettings
    db: Database
    mailer: Mailer
    llm: LLM
    sms: SMSSender
    gbp: ReviewsClient  # client Google (mock ou live), conservé tel quel : `platforms["google"]` l'enveloppe
    facebook: PlatformClient
    tripadvisor: PlatformClient
    stripe: StripeGateway
    signer: SessionSigner
    cipher: TokenCipher  # jetons de plateforme chiffrés en base (TOKENS_KEY)
    # recommandations LLM du rapport mensuel déjà calculées (par processus) : l'aperçu web ne doit pas
    # relancer le modèle à chaque affichage de la même page
    report_cache: dict[tuple, tuple[list[str], str]] = field(default_factory=dict)

    @property
    def platforms(self) -> dict[str, PlatformClient]:
        """Un adaptateur par plateforme, sous le même protocole (fabrique `platforms.build_platform_clients`)."""
        return {"google": GoogleAdapter(self.gbp), "facebook": self.facebook, "tripadvisor": self.tripadvisor}


def build_services(settings: AppSettings | None = None, **overrides: Any) -> Services:
    s = settings or get_settings()
    values: dict[str, Any] = dict(
        settings=s,
        db=Database(s.resolved_db_path),
        mailer=get_mailer(s),
        llm=get_llm(s),
        sms=build_sms_sender(s),
        gbp=build_gbp_client(s),
        facebook=build_facebook_client(s),
        tripadvisor=build_tripadvisor_client(s),
        stripe=StripeGateway(s),
        signer=SessionSigner(s.session_secret, s.session_max_age_s),
        cipher=TokenCipher(s.tokens_key),
    )
    values.update(overrides)
    return Services(**values)
