"""Adaptateurs de synthèse vocale : say (macOS), kokoro (local), elevenlabs (API), silent (tests)."""
from __future__ import annotations

from ..settings import Settings
from .base import TTS, Segment, TTSError, TTSResult
from .elevenlabs import ElevenLabsTTS
from .kokoro import KokoroTTS
from .say import SayTTS
from .silent import SilentTTS

__all__ = ["TTS", "Segment", "TTSError", "TTSResult", "ElevenLabsTTS", "KokoroTTS", "SayTTS",
           "SilentTTS", "get_tts"]


def get_tts(settings: Settings) -> TTS:
    p = settings.tts_provider
    if p == "silent":
        return SilentTTS(duration_s=settings.tts_silent_duration_s)
    if p == "say":
        return SayTTS(voice=settings.say_voice, rate=settings.say_rate)
    if p == "kokoro":
        return KokoroTTS(settings.kokoro_model_path, settings.kokoro_voices_path,
                         voice=settings.kokoro_voice)
    if p == "elevenlabs":
        if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
            raise TTSError("ELEVENLABS_API_KEY et ELEVENLABS_VOICE_ID sont requis")
        return ElevenLabsTTS(settings.elevenlabs_api_key, settings.elevenlabs_voice_id,
                             settings.elevenlabs_model_id)
    raise TTSError(f"fournisseur TTS inconnu : {p}")
