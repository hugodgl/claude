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


def join_within(head: list[str], tail: list[str], limit: int, sep: str = "\n\n") -> str:
    """Assemble `head + tail` sous `limit` caractères en sacrifiant la tête, jamais la queue :
    l'étiquette IA, le lien et les hashtags restent présents même si le texte du LLM est long."""
    head_text = sep.join(b.strip() for b in head if b and b.strip())
    tail_text = sep.join(b.strip() for b in tail if b and b.strip())
    if not tail_text:
        return truncate(head_text, limit)
    if len(tail_text) > limit:
        return truncate(tail_text, limit)
    budget = limit - len(tail_text) - (len(sep) if head_text else 0)
    if head_text and len(head_text) > budget:
        head_text = truncate(head_text, budget) if budget > 1 else ""
    return sep.join(b for b in (head_text, tail_text) if b)


_YOUTUBE_FORBIDDEN = str.maketrans({"<": "‹", ">": "›"})


def youtube_safe(text: str) -> str:
    """YouTube refuse « < » et « > » dans les titres et descriptions (invalidTitle/Description)."""
    return text.translate(_YOUTUBE_FORBIDDEN)


def hashtags_line(payload: dict, product: Product, limit: int = 6) -> str:
    tags: list[str] = []
    for tag in list(payload.get("hashtags", [])) + list(product.hashtags):
        if tag not in tags:
            tags.append(tag)
    return " ".join("#" + t for t in tags[:limit])


def disclosure_line(settings: Settings) -> str:
    return settings.ai_disclosure.strip()


def youtube_title(payload: dict) -> str:
    return truncate(youtube_safe(payload["title"]), LIMITS["youtube_title"])


def compose_description(payload: dict, product: Product, settings: Settings) -> str:
    """Description YouTube : description du script (sources), CTA + lien, label IA, hashtags."""
    head = [youtube_safe(payload.get("description", ""))]
    tail = [
        youtube_safe(
            f"{payload['cta']}\n{ucfirst(product.cta_hint)} : {settings.landing_url(product.slug)}"
        ),
        disclosure_line(settings),
        hashtags_line(payload, product),
    ]
    return join_within(head, tail, LIMITS["youtube_description"])


def compose_tiktok_caption(payload: dict, product: Product, settings: Settings) -> str:
    cta = payload["cta"] if "bio" in payload["cta"].lower() else f"{payload['cta']} (lien en bio)"
    tail = [cta, disclosure_line(settings), hashtags_line(payload, product, limit=5)]
    return join_within([payload["hook"]], tail, LIMITS["tiktok_title"], sep="\n")


def compose_pin(payload: dict, product: Product, settings: Settings) -> dict:
    tail = [disclosure_line(settings), hashtags_line(payload, product, limit=5)]
    description = join_within(
        [payload.get("description", "")], tail, LIMITS["pinterest_description"]
    )
    return {
        "title": truncate(payload["title"], LIMITS["pinterest_title"]),
        "description": description,
        "alt_text": truncate(payload["hook"], 500),
        "link": settings.landing_url(product.slug),
    }


def compose_linkedin_post(payload: dict, product: Product, settings: Settings) -> str:
    head = [payload["hook"], *payload["body"], payload["cta"]]
    tail = [
        f"{ucfirst(product.cta_hint)} : {settings.landing_url(product.slug)}",
        disclosure_line(settings),
        hashtags_line(payload, product, limit=4),
    ]
    return join_within(head, tail, LIMITS["linkedin_commentary"])


def teleprompter_text(payload: dict) -> str:
    lines = [payload["title"].upper(), "", payload["hook"], ""]
    lines += [part + "\n" for part in payload["body"]]
    lines += [payload["cta"], "", "— description —", payload.get("description", "")]
    return "\n".join(lines)
