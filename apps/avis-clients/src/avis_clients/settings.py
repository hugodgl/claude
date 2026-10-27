"""Réglages de l'app (hérite des réglages communs : LLM, mail, data_dir)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from core.settings import Settings
from pydantic_settings import SettingsConfigDict

Plan = Literal["none", "solo", "pro", "reseau"]

PLAN_LABELS: dict[str, str] = {"none": "Essai", "solo": "Solo", "pro": "Pro", "reseau": "Réseau"}
PLAN_PRICES_EUR: dict[str, int] = {"solo": 19, "pro": 29, "reseau": 59}
# Quota mensuel de demandes d'avis par SMS / WhatsApp selon la formule.
PLAN_SMS_QUOTA: dict[str, int] = {"none": 0, "solo": 0, "pro": 100, "reseau": 300}
# Nombre d'établissements autorisés selon la formule.
PLAN_MAX_ESTABLISHMENTS: dict[str, int] = {"none": 1, "solo": 1, "pro": 1, "reseau": 5}


class AppSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "Avis Clients"
    app_base_url: str = "http://localhost:8000"
    session_secret: str = "change-me-en-production"
    session_max_age_s: int = 60 * 60 * 24 * 30
    magic_link_ttl_s: int = 60 * 20
    db_path: Path | None = None  # défaut : <data_dir>/avis-clients.db
    trial_days: int = 14
    trial_sms_quota: int = 10  # SMS offerts pendant l'essai, pour tester le parcours
    support_email: str = "contact@example.com"

    # Stripe
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_solo: str | None = None
    stripe_price_pro: str | None = None
    stripe_price_reseau: str | None = None

    # SMS
    sms_provider: Literal["dry-run", "smsmode", "twilio"] = "dry-run"
    sms_sender: str = "AvisClients"  # émetteur alphanumérique (11 caractères max chez smsmode)
    smsmode_api_key: str | None = None
    smsmode_api: Literal["http16", "rest"] = "rest"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from: str | None = None  # numéro Twilio au format E.164
    twilio_whatsapp_from: str | None = None  # ex. whatsapp:+14155238886

    # Google Business Profile
    gbp_mode: Literal["mock", "live"] = "mock"
    gbp_fixtures_file: Path | None = None  # défaut : fixtures livrées avec le paquet
    google_oauth_client_secrets_file: Path | None = None
    google_token_file: Path | None = None  # défaut : <data_dir>/google_token.json

    # Réponses aux avis
    reply_max_words: int = 60
    alert_max_rating: int = 2  # alerte email immédiate pour les avis ≤ 2 étoiles
    auto_publish_min_rating: int = 4

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path or (self.data_dir / "avis-clients.db")

    @property
    def resolved_token_file(self) -> Path:
        return self.google_token_file or (self.data_dir / "google_token.json")

    @property
    def cookie_secure(self) -> bool:
        return self.app_base_url.startswith("https://")

    def stripe_price_for(self, plan: str) -> str | None:
        return {
            "solo": self.stripe_price_solo,
            "pro": self.stripe_price_pro,
            "reseau": self.stripe_price_reseau,
        }.get(plan)

    def plan_for_price(self, price_id: str | None) -> str | None:
        if not price_id:
            return None
        for plan in ("solo", "pro", "reseau"):
            if self.stripe_price_for(plan) == price_id:
                return plan
        return None


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
