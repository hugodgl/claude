"""Réglages de l'app : hérite du socle commun (LLM, mail, data_dir) et ajoute les siens.

Les chemins relatifs sont résolus depuis le dossier courant (le lanceur launchd se place dans
`apps/newsletter-pipeline`). Les fichiers livrés avec l'app (`sources.yaml`, `style.md`, `cases/`)
sont cherchés par défaut à la racine de l'app, quel que soit le dossier courant.
"""
from __future__ import annotations

from pathlib import Path

from core.settings import Settings as CoreSettings
from pydantic import Field

APP_ROOT = Path(__file__).resolve().parents[2]

THEMES: tuple[str, ...] = (
    "tenue", "revision", "social", "fiscal", "relation_client",
    "recrutement", "outils", "reglementation", "ia_generale",
)


class Settings(CoreSettings):
    # Identité de la newsletter
    newsletter_name: str = "L'IA en cabinet"
    newsletter_tagline: str = "Chaque mardi, ce que l'IA change pour votre cabinet, en 5 minutes."
    author_name: str = "Hugo"
    author_signature: str = "Hugo"  # affiché après « relue et signée par un humain : »
    reply_to_email: str | None = None
    archive_url: str | None = None  # page d'archives publique (beehiiv, Kessel…)

    # Fichiers et dossiers
    sources_file: Path = APP_ROOT / "sources.yaml"
    style_file: Path = APP_ROOT / "style.md"
    cases_dir: Path = APP_ROOT / "cases"
    sponsor_file: Path = APP_ROOT / "sponsor.yaml"
    issues_dir: Path = Path("issues")
    out_dir: Path = Path("out")
    db_name: str = "newsletter.db"

    # Collecte
    request_delay_s: float = 1.5  # délai de politesse entre deux requêtes HTTP
    http_timeout_s: float = 20.0
    user_agent: str = "newsletter-pipeline/0.1 (+veille IA cabinets comptables ; contact : voir .env)"
    max_links_per_page: int = 8  # liens d'articles suivis par source de type `page` et par passage
    rss_fetch_pages: bool = False  # True : télécharge l'article complet derrière chaque entrée RSS
    max_content_chars: int = 20000  # taille max du texte stocké par item
    max_page_bytes: int = 5_000_000  # taille max d'une réponse HTTP (flux ou page) ; au-delà, source en erreur

    # Classement
    rank_batch_size: int = 5
    rank_max_chars: int = 1500  # extrait d'article envoyé au modèle par item
    weight_pertinence: float = 0.5
    weight_actionnable: float = 0.3
    weight_nouveaute: float = 0.2
    rank_default_limit: int = 60

    # Sélection
    issue_items: int = 8
    max_per_theme: int = 2
    max_per_source: int = 3
    max_item_age_days: int = 14  # 0 = pas de filtre d'ancienneté à la sélection

    # Push
    beehiiv_api_key: str | None = None
    beehiiv_publication_id: str | None = None
    beehiiv_base_url: str = "https://api.beehiiv.com/v2"
    beehiiv_content_tags: list[str] = Field(default_factory=lambda: ["ia", "cabinets"])
    kessel_publication_url: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_name


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
