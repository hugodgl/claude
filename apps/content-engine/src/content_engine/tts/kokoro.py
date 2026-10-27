"""TTS local Kokoro (optionnel) via le paquet `kokoro-onnx` ; modèle et voix à télécharger dans data/."""
from __future__ import annotations

from pathlib import Path

from .audio import assemble, write_wav
from .base import TTSError, TTSResult


class KokoroTTS:
    name = "kokoro"

    def __init__(self, model_path: Path, voices_path: Path, voice: str = "ff_siwis",
                 lang: str = "fr-fr", speed: float = 1.0, pause_s: float = 0.3):
        self.model_path, self.voices_path = Path(model_path), Path(voices_path)
        self.voice, self.lang, self.speed, self.pause_s = voice, lang, speed, pause_s
        self._engine = None

    def _load(self):
        if self._engine is None:
            try:
                from kokoro_onnx import Kokoro  # dépendance optionnelle
            except ImportError as e:
                raise TTSError("installer l'extra : uv pip install -e '.[kokoro]'") from e
            if not self.model_path.exists() or not self.voices_path.exists():
                raise TTSError(
                    f"modèle Kokoro absent : {self.model_path} / {self.voices_path} "
                    "(télécharger kokoro-v1.0.onnx et voices-v1.0.bin, voir README)"
                )
            self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        return self._engine

    def synthesize(self, sentences: list[str], out_dir: Path) -> TTSResult:
        engine = self._load()
        out_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        for i, sentence in enumerate(sentences):
            samples, sample_rate = engine.create(sentence, voice=self.voice, speed=self.speed,
                                                 lang=self.lang)
            wav = out_dir / f"tts_{i:02d}.wav"
            write_wav(wav, samples, int(sample_rate))
            parts.append(wav)
        return assemble(parts, sentences, out_dir / "voice.m4a", self.pause_s, self.name)
