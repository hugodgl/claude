"""Réglages communs, lus depuis l'environnement et un fichier .env (jamais commité)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Les apps peuvent hériter de cette classe pour ajouter leurs propres réglages."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: Literal["mock", "ollama", "anthropic"] = "ollama"
    llm_timeout_s: float = 180.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"
    ollama_think: bool = False  # désactive le mode « réflexion » de Qwen3 pour des réponses rapides
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    anthropic_fallbacks: bool = True  # bascule serveur vers un autre modèle en cas de refus de sécurité

    # Mail
    mail_provider: Literal["console", "smtp", "resend"] = "console"
    mail_from: str = "Side project <noreply@example.com>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    resend_api_key: str | None = None

    # Données
    data_dir: Path = Path("data")


def get_settings(**overrides) -> Settings:
    """Instancie les réglages (environnement + .env), avec surcharges explicites pour les tests."""
    return Settings(**overrides)
