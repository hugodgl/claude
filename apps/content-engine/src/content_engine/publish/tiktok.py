"""TikTok Content Posting API (publication directe) : stub documenté.

L'app TikTok doit passer l'audit « Content Posting » avant toute publication publique ; sans audit,
`privacy_level` est limité à SELF_ONLY (vidéo visible par le compte seul). L'appel
`post/publish/video/init/` est implémenté (dry-run par défaut), puis l'envoi du fichier en un seul
morceau et une vérification de statut.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..texts import compose_tiktok_caption
from .base import (
    PublishContext,
    PublishError,
    PublishOutcome,
    PublishPlan,
    PublishRequest,
    file_ref,
    raise_for_status,
    require_token,
)

MAX_SINGLE_CHUNK = 64 * 1024 * 1024


class TikTokPublisher:
    platform = "tiktok"

    def body(self, ctx: PublishContext, size: int) -> dict:
        return {
            "post_info": {
                "title": compose_tiktok_caption(ctx.payload, ctx.product, ctx.settings),
                "privacy_level": ctx.settings.tiktok_privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
                "is_aigc": ctx.synthetic,
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
        }

    def build(self, ctx: PublishContext) -> PublishPlan:
        video_name = (ctx.render or {}).get("video") or "video.mp4"
        video = ctx.require_file(video_name, "lancer `ce render --draft-id N`")
        size = video.stat().st_size
        if size > MAX_SINGLE_CHUNK:
            raise PublishError("TikTok : vidéo > 64 Mo, envoi en plusieurs morceaux non implémenté")
        s = ctx.settings
        auth = ctx.bearer(s.tiktok_access_token, "TIKTOK_ACCESS_TOKEN")
        body = self.body(ctx, size)
        requests = [
            PublishRequest(
                step="post/publish/video/init",
                method="POST",
                url=f"{s.tiktok_api_base}/v2/post/publish/video/init/",
                headers={"Authorization": auth, "Content-Type": "application/json; charset=UTF-8"},
                json=body,
                notes=[
                    "STUB : l'app doit passer l'audit Content Posting ; sans audit, "
                    "privacy_level=SELF_ONLY uniquement",
                    "post_info.is_aigc = vrai : label « contenu généré par IA » (obligatoire, "
                    "sous peine de strike)",
                    "Creator Rewards : contenu 100 % original de plus d'une minute ; un compte "
                    "entièrement synthétique est exclu",
                    "Portée OAuth : video.publish",
                ],
            ),
            PublishRequest(
                step="envoi du fichier (un seul morceau)",
                method="PUT",
                url="<upload_url renvoyé par l'étape précédente>",
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size),
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                },
                files=[file_ref("body", video, "video/mp4")],
            ),
            PublishRequest(
                step="post/publish/status/fetch",
                method="POST",
                url=f"{s.tiktok_api_base}/v2/post/publish/status/fetch/",
                headers={"Authorization": auth, "Content-Type": "application/json; charset=UTF-8"},
                json={"publish_id": "<publish_id renvoyé par l'étape init>"},
            ),
        ]
        summary = {
            "title": body["post_info"]["title"][:120],
            "privacy_level": s.tiktok_privacy_level,
            "is_aigc": body["post_info"]["is_aigc"],
            "video": str(video),
            "bytes": size,
            "audit_required": True,
        }
        return PublishPlan(self.platform, int(ctx.draft["id"]), requests, summary)

    def send(self, plan: PublishPlan, ctx: PublishContext, client: httpx.Client) -> PublishOutcome:
        token = require_token(ctx.settings.tiktok_access_token, "TIKTOK_ACCESS_TOKEN")
        auth = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        init, upload, status = plan.requests
        r = client.post(init.url, json=init.json, headers=auth)
        raise_for_status(r, "TikTok (init)")
        data = r.json().get("data") or {}
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if not publish_id or not upload_url:
            raise PublishError(f"TikTok : réponse init incomplète : {r.text[:300]}")
        content = Path(upload.files[0].path).read_bytes()
        r2 = client.put(
            upload_url,
            content=content,
            headers={k: v for k, v in upload.headers.items() if k != "Content-Length"},
        )
        raise_for_status(r2, "TikTok (upload)")
        r3 = client.post(status.url, json={"publish_id": publish_id}, headers=auth)
        state = (r3.json().get("data") or {}).get("status") if r3.status_code < 400 else None
        return PublishOutcome(
            self.platform, publish_id, None, {"publish_id": publish_id, "status": state}
        )
