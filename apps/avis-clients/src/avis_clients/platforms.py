"""Plateformes d'avis : constantes, avis distant commun, erreurs, protocole des adaptateurs et fabrique.

Trois plateformes : Google (fiche Business Profile, jeton opérateur unique), Facebook (Page, jeton de Page
chiffré par source) et Tripadvisor (fiche, clé Content API globale, lecture seule : pas de réponse par API).
Chaque établissement relie au plus une source par plateforme (table `review_sources`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - uniquement pour les annotations
    from .models import ReviewSource
    from .settings import AppSettings

PLATFORMS: tuple[str, ...] = ("google", "facebook", "tripadvisor")
PLATFORM_LABELS: dict[str, str] = {"google": "Google", "facebook": "Facebook", "tripadvisor": "Tripadvisor"}
# Plateformes où la réponse part par API ; Tripadvisor n'a pas d'API publique de réponse (flux « à copier »).
PLATFORMS_WITH_REPLY_API: frozenset[str] = frozenset({"google", "facebook"})


def platform_label(platform: str | None) -> str:
    return PLATFORM_LABELS.get(platform or "", platform or "?")


class PlatformError(RuntimeError):
    """Erreur d'un adaptateur (réseau, HTTP, jeton) : la source est notée en erreur, le poll continue."""


class PlatformAuthError(PlatformError):
    """Jeton ou clé refusés (expiré, révoqué, permissions manquantes) : à renouveler par le commerçant."""


@dataclass
class RemoteReview:
    """Avis tel que lu sur une plateforme, avant insertion en base.

    `name` est l'identifiant de ressource qui sert à répondre : Google `accounts/…/reviews/…`, Facebook
    l'identifiant de l'open graph story (cible du commentaire), Tripadvisor l'URL publique de l'avis."""

    name: str
    review_id: str
    author: str
    rating: int
    text: str
    create_time: str
    update_time: str | None = None
    reply_text: str | None = None
    reply_time: str | None = None
    rating_note: str | None = None  # ex. « recommandation Facebook sans note, comptée 5 étoiles »


class PlatformClient(Protocol):
    """Adaptateur d'une plateforme. `credentials` : jeton déchiffré de la source (Facebook), None sinon."""

    platform: str
    name: str  # "mock" | "live"
    can_reply: bool

    def fetch_reviews(self, source: ReviewSource, credentials: str | None) -> list[RemoteReview]: ...

    def publish_reply(self, source: ReviewSource, credentials: str | None, review_name: str,
                      text: str) -> dict[str, Any]: ...

    def verify_source(self, external_id: str, credentials: str | None) -> dict[str, Any]: ...


def build_platform_clients(settings: AppSettings, gbp: Any | None = None) -> dict[str, PlatformClient]:
    """Fabrique : un adaptateur par plateforme selon les réglages (`GBP_MODE`, `FACEBOOK_MODE`,
    `TRIPADVISOR_MODE`). `gbp` permet de réutiliser un client Google déjà construit (tests, services)."""
    from .facebook import build_facebook_client
    from .gbp import GoogleAdapter, build_gbp_client
    from .tripadvisor import build_tripadvisor_client

    return {
        "google": GoogleAdapter(gbp or build_gbp_client(settings)),
        "facebook": build_facebook_client(settings),
        "tripadvisor": build_tripadvisor_client(settings),
    }
