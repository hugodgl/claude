"""Contrat commun des adaptateurs TTS : une liste de phrases → un fichier audio + des timings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class TTSError(RuntimeError):
    """Synthèse impossible (outil absent, clé manquante, erreur API)."""


@dataclass
class Segment:
    text: str
    start: float
    end: float


@dataclass
class TTSResult:
    audio_path: Path | None
    duration_s: float
    segments: list[Segment] = field(default_factory=list)
    provider: str = "silent"
    synthetic: bool = True  # voix synthétique → étiquetage IA sur les plateformes


class TTS(Protocol):
    name: str

    def synthesize(self, sentences: list[str], out_dir: Path) -> TTSResult: ...
