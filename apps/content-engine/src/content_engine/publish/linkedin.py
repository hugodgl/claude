"""LinkedIn Posts API : POST /rest/posts (texte « little text format », en-tête LinkedIn-Version)."""
from __future__ import annotations

import re

import httpx

from ..texts import compose_linkedin_post, hashtags_line
from .base import (
    PublishContext,
    PublishOutcome,
    PublishPlan,
    PublishRequest,
    raise_for_status,
    require_token,
)

_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape_little_text(text: str) -> str:
    """Échappe les caractères réservés du format texte de LinkedIn."""
    return _RESERVED.sub(r"\\\1", text)


def linkedin_hashtags(payload: dict, product) -> str:
    tags = hashtags_line(payload, product, limit=4).replace("#", "").split()
    return " ".join("{hashtag|\\#|" + t + "}" for t in tags)


class LinkedInPublisher:
    platform = "linkedin"

    def body(self, ctx: PublishContext) -> dict:
        s = ctx.settings
        text = compose_linkedin_post(ctx.payload, ctx.product, s)
        # les hashtags composés en clair sont remplacés par la syntaxe cliquable de LinkedIn
        plain_tags = hashtags_line(ctx.payload, ctx.product, limit=4)
        text = text.replace(plain_tags, "").rstrip()
        commentary = escape_little_text(text) + "\n\n" + linkedin_hashtags(ctx.payload, ctx.product)
        return {
            "author": s.linkedin_author_urn or "<LINKEDIN_AUTHOR_URN>",
            "commentary": commentary.strip(),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

    def build(self, ctx: PublishContext) -> PublishPlan:
        s = ctx.settings
        body = self.body(ctx)
        req = PublishRequest(
            step="posts.create",
            method="POST", url=f"{s.linkedin_api_base}/rest/posts",
            headers={"Authorization": ctx.bearer(s.linkedin_access_token, "LINKEDIN_ACCESS_TOKEN"),
                     "LinkedIn-Version": s.linkedin_version,
                     "X-Restli-Protocol-Version": "2.0.0",
                     "Content-Type": "application/json"},
            json=body,
            notes=["Portée OAuth : w_member_social (profil) ou w_organization_social (page)",
                   "L'identifiant du post est renvoyé dans l'en-tête x-restli-id",
                   "LinkedIn-Version (AAAAMM) expire : la mettre à jour dans .env tous les ~6 mois"],
        )
        summary = {"author": body["author"], "characters": len(body["commentary"]),
                   "version": s.linkedin_version}
        return PublishPlan(self.platform, int(ctx.draft["id"]), [req], summary)

    def send(self, plan: PublishPlan, ctx: PublishContext, client: httpx.Client) -> PublishOutcome:
        token = require_token(ctx.settings.linkedin_access_token, "LINKEDIN_ACCESS_TOKEN")
        require_token(ctx.settings.linkedin_author_urn, "LINKEDIN_AUTHOR_URN")
        req = plan.requests[0]
        r = client.post(req.url, json=req.json,
                        headers={**req.headers, "Authorization": f"Bearer {token}"})
        raise_for_status(r, "LinkedIn")
        urn = r.headers.get("x-restli-id")
        return PublishOutcome(self.platform, urn,
                              f"https://www.linkedin.com/feed/update/{urn}/" if urn else None,
                              {"status_code": r.status_code})
