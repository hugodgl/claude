"""Réglages de l'app (héritent des réglages communs : LLM, mail, data_dir)."""
from __future__ import annotations

from pathlib import Path

from core.settings import Settings
from pydantic_settings import SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class VMSettings(Settings):
    """Toutes les variables sont lues dans l'environnement ou le fichier `.env` de l'app."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Données
    db_path: Path = Path("data/veille-marches.db")
    out_dir: Path = Path("data/out")

    # Produit
    product_name: str = "Veille marchés"
    trade_label: str = "entreprises d'espaces verts et paysagistes"
    default_cpv_prefixes: str = "773"
    priority_threshold: int = 70
    digest_lookback_days: int = 7
    match_unknown_department: bool = False
    source_label: str = "Côté Marchés"
    reply_to: str | None = None

    # LLM (en plus des réglages communs)
    llm_enabled: bool = True
    llm_max_notices_per_run: int = 200

    # Collecte
    collect_since_days: int = 2
    collect_limit: int = 500
    http_timeout_s: float = 30.0
    http_user_agent: str = "veille-marches/0.1 (+contact: hugo@example.com)"

    # BOAMP
    boamp_base_url: str = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1"
    boamp_dataset: str = "boamp"
    boamp_api_key: str | None = None
    boamp_server_side_cpv: bool = False

    # TED
    ted_base_url: str = "https://api.ted.europa.eu/v3"
    ted_api_key: str | None = None
    ted_country: str = "FRA"
    ted_page_size: int = 100

    # DECP
    decp_base_url: str = "https://data.economie.gouv.fr/api/explore/v2.1"
    decp_dataset: str = "decp-v3"

    # Site public (`vm web`) et espace abonné
    app_base_url: str = "http://localhost:8000"   # URL publique, sans barre finale (liens des emails, retours Stripe)
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    app_secret_key: str | None = None             # signe les liens « espace abonné » ; obligatoire en production
    account_link_days: int = 7                    # durée de validité d'un lien signé

    # Stripe (clés de test `sk_test_…` tant que le produit n'est pas lancé) ; vide = mode mock (paiement simulé)
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_essentiel_monthly: str | None = None
    stripe_price_essentiel_yearly: str | None = None
    stripe_price_pro_monthly: str | None = None
    stripe_price_pro_yearly: str | None = None

    # Mentions légales (placeholders explicites tant qu'Hugo ne les a pas remplis)
    legal_company: str = "[À COMPLÉTER : raison sociale ou nom de l'entrepreneur]"
    legal_address: str = "[À COMPLÉTER : adresse du siège]"
    legal_siren: str = "[À COMPLÉTER : SIREN / RCS]"
    legal_vat: str = "[À COMPLÉTER : numéro de TVA ou mention « TVA non applicable, art. 293 B du CGI »]"
    legal_publisher: str = "[À COMPLÉTER : nom du directeur de la publication]"
    legal_host: str = "[À COMPLÉTER : hébergeur, adresse, téléphone]"
    legal_contact_email: str | None = None        # défaut : REPLY_TO

    @property
    def default_cpv_prefix_list(self) -> list[str]:
        return _csv(self.default_cpv_prefixes)

    @property
    def base_url(self) -> str:
        return self.app_base_url.rstrip("/")

    @property
    def contact_email(self) -> str:
        return self.legal_contact_email or self.reply_to or "[À COMPLÉTER : email de contact]"

    @property
    def stripe_mode(self) -> str:
        """`live` dès qu'une clé secrète est fournie (clé de test ou réelle), sinon `mock` (paiement simulé)."""
        return "live" if self.stripe_secret_key else "mock"

    def stripe_price(self, plan: str, period: str) -> str | None:
        return getattr(self, f"stripe_price_{plan}_{period}", None)

    def plan_for_price(self, price_id: str | None) -> tuple[str, str] | None:
        """Retrouve (formule, période) à partir d'un identifiant de prix Stripe."""
        if not price_id:
            return None
        for plan in ("essentiel", "pro"):
            for period in ("monthly", "yearly"):
                if self.stripe_price(plan, period) == price_id:
                    return plan, period
        return None


def get_settings(**overrides) -> VMSettings:
    return VMSettings(**overrides)
