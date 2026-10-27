"""Réglages de l'app (hérite du socle commun : LLM, mail, data_dir)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.settings import Settings as CoreSettings
from pydantic_settings import SettingsConfigDict


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Dossiers
    out_dir: Path = Path("out")
    topics_file: Path = Path("topics.yaml")
    assets_dir: Path = Path("assets")
    assets_synthetic: bool = True  # les images de assets/ sont considérées générées par IA
    timezone: str = "Europe/Paris"

    # Marque et pages de capture
    brand_name: str = "@moncompte"
    landing_url_avis: str = "https://example.com/avis"
    landing_url_marches: str = "https://example.com/marches"
    landing_url_cabinets: str = "https://example.com/cabinets"
    ai_disclosure: str = "Contenu créé avec l'aide d'IA, relu par un humain."

    # Voix
    tts_provider: Literal["silent", "say", "kokoro", "elevenlabs"] = "say"
    say_voice: str = "Thomas"
    say_rate: int = 175
    kokoro_model_path: Path = Path("data/kokoro-v1.0.onnx")
    kokoro_voices_path: Path = Path("data/voices-v1.0.bin")
    kokoro_voice: str = "ff_siwis"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    tts_silent_duration_s: float | None = None

    # Vidéo
    font_path: Path | None = None
    video_codec: str = "libx264"
    video_preset: str = "medium"
    video_crf: int = 20
    video_max_seconds: int = 60

    # YouTube
    youtube_client_secrets_file: Path = Path("data/youtube-client-secret.json")
    youtube_token_file: Path = Path("data/youtube-token.json")
    youtube_privacy_status: Literal["private", "unlisted", "public"] = "private"
    youtube_category_id: str = "27"

    # Pinterest
    pinterest_access_token: str | None = None
    pinterest_board_id: str | None = None
    pinterest_api_base: str = "https://api.pinterest.com"

    # LinkedIn
    linkedin_access_token: str | None = None
    linkedin_author_urn: str | None = None
    linkedin_version: str = "202510"
    linkedin_api_base: str = "https://api.linkedin.com"

    # TikTok
    tiktok_access_token: str | None = None
    tiktok_privacy_level: str = "SELF_ONLY"
    tiktok_api_base: str = "https://open.tiktokapis.com"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "content-engine.db"

    def landing_url(self, product: str) -> str:
        return getattr(self, f"landing_url_{product}", None) or self.landing_url_avis


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
