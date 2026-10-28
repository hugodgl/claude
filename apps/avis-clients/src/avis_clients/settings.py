"""Réglages de l'app (hérite des réglages communs : LLM, mail, data_dir)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from core.settings import Settings
from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

Plan = Literal["none", "solo", "pro", "reseau"]

# Valeurs de SESSION_SECRET refusées dès que l'app est servie en https (production).
INSECURE_SESSION_SECRETS = {"", "change-me-en-production", "remplacez-par-une-longue-chaine-aleatoire", "secret",
                            "changeme", "change-me"}
MIN_SESSION_SECRET_LENGTH = 32

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
    app_timezone: str = "Europe/Paris"  # mois des quotas et des rapports, affichage des dates

    # Stripe
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_solo: str | None = None
    stripe_price_pro: str | None = None
    stripe_price_reseau: str | None = None

    # SMS
    sms_provider: Literal["dry-run", "smsmode", "twilio"] = "dry-run"
    sms_sender: str = "AvisClients"  # émetteur alphanumérique (11 caractères max chez smsmode)
    # Jeton partagé exigé sur le webhook SMS entrant (paramètre `token`), indispensable avec smsmode qui ne
    # signe pas ses callbacks ; avec Twilio, la signature X-Twilio-Signature est vérifiée à la place.
    sms_webhook_token: str | None = None
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

    # Facebook (Graph API, jeton de Page par source, chiffré avec TOKENS_KEY)
    facebook_mode: Literal["mock", "live"] = "mock"
    facebook_fixtures_file: Path | None = None  # défaut : fixtures livrées avec le paquet
    facebook_graph_version: str = "v21.0"

    # Tripadvisor (Content API : lecture des 5 derniers avis, clé globale, pas de réponse par API)
    tripadvisor_mode: Literal["mock", "live"] = "mock"
    tripadvisor_fixtures_file: Path | None = None
    tripadvisor_api_key: str | None = None
    tripadvisor_poll_interval_min: int = 360  # quota mensuel limité : au plus un appel par fiche toutes les 6 h

    # Chiffrement des jetons de plateforme stockés en base (clé Fernet, distincte de SESSION_SECRET)
    tokens_key: str | None = None

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

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> AppSettings:
        """Servie en https (production), l'app refuse de démarrer avec un SESSION_SECRET absent ou factice."""
        secret = (self.session_secret or "").strip()
        if self.cookie_secure and (secret in INSECURE_SESSION_SECRETS or len(secret) < MIN_SESSION_SECRET_LENGTH):
            raise ValueError(
                "SESSION_SECRET manquant ou trop faible pour une URL https : générez-le avec "
                "python -c \"import secrets;print(secrets.token_hex(32))\" et placez-le dans .env"
            )
        return self

    @model_validator(mode="after")
    def _require_platform_credentials_in_live(self) -> AppSettings:
        """Les modes `live` exigent leurs secrets au démarrage plutôt qu'au premier poll, deux heures plus tard."""
        from .crypto import MISSING_KEY_MESSAGE, is_valid_fernet_key

        if self.tokens_key and not is_valid_fernet_key(self.tokens_key):
            raise ValueError("TOKENS_KEY invalide : attendu une clé Fernet (44 caractères base64 url-safe).")
        if self.facebook_mode == "live" and not self.tokens_key:
            raise ValueError(f"FACEBOOK_MODE=live exige le chiffrement des jetons de Page. {MISSING_KEY_MESSAGE}")
        if self.tripadvisor_mode == "live" and not (self.tripadvisor_api_key or "").strip():
            raise ValueError("TRIPADVISOR_MODE=live exige TRIPADVISOR_API_KEY (clé Content API).")
        if self.tripadvisor_poll_interval_min < 0:
            raise ValueError("TRIPADVISOR_POLL_INTERVAL_MIN doit être positif ou nul.")
        return self

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
