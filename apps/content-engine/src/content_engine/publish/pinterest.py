"""Pinterest API v5 : POST /v5/pins avec l'image de couverture en base64 (pas d'hébergement requis)."""
from __future__ import annotations

import base64

import httpx

from ..texts import compose_pin
from .base import (
    PublishContext,
    PublishOutcome,
    PublishPlan,
    PublishRequest,
    file_ref,
    raise_for_status,
    require_token,
)


class PinterestPublisher:
    platform = "pinterest"

    def body(self, ctx: PublishContext, image_data: str) -> dict:
        s = ctx.settings
        pin = compose_pin(ctx.payload, ctx.product, s)
        return {
            "board_id": s.pinterest_board_id or "<PINTEREST_BOARD_ID>",
            "title": pin["title"],
            "description": pin["description"],
            "link": pin["link"],
            "alt_text": pin["alt_text"],
            "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                             "data": image_data},
        }

    def build(self, ctx: PublishContext) -> PublishPlan:
        cover = ctx.require_file("cover.jpg", "lancer `ce render --draft-id N`")
        size = cover.stat().st_size
        body = self.body(ctx, f"<base64 de cover.jpg, {size} octets>")
        req = PublishRequest(
            step="pins.create",
            method="POST", url=f"{ctx.settings.pinterest_api_base}/v5/pins",
            headers={"Authorization": ctx.bearer(ctx.settings.pinterest_access_token,
                                                 "PINTEREST_ACCESS_TOKEN"),
                     "Content-Type": "application/json"},
            json=body, files=[file_ref("media_source.data", cover, "image/jpeg")],
            notes=["Portée OAuth : pins:write, boards:read",
                   "Image envoyée en base64 dans media_source.data (marqueur ici)",
                   "Anti-spam : au plus 5 épingles par jour, titres et descriptions différents ; "
                   "mention « lien affilié » en tête de description si affiliation"],
        )
        summary = {"title": body["title"], "link": body["link"], "board_id": body["board_id"],
                   "image": str(cover), "bytes": size}
        return PublishPlan(self.platform, int(ctx.draft["id"]), [req], summary)

    def send(self, plan: PublishPlan, ctx: PublishContext, client: httpx.Client) -> PublishOutcome:
        token = require_token(ctx.settings.pinterest_access_token, "PINTEREST_ACCESS_TOKEN")
        require_token(ctx.settings.pinterest_board_id, "PINTEREST_BOARD_ID")
        req = plan.requests[0]
        data = base64.b64encode(open(req.files[0].path, "rb").read()).decode("ascii")
        r = client.post(req.url, json=self.body(ctx, data),
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"})
        raise_for_status(r, "Pinterest")
        pin_id = str(r.json().get("id", ""))
        return PublishOutcome(self.platform, pin_id or None,
                              f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None, r.json())
