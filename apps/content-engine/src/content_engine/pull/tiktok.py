"""TikTok : POST /v2/video/query/ (fields=like_count,comment_count,share_count,view_count).

Réservé aux apps auditées : tant que TIKTOK_APP_AUDITED=false, la source journalise « non
disponible » sans erreur. `publications.remote_id` est le `publish_id` de la Content Posting API ;
l'identifiant public de la vidéo est résolu via post/publish/status/fetch
(`publicaly_available_post_id`, orthographe de l'API) et conservé dans `publications.post_id`."""

from __future__ import annotations

from ..publish.base import require_token
from .base import (
    PublishedItem,
    PullContext,
    PullError,
    Snapshot,
    SourceResult,
    chunks,
    http_error,
    to_int,
)

QUERY_FIELDS = "id,like_count,comment_count,share_count,view_count"
QUERY_BATCH = 20  # video/query : 20 identifiants par appel


class TikTokMetricsSource:
    platform = "tiktok"

    def fetch(self, ctx: PullContext, items: list[PublishedItem]) -> SourceResult:
        s = ctx.settings
        res = SourceResult()
        if not s.tiktok_app_audited:
            res.available = False
            res.notes.append(
                "TikTok : non disponible tant que TIKTOK_APP_AUDITED=false (video/query réservé "
                "aux apps auditées) ; exporter TikTok Studio et `ce metrics --import` en attendant"
            )
            return res
        token = require_token(s.tiktok_access_token, "TIKTOK_ACCESS_TOKEN")
        auth = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        by_post: dict[str, PublishedItem] = {}
        for it in items:
            post_id = it.post_id
            if not post_id:
                r = ctx.client.post(
                    f"{s.tiktok_api_base}/v2/post/publish/status/fetch/",
                    json={"publish_id": it.remote_id},
                    headers=auth,
                )
                if r.status_code >= 400:
                    raise http_error("TikTok (status/fetch)", r)
                data = r.json().get("data") or {}
                ids = data.get("publicaly_available_post_id") or []
                if data.get("status") != "PUBLISH_COMPLETE" or not ids:
                    res.notes.append(
                        f"TikTok : brouillon #{it.draft_id} ({it.remote_id}) pas encore publié "
                        f"(statut {data.get('status') or '?'}) : pas de métriques"
                    )
                    continue
                post_id = str(ids[0])
                res.post_ids[it.publication_id] = post_id
            by_post[post_id] = it
        seen: set[str] = set()
        for batch in chunks(list(by_post), QUERY_BATCH):
            r = ctx.client.post(
                f"{s.tiktok_api_base}/v2/video/query/",
                params={"fields": QUERY_FIELDS},
                json={"filters": {"video_ids": batch}},
                headers=auth,
            )
            if r.status_code >= 400:
                raise http_error("TikTok (video/query)", r)
            body = r.json()
            err = body.get("error") or {}
            if err.get("code") not in (None, "", "ok"):
                raise PullError(f"TikTok : {err.get('code')} — {err.get('message', '')[:200]}")
            for video in (body.get("data") or {}).get("videos") or []:
                post_id = str(video.get("id", ""))
                it = by_post.get(post_id)
                if it is None:
                    continue
                seen.add(post_id)
                res.snapshots.append(
                    Snapshot(
                        item=it,
                        views=to_int(video.get("view_count")),
                        likes=to_int(video.get("like_count")),
                        comments=to_int(video.get("comment_count")),
                        shares=to_int(video.get("share_count")),
                        extra={"post_id": post_id},
                    )
                )
        missing = [p for p in by_post if p not in seen]
        if missing:
            res.notes.append(
                "TikTok : vidéo(s) absente(s) de la réponse (supprimée(s) ?) : "
                + ", ".join(missing)
            )
        return res
