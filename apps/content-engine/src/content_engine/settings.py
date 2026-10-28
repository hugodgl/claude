"""Réglages de l'app (hérite du socle commun : LLM, mail, data_dir)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.settings import Settings as CoreSettings
from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

DEFAULT_AI_DISCLOSURE = "Contenu créé avec l'aide d'IA, relu par un humain."


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
    ai_disclosure: str = DEFAULT_AI_DISCLOSURE

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
    # Demander aussi la portée yt-analytics.readonly au consentement OAuth (rétention, partages
    # via YouTube Analytics) ; sans elle, `ce metrics --pull` se limite à videos.list.
    youtube_analytics: bool = True

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
    tiktok_privacy_level: Literal[
        "SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"
    ] = "SELF_ONLY"
    # Tant que l'app TikTok n'a pas passé l'audit Content Posting, la visibilité est forcée à
    # SELF_ONLY quoi que dise TIKTOK_PRIVACY_LEVEL (voir `tiktok_effective_privacy`).
    tiktok_app_audited: bool = False
    tiktok_api_base: str = "https://open.tiktokapis.com"

    # Sélection des angles (P4-4) : part d'exploration dans `ce run-daily`, lissage bayésien
    # (pseudo-observations), pause automatique d'un angle nettement sous la médiane.
    angle_exploration_rate: float = 0.3
    angle_prior_weight: float = 5.0
    angle_pause_min_contents: int = 6
    angle_pause_ratio: float = 0.5  # en pause si ses vues lissées < 50 % de l'angle médian

    @field_validator("angle_exploration_rate", "angle_pause_ratio")
    @classmethod
    def _unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("valeur attendue entre 0 et 1")
        return v

    @field_validator("angle_prior_weight")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("valeur positive attendue")
        return v

    @field_validator("ai_disclosure", mode="before")
    @classmethod
    def _disclosure_never_blank(cls, v):
        """L'étiquette IA ne peut pas être vidée par la configuration : repli sur le défaut."""
        text = " ".join(str(v or "").split())
        return text or DEFAULT_AI_DISCLOSURE

    @property
    def db_path(self) -> Path:
        return self.data_dir / "content-engine.db"

    @property
    def tiktok_effective_privacy(self) -> str:
        return self.tiktok_privacy_level if self.tiktok_app_audited else "SELF_ONLY"

    def landing_url(self, product: str) -> str:
        return getattr(self, f"landing_url_{product}", None) or self.landing_url_avis
