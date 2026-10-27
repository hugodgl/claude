"""Sous-titres phrase par phrase : découpage, timings proportionnels, fichiers ASS et SRT."""

from __future__ import annotations

import re
from pathlib import Path

from ..products import Palette
from ..tts.base import Segment

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=\S)")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+")


def split_sentences(parts: list[str], max_chars: int = 85) -> list[list[str]]:
    """Pour chaque partie (hook, phrases du corps, CTA), la liste de ses phrases affichables."""
    result: list[list[str]] = []
    for part in parts:
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(" ".join(part.split())) if s.strip()]
        out: list[str] = []
        for s in sentences:
            if len(s) <= max_chars:
                out.append(s)
                continue
            # phrase longue : on coupe aux virgules, en regroupant jusqu'à max_chars
            buf = ""
            for clause in _CLAUSE_SPLIT.split(s):
                if buf and len(buf) + 1 + len(clause) > max_chars:
                    out.append(buf.strip())
                    buf = clause
                else:
                    buf = f"{buf} {clause}".strip()
            if buf:
                out.append(buf.strip())
        result.append(out or [part.strip()])
    return result


def proportional_segments(
    sentences: list[str], total_s: float, lead_in_s: float = 0.0, min_s: float = 0.6
) -> list[Segment]:
    """Répartit `total_s` entre les phrases au prorata de leur longueur (sans timings TTS)."""
    if not sentences:
        return []
    weights = [max(1, len(s)) for s in sentences]
    available = max(0.0, total_s - lead_in_s)
    unit = available / sum(weights)
    segments, t = [], lead_in_s
    for s, w in zip(sentences, weights, strict=True):
        d = max(min_s, w * unit) if available > min_s * len(sentences) else w * unit
        segments.append(Segment(text=s, start=round(t, 3), end=round(min(total_s, t + d), 3)))
        t += d
    return segments


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB → &HAABBGGRR (format ASS)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def write_ass(
    segments: list[Segment],
    path: Path,
    font_family: str,
    palette: Palette,
    play_res: tuple[int, int] = (1080, 1920),
    font_size: int = 66,
    accent_first: bool = True,
) -> Path:
    w, h = play_res
    style_fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    margin = int(w * 0.07)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {w}",
        f"PlayResY: {h}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        style_fmt,
        f"Style: Sub,{font_family},{font_size},{ass_color(palette.text)},{ass_color(palette.text)},"
        f"{ass_color('#000000')},{ass_color('#000000', 128)},-1,0,0,0,100,100,0,0,1,5,1,5,"
        f"{margin},{margin},0,1",
        f"Style: Hook,{font_family},{font_size + 6},{ass_color(palette.accent)},"
        f"{ass_color(palette.accent)},{ass_color('#000000')},{ass_color('#000000', 128)},"
        f"-1,0,0,0,100,100,0,0,1,5,1,5,{margin},{margin},0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i, seg in enumerate(segments):
        style = "Hook" if (accent_first and i == 0) else "Sub"
        lines.append(
            f"Dialogue: 0,{ass_time(seg.start)},{ass_time(seg.end)},{style},,0,0,0,,"
            f"{_ass_escape(seg.text)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_srt(segments: list[Segment], path: Path) -> Path:
    blocks = [
        f"{i}\n{srt_time(seg.start)} --> {srt_time(seg.end)}\n{seg.text}\n"
        for i, seg in enumerate(segments, start=1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path
