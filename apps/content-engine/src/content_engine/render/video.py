"""Rendu d'un brouillon : vidéo verticale 1080×1920 (short), couverture et miniature (short, pin,
long), texte prêt à coller (linkedin). Tout passe par une commande ffmpeg lancée dans out/<id>/."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from ..db import utc_now_iso
from ..products import Product, get_product
from ..scripts import draft_payload, get_draft, narration_parts, set_draft_status
from ..settings import Settings
from ..texts import compose_linkedin_post, teleprompter_text
from ..tts.base import TTS, TTSResult
from .ffmpeg import (
    FontInfo,
    RenderError,
    ffmpeg_bin,
    ffmpeg_version,
    find_font,
    probe,
    run,
    wrap_text,
)
from .subtitles import proportional_segments, split_sentences, write_ass, write_srt

WIDTH, HEIGHT, FPS = 1080, 1920, 30
THUMB_W, THUMB_H = 1280, 720
IMAGE_EXTS = (".jpg", ".jpeg", ".png")


@dataclass
class RenderResult:
    draft_id: int
    format: str
    out_dir: str
    video: str | None = None
    thumb: str | None = None
    cover: str | None = None
    audio: str | None = None
    ass: str | None = None
    srt: str | None = None
    text_file: str | None = None
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    tts_provider: str = "none"
    synthetic_voice: bool = False
    synthetic_image: bool = False
    rendered_at: str = ""
    ffmpeg: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def find_asset(assets_dir: Path, slug: str) -> Path | None:
    assets_dir = Path(assets_dir)
    for ext in IMAGE_EXTS:
        p = assets_dir / f"{slug}{ext}"
        if p.exists():
            return p
    folder = assets_dir / slug
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in IMAGE_EXTS:
                return p
    return None


def _font_file(font: FontInfo, out_dir: Path) -> str | None:
    """Copie la police dans le dossier de rendu : chemins relatifs, zéro échappement ffmpeg."""
    if not font.path:
        return None
    dest = out_dir / f"font{font.path.suffix.lower()}"
    if not dest.exists() or dest.stat().st_size != font.path.stat().st_size:
        shutil.copyfile(font.path, dest)
    return dest.name


def _drawtext(
    font_file: str | None,
    font_family: str,
    textfile: str,
    size: int,
    color: str,
    x: str,
    y: str,
    boxcolor: str | None = None,
    border: int = 0,
    line_spacing: int = 12,
    enable: str | None = None,
) -> str:
    opts = [
        f"fontfile={font_file}" if font_file else f"font={font_family}",
        f"textfile={textfile}",
        f"fontsize={size}",
        f"fontcolor={color}",
        f"x={x}",
        f"y={y}",
        f"line_spacing={line_spacing}",
    ]
    if boxcolor:
        opts += ["box=1", f"boxcolor={boxcolor}", f"boxborderw={border}"]
    if enable:
        opts.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(opts)


def _background(
    product: Product,
    settings: Settings,
    duration_s: float,
    w: int,
    h: int,
    horizontal: bool = False,
) -> tuple[list[str], str, bool]:
    """Entrée ffmpeg du fond + préfixe de filtre + drapeau « image synthétique »."""
    img = find_asset(settings.assets_dir, product.slug)
    if img:
        args = [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{duration_s:.3f}",
            "-i",
            str(img.resolve()),
        ]
        pre = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
            "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill,"
        )
        return args, pre, settings.assets_synthetic
    pal = product.palette
    x1, y1 = (w, 0) if horizontal else (w, h)
    src = (
        f"gradients=size={w}x{h}:c0={pal.bg0}:c1={pal.bg1}:x0=0:y0=0:x1={x1}:y1={y1}:"
        f"nb_colors=2:duration={duration_s:.3f}:speed=0.01:rate={FPS}"
    )
    return ["-f", "lavfi", "-i", src], "", False


def _encode_args(settings: Settings) -> list[str]:
    if settings.video_codec == "libx264":
        return [
            "-c:v",
            "libx264",
            "-preset",
            settings.video_preset,
            "-crf",
            str(settings.video_crf),
        ]
    return ["-c:v", settings.video_codec, "-b:v", "6M"]


CHAR_WIDTH_RATIO = 0.66  # largeur moyenne d'un caractère DejaVu Sans Bold, en em


def fit_chars(width_px: int, font_size: int, margin_px: int = 60, border_px: int = 0) -> int:
    """Nombre de caractères qui tiennent sur une ligne, marges et bordure de boîte déduites."""
    usable = width_px - 2 * margin_px - 2 * border_px
    return max(8, int(usable / (font_size * CHAR_WIDTH_RATIO)))


def _title_layout(title: str, width: int = WIDTH) -> tuple[str, int]:
    text = wrap_text(title, fit_chars(width, 64, border_px=26), 3)
    if text.count("\n") >= 2:
        return wrap_text(title, fit_chars(width, 54, border_px=26), 3), 54
    return text, 64


def render_video(
    payload: dict, product: Product, out_dir: Path, settings: Settings, tts: TTS, font: FontInfo
) -> tuple[Path, TTSResult, float]:
    """Vidéo verticale : fond, barre de progression, titre, sous-titres, CTA, marque."""
    out_dir.mkdir(parents=True, exist_ok=True)
    grouped = split_sentences(narration_parts(payload))
    sentences = [s for g in grouped for s in g]
    cta_index = sum(len(g) for g in grouped[:-1])
    tts_result = tts.synthesize(sentences, out_dir)
    narration_s = tts_result.duration_s
    if narration_s > settings.video_max_seconds:
        raise RenderError(
            f"narration de {narration_s:.0f} s > {settings.video_max_seconds} s : raccourcir le "
            "script (ou relever VIDEO_MAX_SECONDS)"
        )
    total_s = round(min(float(settings.video_max_seconds), max(3.0, narration_s + 0.6)), 3)
    segments = tts_result.segments
    if len(segments) != len(sentences):
        segments = proportional_segments(sentences, narration_s)
    # le CTA est affiché dans son encart : on ne l'incruste pas une seconde fois en sous-titre
    write_ass(segments[:cta_index] or segments, out_dir / "subs.ass", font.family, product.palette)
    write_srt(segments, out_dir / "subs.srt")
    cta_from = segments[cta_index].start if cta_index < len(segments) else max(0.0, total_s - 4)

    title_text, title_size = _title_layout(payload["title"])
    (out_dir / "title.txt").write_text(title_text, encoding="utf-8")
    (out_dir / "cta.txt").write_text(
        wrap_text(payload["cta"], fit_chars(WIDTH, 48, 60, 28), 3), encoding="utf-8"
    )
    (out_dir / "brand.txt").write_text(settings.brand_name, encoding="utf-8")
    font_file = _font_file(font, out_dir)
    pal = product.palette

    bg_args, pre, _ = _background(product, settings, total_s, WIDTH, HEIGHT)
    audio_args = (
        ["-i", tts_result.audio_path.name]
        if tts_result.audio_path
        else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    )
    chain = (
        f"[0:v]{pre}"
        f"drawbox=x=0:y=ih-18:w='iw*t/{total_s}':h=18:color={pal.accent}@0.95:t=fill,"
        + _drawtext(
            font_file,
            font.family,
            "title.txt",
            title_size,
            "white",
            "(w-text_w)/2",
            "150",
            boxcolor="black@0.35",
            border=26,
            line_spacing=14,
        )
        + ","
        + _drawtext(font_file, font.family, "brand.txt", 34, "white@0.85", "(w-text_w)/2", "h-120")
        + ","
        + _drawtext(
            font_file,
            font.family,
            "cta.txt",
            48,
            pal.accent_text,
            "(w-text_w)/2",
            "h-470",
            boxcolor=pal.accent,
            border=28,
            enable=f"gte(t,{cta_from:.3f})",
        )
        + ",subtitles=subs.ass:fontsdir=.,format=yuv420p[v]"
    )
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *bg_args,
        *audio_args,
        "-filter_complex",
        chain,
        "-map",
        "[v]",
        "-map",
        "1:a",
        "-af",
        "apad",
        "-r",
        str(FPS),
        "-t",
        f"{total_s}",
        *_encode_args(settings),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "video.mp4",
    ]
    run(cmd, cwd=out_dir)
    (out_dir / "ffmpeg-command.txt").write_text(" ".join(cmd), encoding="utf-8")
    return out_dir / "video.mp4", tts_result, total_s


def render_still(
    product: Product,
    out_dir: Path,
    settings: Settings,
    font: FontInfo,
    name: str,
    size: tuple[int, int],
    blocks: list[dict],
) -> Path:
    """Image fixe (JPEG) composée de blocs de texte ; `blocks` : dicts pour `_drawtext`."""
    w, h = size
    out_dir.mkdir(parents=True, exist_ok=True)
    font_file = _font_file(font, out_dir)
    bg_args, pre, _ = _background(product, settings, 1.0, w, h, horizontal=w > h)
    pal = product.palette
    parts = [f"[0:v]{pre}drawbox=x=0:y=ih-24:w=iw:h=24:color={pal.accent}:t=fill"]
    for i, b in enumerate(blocks):
        tf = f"{name}_{i}.txt"
        (out_dir / tf).write_text(b["text"], encoding="utf-8")
        parts.append(
            _drawtext(
                font_file,
                font.family,
                tf,
                b["size"],
                b.get("color", "white"),
                b.get("x", "(w-text_w)/2"),
                b["y"],
                boxcolor=b.get("boxcolor"),
                border=b.get("border", 0),
                line_spacing=b.get("line_spacing", 12),
            )
        )
    chain = ",".join(parts) + ",format=yuv420p[v]"
    out = out_dir / f"{name}.jpg"
    run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *bg_args,
            "-filter_complex",
            chain,
            "-map",
            "[v]",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            out.name,
        ],
        cwd=out_dir,
    )
    return out


def render_thumb(
    payload: dict, product: Product, out_dir: Path, settings: Settings, font: FontInfo
) -> Path:
    blocks = [
        {
            "text": wrap_text(payload["title"], fit_chars(THUMB_W, 68, 80, 30), 4),
            "size": 68,
            "x": "80",
            "y": "(h-text_h)/2",
            "boxcolor": "black@0.3",
            "border": 30,
            "line_spacing": 16,
        },
        {
            "text": settings.brand_name,
            "size": 36,
            "color": "white@0.85",
            "x": "w-text_w-60",
            "y": "h-100",
        },
    ]
    return render_still(product, out_dir, settings, font, "thumb", (THUMB_W, THUMB_H), blocks)


def render_cover(
    payload: dict, product: Product, out_dir: Path, settings: Settings, font: FontInfo, fmt: str
) -> Path:
    pal = product.palette
    if fmt == "pin":
        middle = "\n".join(
            "• " + wrap_text(p, fit_chars(WIDTH, 44, 90) - 2, 2).replace("\n", "\n   ")
            for p in payload["body"][:5]
        )
        blocks = [
            {
                "text": wrap_text(payload["title"], fit_chars(WIDTH, 68, 60, 30), 4),
                "size": 68,
                "y": "220",
                "boxcolor": "black@0.3",
                "border": 30,
                "line_spacing": 16,
            },
            {"text": middle, "size": 44, "x": "90", "y": "820", "line_spacing": 22},
        ]
    else:
        blocks = [
            {
                "text": wrap_text(payload["title"], fit_chars(WIDTH, 76, 60, 30), 4),
                "size": 76,
                "y": "300",
                "boxcolor": "black@0.3",
                "border": 30,
                "line_spacing": 18,
            },
            {
                "text": wrap_text(payload["hook"], fit_chars(WIDTH, 48, 70), 4),
                "size": 48,
                "color": pal.accent,
                "y": "980",
                "line_spacing": 16,
            },
        ]
    blocks += [
        {
            "text": wrap_text(payload["cta"], fit_chars(WIDTH, 46, 60, 28), 3),
            "size": 46,
            "color": pal.accent_text,
            "y": "h-520",
            "boxcolor": pal.accent,
            "border": 28,
        },
        {"text": settings.brand_name, "size": 36, "color": "white@0.85", "y": "h-150"},
    ]
    return render_still(product, out_dir, settings, font, "cover", (WIDTH, HEIGHT), blocks)


def render_draft(
    conn: sqlite3.Connection,
    draft_id: int,
    settings: Settings,
    tts: TTS | None = None,
    *,
    force: bool = False,
) -> RenderResult:
    """Rend un brouillon dans out/<id>/ et passe son statut à `rendered` (s'il était approuvé)."""
    row = get_draft(conn, draft_id)
    if row["status"] not in ("approved", "rendered") and not force:
        raise ValueError(
            f"brouillon #{draft_id} en statut « {row['status']} » : approuver d'abord "
            f"(ce approve {draft_id}) ou utiliser --force pour un aperçu"
        )
    payload = draft_payload(row)
    product = get_product(row["product"])
    fmt = row["format"]
    out_dir = Path(settings.out_dir) / str(draft_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    font = find_font(settings.font_path)
    result = RenderResult(
        draft_id=draft_id,
        format=fmt,
        out_dir=str(out_dir),
        rendered_at=utc_now_iso(),
        ffmpeg=ffmpeg_version(),
    )

    if fmt == "short":
        if tts is None:
            from ..tts import get_tts  # import tardif : évite un cycle tts ↔ render

            tts = get_tts(settings)
        video, tts_result, total_s = render_video(payload, product, out_dir, settings, tts, font)
        info = probe(video)
        result.video, result.duration_s = video.name, round(info.duration_s or total_s, 3)
        result.width, result.height = info.width, info.height
        result.audio = tts_result.audio_path.name if tts_result.audio_path else None
        result.ass, result.srt = "subs.ass", "subs.srt"
        result.tts_provider, result.synthetic_voice = tts_result.provider, tts_result.synthetic
    elif fmt == "long":
        (out_dir / "script.txt").write_text(teleprompter_text(payload), encoding="utf-8")
        result.text_file = "script.txt"
    elif fmt == "linkedin":
        (out_dir / "post.txt").write_text(
            compose_linkedin_post(payload, product, settings), encoding="utf-8"
        )
        result.text_file = "post.txt"
    if fmt in ("short", "pin", "long"):
        result.cover = render_cover(payload, product, out_dir, settings, font, fmt).name
        result.thumb = render_thumb(payload, product, out_dir, settings, font).name
        result.synthetic_image = _background(product, settings, 1.0, WIDTH, HEIGHT)[2]
    (out_dir / "render.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if row["status"] in ("approved", "rendered"):
        set_draft_status(conn, draft_id, "rendered")
    return result


def load_render_info(out_dir: Path) -> dict | None:
    p = Path(out_dir) / "render.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
