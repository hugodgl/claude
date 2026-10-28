"""YouTube : videos.list (Data API v3, part=statistics,contentDetails) pour les vues, j'aime et
commentaires ; en option reports.query (YouTube Analytics API v2) pour la rétention moyenne, le
temps de visionnage et les partages, si le jeton porte la portée yt-analytics.readonly.
Le jeton OAuth est celui du publisher (data/youtube-token.json, même gestion)."""

from __future__ import annotations

import httpx

from ..publish.youtube import ANALYTICS_SCOPE, READONLY_SCOPE, get_access_token, token_scopes
from .base import (
    PublishedItem,
    PullContext,
    PullError,
    Snapshot,
    SourceResult,
    chunks,
    http_error,
    to_float,
    to_int,
)

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REPORTS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
ANALYTICS_METRICS = "views,estimatedMinutesWatched,averageViewPercentage,shares"
VIDEOS_BATCH = 50  # videos.list : 50 identifiants par appel (1 unité de quota)
REPORTS_BATCH = 200  # reports.query : filtre video== limité à 500 identifiants


class YouTubeMetricsSource:
    platform = "youtube"

    def __init__(self, token: str | None = None, analytics: bool | None = None):
        """`token` et `analytics` injectés dans les tests ; sinon jeton du publisher et portée lue
        dans le fichier de jeton."""
        self._token = token
        self._analytics = analytics

    def fetch(self, ctx: PullContext, items: list[PublishedItem]) -> SourceResult:
        token = self._token or get_access_token(ctx.settings, needed=(READONLY_SCOPE,))
        headers = {"Authorization": f"Bearer {token}"}
        res = SourceResult()
        by_id = {it.remote_id: it for it in items}
        stats: dict[str, dict] = {}
        for batch in chunks(list(by_id), VIDEOS_BATCH):
            r = ctx.client.get(
                VIDEOS_URL,
                params={"part": "statistics,contentDetails", "id": ",".join(batch)},
                headers=headers,
            )
            if r.status_code >= 400:
                raise http_error("YouTube", r)
            for video in r.json().get("items") or []:
                if isinstance(video, dict) and video.get("id"):
                    stats[str(video["id"])] = video
        missing = [vid for vid in by_id if vid not in stats]
        if missing:
            res.notes.append(
                "YouTube : vidéo(s) absente(s) de la réponse (supprimée(s) ?) : "
                + ", ".join(missing)
            )
        analytics = (
            self._analytics
            if self._analytics is not None
            else ANALYTICS_SCOPE in token_scopes(ctx.settings)
        )
        reports: dict[str, dict] = {}
        if not analytics:
            res.notes.append(
                "YouTube Analytics ignoré : portée yt-analytics.readonly absente du jeton "
                "(rétention et partages non relevés ; supprimer data/youtube-token.json et "
                "refaire le consentement avec YOUTUBE_ANALYTICS=true pour l'obtenir)"
            )
        elif stats:
            try:
                reports = self._reports(ctx, headers, list(stats))
            except (PullError, httpx.HTTPError) as e:  # les compteurs videos.list restent valables
                res.notes.append(f"YouTube Analytics ignoré : {e}")
        for vid, video in stats.items():
            if vid not in by_id:  # vidéo non demandée : ignorée
                continue
            st = video.get("statistics") or {}
            rep = reports.get(vid) or {}
            minutes = to_float(rep.get("estimatedMinutesWatched"))
            res.snapshots.append(
                Snapshot(
                    item=by_id[vid],
                    views=to_int(st.get("viewCount")),
                    likes=to_int(st.get("likeCount")),
                    comments=to_int(st.get("commentCount")),
                    shares=to_int(rep.get("shares")),
                    avg_view_pct=to_float(rep.get("averageViewPercentage")),
                    watch_time_h=round(minutes / 60, 3) if minutes is not None else None,
                    extra={
                        "duration": (video.get("contentDetails") or {}).get("duration"),
                        "analytics": bool(rep),
                        "analytics_views": to_int(rep.get("views")) if rep else None,
                        "window": [ctx.start.isoformat(), ctx.end.isoformat()],
                    },
                )
            )
        return res

    def _reports(self, ctx: PullContext, headers: dict, ids: list[str]) -> dict[str, dict]:
        """reports.query par lots : une ligne par vidéo, colonnes nommées par columnHeaders."""
        out: dict[str, dict] = {}
        for batch in chunks(ids, REPORTS_BATCH):
            r = ctx.client.get(
                REPORTS_URL,
                params={
                    "ids": "channel==MINE",
                    "startDate": ctx.start.isoformat(),
                    "endDate": ctx.end.isoformat(),
                    "metrics": ANALYTICS_METRICS,
                    "dimensions": "video",
                    "filters": "video==" + ",".join(batch),
                    "maxResults": REPORTS_BATCH,
                },
                headers=headers,
            )
            if r.status_code >= 400:
                raise http_error("YouTube Analytics", r)
            data = r.json()
            columns = [c.get("name") for c in data.get("columnHeaders") or []]
            for row in data.get("rows") or []:
                record = dict(zip(columns, row, strict=False))
                if record.get("video") is not None:
                    out[str(record["video"])] = record
        return out
