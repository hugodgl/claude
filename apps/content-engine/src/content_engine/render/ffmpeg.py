"""Enveloppe ffmpeg / ffprobe : exécution, sonde, police, utilitaires de texte."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path


class RenderError(RuntimeError):
    """ffmpeg absent ou commande en échec."""


def ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"


def have_ffmpeg() -> bool:
    return shutil.which(ffmpeg_bin()) is not None and shutil.which(ffprobe_bin()) is not None


def ffmpeg_version() -> str | None:
    try:
        out = subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.stdout.splitlines()[0] if out.stdout else ""
    return first.replace("ffmpeg version ", "").split(" ")[0] or None


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    if shutil.which(cmd[0]) is None:
        raise RenderError(f"{cmd[0]} introuvable : installer ffmpeg (brew install ffmpeg)")
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"{cmd[0]} : délai dépassé ({timeout} s)") from e
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-1200:]
        raise RenderError(f"{cmd[0]} a échoué (code {proc.returncode}) :\n{tail}")
    return proc


@dataclass
class ProbeInfo:
    path: Path
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None


def probe(path: str | Path) -> ProbeInfo:
    proc = run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    data = json.loads(proc.stdout or "{}")
    info = ProbeInfo(path=Path(path))
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        info.duration_s = float(fmt["duration"])
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.width, info.height = int(s.get("width", 0)), int(s.get("height", 0))
            info.video_codec = s.get("codec_name")
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            try:
                info.fps = round(float(num) / float(den or 1), 3)
            except (ValueError, ZeroDivisionError):
                info.fps = 0.0
            if not info.duration_s and s.get("duration"):
                info.duration_s = float(s["duration"])
        elif s.get("codec_type") == "audio":
            info.has_audio = True
            if not info.duration_s and s.get("duration"):
                info.duration_s = float(s["duration"])
    return info


def probe_duration(path: str | Path) -> float:
    return probe(path).duration_s


FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ("/opt/homebrew/share/fonts/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ("/usr/local/share/fonts/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ("~/Library/Fonts/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ("/Library/Fonts/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "Arial"),
    ("/Library/Fonts/Arial Bold.ttf", "Arial"),
    ("/System/Library/Fonts/Helvetica.ttc", "Helvetica"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "Liberation Sans"),
]


@dataclass
class FontInfo:
    path: Path | None
    family: str

    @property
    def found(self) -> bool:
        return self.path is not None


def find_font(preferred: Path | None = None) -> FontInfo:
    """Police pour drawtext et libass : DejaVu si présente, sinon police système, sinon défaut."""
    if preferred:
        p = Path(preferred).expanduser()
        if p.exists():
            name = p.stem
            family = next((fam for _, fam in FONT_CANDIDATES if fam.replace(" ", "") in name), None)
            return FontInfo(p, family or name.split("-")[0])
    for cand, family in FONT_CANDIDATES:
        p = Path(cand).expanduser()
        if p.exists():
            return FontInfo(p, family)
    return FontInfo(None, "Helvetica" if platform.system() == "Darwin" else "Sans")


def wrap_text(text: str, max_chars: int, max_lines: int | None = None) -> str:
    lines = textwrap.wrap(" ".join(text.split()), width=max_chars, break_long_words=True)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,;:") + "…"
    return "\n".join(lines)
