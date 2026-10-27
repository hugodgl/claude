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

    @property
    def default_cpv_prefix_list(self) -> list[str]:
        return _csv(self.default_cpv_prefixes)


def get_settings(**overrides) -> VMSettings:
    return VMSettings(**overrides)
