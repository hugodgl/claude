"""TTS ElevenLabs (API, payant) : une requête par phrase pour garder des timings exacts."""

from __future__ import annotations

from pathlib import Path

import httpx

from .audio import assemble
from .base import TTSError, TTSResult


class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        client: httpx.Client | None = None,
        pause_s: float = 0.3,
        base_url: str = "https://api.elevenlabs.io",
    ):
        self.api_key, self.voice_id, self.model_id, self.pause_s = (
            api_key,
            voice_id,
            model_id,
            pause_s,
        )
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    def synthesize(self, sentences: list[str], out_dir: Path) -> TTSResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        for i, sentence in enumerate(sentences):
            try:
                r = self._client.post(
                    f"{self.base_url}/v1/text-to-speech/{self.voice_id}",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                    json={"text": sentence, "model_id": self.model_id},
                )
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise TTSError(
                    f"ElevenLabs HTTP {e.response.status_code} : {e.response.text[:200]}"
                ) from e
            except httpx.HTTPError as e:
                raise TTSError(f"ElevenLabs injoignable : {e}") from e
            mp3 = out_dir / f"tts_{i:02d}.mp3"
            mp3.write_bytes(r.content)
            parts.append(mp3)
        return assemble(parts, sentences, out_dir / "voice.m4a", self.pause_s, self.name)
