"""Publication : dry-run par défaut (fichier JSON décrivant la requête), envoi réel avec --live."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..db import utc_now_iso
from ..products import get_product
from ..scripts import draft_payload, get_draft, set_draft_status
from ..settings import Settings
from .base import (
    PublishContext,
    Publisher,
    PublishError,
    PublishOutcome,
    PublishPlan,
    PublishRequest,
    write_dry_run,
)
from .linkedin import LinkedInPublisher
from .pinterest import PinterestPublisher
from .tiktok import TikTokPublisher
from .youtube import YouTubePublisher

__all__ = [
    "PLATFORMS",
    "PLATFORM_FORMATS",
    "PublishContext",
    "PublishError",
    "PublishOutcome",
    "PublishPlan",
    "PublishReport",
    "PublishRequest",
    "Publisher",
    "build_context",
    "get_publisher",
    "publish_draft",
]

PUBLISHERS: dict[str, type] = {
    "youtube": YouTubePublisher,
    "pinterest": PinterestPublisher,
    "linkedin": LinkedInPublisher,
    "tiktok": TikTokPublisher,
}
PLATFORMS = tuple(PUBLISHERS)
PLATFORM_FORMATS = {
    "youtube": ("short", "long"),
    "tiktok": ("short",),
    "pinterest": ("pin", "short"),
    "linkedin": ("linkedin",),
}


def get_publisher(platform: str, **kwargs) -> Publisher:
    try:
        return PUBLISHERS[platform](**kwargs)
    except KeyError:
        raise PublishError(
            f"plateforme inconnue : {platform!r} (choix : {', '.join(PLATFORMS)})"
        ) from None


def build_context(conn: sqlite3.Connection, draft_id: int, settings: Settings) -> PublishContext:
    row = get_draft(conn, draft_id)
    out_dir = Path(settings.out_dir) / str(draft_id)
    render = None
    if (out_dir / "render.json").exists():
        render = json.loads((out_dir / "render.json").read_text(encoding="utf-8"))
    return PublishContext(
        draft=dict(row),
        payload=draft_payload(row),
        product=get_product(row["product"]),
        settings=settings,
        out_dir=out_dir,
        render=render,
    )


@dataclass
class PublishReport:
    platform: str
    draft_id: int
    dry_run: bool
    request_file: Path
    plan: PublishPlan
    outcome: PublishOutcome | None = None


def already_published(conn: sqlite3.Connection, draft_id: int, platform: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM publications WHERE draft_id = ? AND platform = ? AND dry_run = 0 "
        "ORDER BY id DESC LIMIT 1",
        (draft_id, platform),
    ).fetchone()


def publish_draft(
    conn: sqlite3.Connection,
    draft_id: int,
    platform: str,
    settings: Settings,
    *,
    live: bool = False,
    client: httpx.Client | None = None,
    publisher: Publisher | None = None,
    force: bool = False,
) -> PublishReport:
    """Construit la requête, l'écrit en JSON (toujours), l'envoie si `live`, journalise."""
    if platform not in PUBLISHERS:
        raise PublishError(f"plateforme inconnue : {platform!r} (choix : {', '.join(PLATFORMS)})")
    ctx = build_context(conn, draft_id, settings)
    status, fmt = ctx.draft["status"], ctx.draft["format"]
    if status not in ("approved", "rendered", "published"):
        raise PublishError(
            f"brouillon #{draft_id} en statut « {status} » : approuver puis rendre d'abord"
        )
    if fmt not in PLATFORM_FORMATS.get(platform, ()):
        raise PublishError(
            f"format {fmt} incompatible avec {platform} (formats acceptés : "
            f"{', '.join(PLATFORM_FORMATS.get(platform, ()))})"
        )
    if live and not force and (prev := already_published(conn, draft_id, platform)):
        raise PublishError(
            f"brouillon #{draft_id} déjà publié sur {platform} "
            f"({prev['url'] or prev['remote_id']}) ; "
            "--force pour republier"
        )
    pub = publisher or get_publisher(platform)
    plan = pub.build(ctx)
    path = write_dry_run(plan, ctx.out_dir, live=live)
    outcome = None
    if live:
        try:
            outcome = pub.send(plan, ctx, client or httpx.Client(timeout=180))
        except httpx.HTTPError as e:  # réseau coupé, DNS, délai : erreur métier, pas un crash
            raise PublishError(f"{platform} injoignable ({type(e).__name__}) : {e}") from e
        set_draft_status(conn, draft_id, "published")
    with conn:
        conn.execute(
            "INSERT INTO publications (draft_id, platform, dry_run, request_file, remote_id, url, "
            "response_json, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                draft_id,
                platform,
                0 if live else 1,
                str(path),
                outcome.remote_id if outcome else None,
                outcome.url if outcome else None,
                json.dumps(outcome.response, ensure_ascii=False, default=str) if outcome else None,
                utc_now_iso(),
            ),
        )
    return PublishReport(platform, draft_id, not live, path, plan, outcome)
