"""TTS macOS intégré : `say` → AIFF par phrase → concaténation ffmpeg (timings exacts)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .audio import assemble
from .base import TTSError, TTSResult


class SayTTS:
    name = "say"

    def __init__(self, voice: str = "Thomas", rate: int = 175, pause_s: float = 0.3):
        self.voice, self.rate, self.pause_s = voice, rate, pause_s

    def synthesize(self, sentences: list[str], out_dir: Path) -> TTSResult:
        if shutil.which("say") is None:
            raise TTSError("commande `say` introuvable : TTS_PROVIDER=say ne marche que sur macOS")
        out_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        for i, sentence in enumerate(sentences):
            txt = out_dir / f"tts_{i:02d}.txt"
            aiff = out_dir / f"tts_{i:02d}.aiff"
            txt.write_text(sentence, encoding="utf-8")
            try:
                proc = subprocess.run(
                    ["say", "-v", self.voice, "-r", str(self.rate), "-o", str(aiff), "-f", str(txt)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired as e:
                raise TTSError(f"say bloqué plus de 180 s sur la phrase {i + 1}") from e
            if proc.returncode != 0 or not aiff.exists():
                raise TTSError(f"say a échoué (voix {self.voice!r}) : {proc.stderr.strip()[:300]}")
            parts.append(aiff)
        return assemble(parts, sentences, out_dir / "voice.m4a", self.pause_s, self.name)
