"""Relevé automatique des métriques (`ce metrics --pull`) : pour chaque publication réelle, la
source de la plateforme interroge son API et les compteurs sont historisés dans `metrics`
(un relevé daté par contenu et par jour ; relancer le même jour met à jour le relevé du jour)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from ..publish.base import PublishError
from ..settings import Settings
from .base import (
    MetricsSource,
    PublishedItem,
    PullContext,
    PullError,
    Snapshot,
    SourceResult,
)
from .linkedin import LinkedInMetricsSource
from .pinterest import PinterestMetricsSource
from .tiktok import TikTokMetricsSource
from .youtube import YouTubeMetricsSource

__all__ = [
    "PLATFORMS",
    "MetricsSource",
    "PlatformReport",
    "PublishedItem",
    "PullContext",
    "PullError",
    "PullReport",
    "Snapshot",
    "SourceResult",
    "last_measurement",
    "published_items",
    "pull_metrics",
    "store_snapshot",
]

SOURCES: dict[str, type] = {
    "youtube": YouTubeMetricsSource,
    "pinterest": PinterestMetricsSource,
    "tiktok": TikTokMetricsSource,
    "linkedin": LinkedInMetricsSource,
}
PLATFORMS = tuple(SOURCES)
DEFAULT_DAYS = 90
# Erreurs confinées à une plateforme : HTTP, jeton absent, réponse inattendue (JSON, champs).
SOURCE_ERRORS = (PullError, PublishError, httpx.HTTPError, ValueError, KeyError, TypeError)


@dataclass
class PlatformReport:
    platform: str
    publications: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)
    stored: int = 0
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    available: bool = True


@dataclass
class PullReport:
    dry_run: bool
    measured_at: str
    platforms: dict[str, PlatformReport] = field(default_factory=dict)

    @property
    def attempted(self) -> list[str]:
        """Plateformes avec des publications à relever et une API disponible."""
        return [p for p, r in self.platforms.items() if r.publications and r.available]

    @property
    def failed(self) -> list[str]:
        return [p for p, r in self.platforms.items() if r.error]

    @property
    def succeeded(self) -> list[str]:
        return [p for p in self.attempted if not self.platforms[p].error]


def published_items(conn: sqlite3.Connection, platform: str, since: str) -> list[PublishedItem]:
    """Publications réelles (envoi `--live`, identifiant distant connu) de brouillons publiés,
    datées d'après `since` (ISO UTC)."""
    rows = conn.execute(
        "SELECT p.id AS publication_id, p.draft_id, p.platform, p.remote_id, p.post_id, "
        "p.published_at, d.payload_json, t.product "
        "FROM publications p JOIN drafts d ON d.id = p.draft_id JOIN topics t ON t.id = d.topic_id "
        "WHERE p.dry_run = 0 AND p.remote_id IS NOT NULL AND p.remote_id != '' "
        "AND d.status = 'published' AND p.platform = ? AND p.published_at >= ? ORDER BY p.id",
        (platform, since),
    ).fetchall()
    items = []
    for r in rows:
        try:
            title = str(json.loads(r["payload_json"]).get("title", ""))
        except (ValueError, AttributeError):
            title = ""
        items.append(
            PublishedItem(
                publication_id=int(r["publication_id"]),
                draft_id=int(r["draft_id"]),
                platform=r["platform"],
                remote_id=str(r["remote_id"]),
                post_id=r["post_id"],
                published_at=r["published_at"],
                title=title[:200],
                product=r["product"],
            )
        )
    return items


def store_snapshot(conn: sqlite3.Connection, snap: Snapshot, measured_at: str) -> None:
    """Historise un relevé : un par contenu, par source API et par jour (le relevé du jour est
    remplacé, les jours précédents sont conservés)."""
    it = snap.item
    with conn:
        conn.execute(
            "DELETE FROM metrics WHERE platform = ? AND remote_id = ? AND source = 'api' "
            "AND substr(measured_at, 1, 10) = ?",
            (it.platform, it.remote_id, measured_at[:10]),
        )
        conn.execute(
            "INSERT INTO metrics (platform, remote_id, title, draft_id, views, likes, comments, "
            "shares, impressions, ctr, avg_view_pct, watch_time_h, published_at, imported_at, "
            "source_file, measured_at, source, clicks, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'api', ?, ?)",
            (
                it.platform,
                it.remote_id,
                it.title or None,
                it.draft_id,
                snap.views,
                snap.likes,
                snap.comments,
                snap.shares,
                snap.impressions,
                snap.ctr,
                snap.avg_view_pct,
                snap.watch_time_h,
                it.published_at,
                measured_at,
                measured_at,
                snap.clicks,
                json.dumps(snap.extra, ensure_ascii=False, default=str) if snap.extra else None,
            ),
        )


def pull_metrics(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    platforms: list[str] | None = None,
    days: int = DEFAULT_DAYS,
    dry_run: bool = False,
    client: httpx.Client | None = None,
    sources: dict[str, MetricsSource] | None = None,
    now: datetime | None = None,
) -> PullReport:
    """Relève les publications réelles des `days` derniers jours, plateforme par plateforme ; une
    plateforme en erreur n'empêche pas les autres. `dry_run` : rien n'est écrit."""
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    wanted = list(platforms or PLATFORMS)
    unknown = [p for p in wanted if p not in SOURCES]
    if unknown:
        raise ValueError(
            f"plateforme inconnue : {', '.join(unknown)} (choix : {', '.join(PLATFORMS)}, all)"
        )
    if days < 1:
        raise ValueError("--days doit valoir au moins 1")
    since = now - timedelta(days=days)
    ctx = PullContext(
        settings=settings,
        client=client or httpx.Client(timeout=60),
        now=now,
        start=since.date(),
        end=now.date(),
        days=days,
    )
    measured_at = now.replace(microsecond=0).isoformat()
    report = PullReport(dry_run=dry_run, measured_at=measured_at)
    for platform in wanted:
        items = published_items(conn, platform, since.isoformat())
        pr = PlatformReport(platform, publications=len(items))
        report.platforms[platform] = pr
        if not items:
            pr.notes.append(f"aucune publication réelle des {days} derniers jours à relever")
            continue
        source = (sources or {}).get(platform) or SOURCES[platform]()
        try:
            res = source.fetch(ctx, items)
        except SOURCE_ERRORS as e:
            kind = "" if isinstance(e, (PullError, PublishError)) else f"{type(e).__name__} : "
            pr.error = f"{kind}{e}"[:500]
            continue
        pr.snapshots, pr.notes, pr.available, pr.error = (
            res.snapshots,
            pr.notes + res.notes,
            res.available,
            res.error,
        )
        if dry_run:
            continue
        for snap in res.snapshots:
            store_snapshot(conn, snap, measured_at)
            pr.stored += 1
        if res.post_ids:
            with conn:
                for publication_id, post_id in res.post_ids.items():
                    conn.execute(
                        "UPDATE publications SET post_id = ? WHERE id = ?",
                        (post_id, publication_id),
                    )
    return report


def last_measurement(conn: sqlite3.Connection) -> str | None:
    """Date du dernier relevé API (pour `ce doctor`)."""
    row = conn.execute("SELECT MAX(measured_at) FROM metrics WHERE source = 'api'").fetchone()
    return row[0] if row and row[0] else None
