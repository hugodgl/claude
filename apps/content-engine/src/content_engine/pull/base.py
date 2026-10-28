"""Contrat des sources de métriques : une source reçoit les publications réelles d'une plateforme
et renvoie des relevés datés. Ses erreurs (réseau, quota, jeton) restent confinées à la plateforme :
l'orchestrateur (`pull_metrics`) continue avec les autres."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import httpx

from ..settings import Settings


class PullError(RuntimeError):
    """Relevé impossible pour une plateforme : HTTP ≥ 400, quota, réponse inattendue."""


@dataclass
class PullContext:
    settings: Settings
    client: httpx.Client
    now: datetime  # UTC
    start: date  # fenêtre d'analyse (Pinterest, YouTube Analytics)
    end: date
    days: int


@dataclass
class PublishedItem:
    """Une publication réelle (table `publications`, dry_run = 0, identifiant distant connu)."""

    publication_id: int
    draft_id: int
    platform: str
    remote_id: str
    post_id: str | None
    published_at: str
    title: str
    product: str


@dataclass
class Snapshot:
    """Un relevé : les compteurs d'un contenu à l'instant du relevé."""

    item: PublishedItem
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    impressions: int | None = None
    clicks: int | None = None
    ctr: float | None = None
    avg_view_pct: float | None = None  # rétention (YouTube Analytics)
    watch_time_h: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceResult:
    snapshots: list[Snapshot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    available: bool = True  # False : stub ou API non disponible (journalisé, pas une erreur)
    post_ids: dict[int, str] = field(default_factory=dict)  # publication_id → identifiant public


class MetricsSource(Protocol):
    platform: str

    def fetch(self, ctx: PullContext, items: list[PublishedItem]) -> SourceResult: ...


def chunks(seq: Iterable, size: int) -> Iterator[list]:
    batch: list = []
    for item in seq:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def to_int(value: Any) -> int:
    """Compteur renvoyé en chaîne (YouTube), en flottant (Pinterest) ou absent → entier."""
    if value is None or value == "":
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def http_error(platform: str, r: httpx.Response) -> PullError:
    text = r.text[:300]
    quota = r.status_code == 429 or "quota" in text.lower() or "rate limit" in text.lower()
    hint = " (quota ou limite de débit : réessayer demain)" if quota else ""
    return PullError(f"{platform} : HTTP {r.status_code}{hint} — {text}")
