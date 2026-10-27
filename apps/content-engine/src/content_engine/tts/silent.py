"""TTS muet : aucune voix, timings estimés (tests, aperçus rapides, vidéos à doubler soi-même)."""

from __future__ import annotations

from pathlib import Path

from ..scripts import estimate_duration_s
from .base import Segment, TTSResult


class SilentTTS:
    name = "silent"

    def __init__(self, duration_s: float | None = None, pause_s: float = 0.35):
        self.duration_s = duration_s
        self.pause_s = pause_s

    def synthesize(self, sentences: list[str], out_dir: Path) -> TTSResult:
        estimates = [max(0.8, estimate_duration_s(s)) for s in sentences] or [1.0]
        total = sum(estimates)
        if self.duration_s:
            scale = self.duration_s / total
            estimates = [e * scale for e in estimates]
            total = self.duration_s
        segments, t = [], 0.0
        for text, d in zip(sentences, estimates, strict=False):
            segments.append(Segment(text=text, start=round(t, 3), end=round(t + d, 3)))
            t += d
        return TTSResult(
            audio_path=None,
            duration_s=round(total, 3),
            segments=segments,
            provider=self.name,
            synthetic=False,
        )
