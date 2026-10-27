"""Textes finaux par plateforme : descriptions, légendes, post LinkedIn, étiquetage IA."""
from __future__ import annotations

from .products import Product
from .settings import Settings

LIMITS = {
    "youtube_title": 100,
    "youtube_description": 5000,
    "tiktok_title": 2200,
    "pinterest_title": 100,
    "pinterest_description": 800,
    "linkedin_commentary": 3000,
}


def ucfirst(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def hashtags_line(payload: dict, product: Product, limit: int = 6) -> str:
    tags: list[str] = []
    for tag in list(payload.get("hashtags", [])) + list(product.hashtags):
        if tag not in tags:
            tags.append(tag)
    return " ".join("#" + t for t in tags[:limit])


def disclosure_line(settings: Settings) -> str:
    return settings.ai_disclosure.strip()


def youtube_title(payload: dict) -> str:
    return truncate(payload["title"], LIMITS["youtube_title"])


def compose_description(payload: dict, product: Product, settings: Settings) -> str:
    """Description YouTube : description du script (sources incluses), CTA + lien, label IA, hashtags."""
    blocks = [
        payload.get("description", "").strip(),
        f"{payload['cta']}\n{ucfirst(product.cta_hint)} : {settings.landing_url(product.slug)}",
        disclosure_line(settings),
        hashtags_line(payload, product),
    ]
    return truncate("\n\n".join(b for b in blocks if b), LIMITS["youtube_description"])


def compose_tiktok_caption(payload: dict, product: Product, settings: Settings) -> str:
    cta = payload["cta"] if "bio" in payload["cta"].lower() else f"{payload['cta']} (lien en bio)"
    blocks = [payload["hook"], cta, disclosure_line(settings), hashtags_line(payload, product, limit=5)]
    return truncate("\n".join(b for b in blocks if b), LIMITS["tiktok_title"])


def compose_pin(payload: dict, product: Product, settings: Settings) -> dict:
    description = "\n\n".join(
        b for b in [payload.get("description", "").strip(), disclosure_line(settings),
                    hashtags_line(payload, product, limit=5)] if b
    )
    return {
        "title": truncate(payload["title"], LIMITS["pinterest_title"]),
        "description": truncate(description, LIMITS["pinterest_description"]),
        "alt_text": truncate(payload["hook"], 500),
        "link": settings.landing_url(product.slug),
    }


def compose_linkedin_post(payload: dict, product: Product, settings: Settings) -> str:
    blocks = [payload["hook"], *payload["body"], payload["cta"],
              f"{ucfirst(product.cta_hint)} : {settings.landing_url(product.slug)}",
              disclosure_line(settings), hashtags_line(payload, product, limit=4)]
    return truncate("\n\n".join(b for b in blocks if b), LIMITS["linkedin_commentary"])


def teleprompter_text(payload: dict) -> str:
    lines = [payload["title"].upper(), "", payload["hook"], ""]
    lines += [part + "\n" for part in payload["body"]]
    lines += [payload["cta"], "", "— description —", payload.get("description", "")]
    return "\n".join(lines)
