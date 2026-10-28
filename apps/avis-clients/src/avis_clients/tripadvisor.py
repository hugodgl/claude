"""Avis Tripadvisor (Content API) : lecture des 5 avis les plus récents d'une fiche, mock et client réel.

Limite structurelle : **Tripadvisor n'offre pas d'API publique pour répondre aux avis**. La réponse est
rédigée ici (brouillon LLM, mêmes garde-fous), puis copiée et publiée par le commerçant depuis sa page
propriétaire Tripadvisor ; l'avis passe en `published_manually` quand il le confirme.
API réelle : GET https://api.content.tripadvisor.com/api/v1/location/{locationId}/reviews?key=…&language=fr
(5 avis les plus récents, quota mensuel de la clé gratuite) et …/location/{locationId}/details (nom,
`web_url`, `write_review`) pour vérifier la fiche au moment de la liaison.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .db import now_iso
from .models import ReviewSource
from .platforms import PlatformAuthError, PlatformError, RemoteReview
from .settings import AppSettings

log = logging.getLogger(__name__)

CONTENT_API = "https://api.content.tripadvisor.com/api/v1"
OWNERS_URL = "https://www.tripadvisor.fr/Owners"  # espace propriétaire (Centre de gestion → Avis)
PACKAGE_FIXTURE = Path(__file__).parent / "fixtures" / "tripadvisor_reviews.json"
LOCATION_ID_RE = re.compile(r"^\d{1,12}$")
# sous-domaines facultatifs + tripadvisor.<tld> (fr, com, co.uk, com.au…) et rien après
TRIPADVISOR_HOST_RE = re.compile(r"(?:[a-z0-9-]+\.)*tripadvisor\.(?:[a-z]{2,3}|co\.[a-z]{2}|com\.[a-z]{2})")
NO_REPLY_API_MESSAGE = ("Tripadvisor ne propose pas d'API de réponse : copiez la réponse et publiez-la depuis "
                        "votre espace propriétaire Tripadvisor, puis confirmez ici.")


class TripadvisorError(PlatformError):
    pass


class TripadvisorAuthError(PlatformAuthError, TripadvisorError):
    pass


def safe_tripadvisor_url(url: str | None) -> str | None:
    """N'accepte qu'une URL https du domaine tripadvisor.* (l'URL vient de l'API ou des fixtures)."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not TRIPADVISOR_HOST_RE.fullmatch(host):
        return None
    return url


def management_url(review_url: str | None) -> str:
    """Lien « ouvrir Tripadvisor » du flux à copier : la page de l'avis (bouton « Répondre » visible pour le
    propriétaire connecté), sinon l'espace propriétaire."""
    return safe_tripadvisor_url(review_url) or OWNERS_URL


@dataclass
class TripadvisorReview(RemoteReview):
    """Avis Tripadvisor ; `name` = URL publique de l'avis (il n'y a pas de ressource de réponse)."""

    @classmethod
    def from_api(cls, data: dict[str, Any], location_id: str) -> TripadvisorReview:
        review_id = str(data.get("id") or "")
        user = data.get("user") or {}
        title = (data.get("title") or "").strip()
        body = (data.get("text") or "").strip()
        text = f"{title}\n{body}".strip() if title and body else (title or body)
        owner = data.get("owner_response") or {}
        try:
            rating = int(data.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0
        return cls(
            name=safe_tripadvisor_url(data.get("url")) or "",
            review_id=review_id or f"{location_id}:{data.get('published_date')}",
            author=user.get("username") or "Anonyme",
            rating=rating,
            text=text,
            create_time=data.get("published_date") or now_iso(),
            update_time=None,
            reply_text=(owner.get("text") or None) if isinstance(owner, dict) else None,
            reply_time=(owner.get("published_date") or None) if isinstance(owner, dict) else None,
        )


def _check_location_id(location_id: str) -> str:
    location_id = (location_id or "").strip()
    if not LOCATION_ID_RE.match(location_id):
        raise TripadvisorError("identifiant de fiche Tripadvisor invalide (attendu : identifiant numérique)")
    return location_id


def _location_info(location_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": location_id,
        "name": data.get("name"),
        "public_url": safe_tripadvisor_url(data.get("write_review")) or safe_tripadvisor_url(data.get("web_url")),
    }


class MockTripadvisorClient:
    platform = "tripadvisor"
    name = "mock"
    can_reply = False

    def __init__(self, fixtures_path: Path | None = None, data: dict[str, Any] | None = None):
        if data is None:
            data = json.loads(Path(fixtures_path or PACKAGE_FIXTURE).read_text(encoding="utf-8"))
        self.data = data

    def list_location_reviews(self, location_id: str) -> list[TripadvisorReview]:
        location_id = _check_location_id(location_id)
        per_location = self.data.get("locations_reviews") or {}
        raws = per_location.get(location_id, self.data.get("reviews", []))
        return [TripadvisorReview.from_api(raw, location_id) for raw in raws[:5]]  # l'API réelle en renvoie 5

    def get_location(self, location_id: str) -> dict[str, Any]:
        location_id = _check_location_id(location_id)
        for loc in self.data.get("locations", []):
            if str(loc.get("location_id")) == location_id:
                return _location_info(location_id, loc)
        return {"id": location_id, "name": f"Fiche Tripadvisor {location_id} (démo)", "public_url": None}

    # --- protocole PlatformClient ---
    def fetch_reviews(self, source: ReviewSource, credentials: str | None) -> list[RemoteReview]:
        return list(self.list_location_reviews(source.external_id))

    def publish_reply(self, source: ReviewSource, credentials: str | None, review_name: str,
                      text: str) -> dict[str, Any]:
        raise TripadvisorError(NO_REPLY_API_MESSAGE)

    def verify_source(self, external_id: str, credentials: str | None) -> dict[str, Any]:
        return self.get_location(external_id)


class LiveTripadvisorClient:
    """Content API avec la clé globale de l'application (paramètre `key`, comme l'exige l'API). La clé doit
    être autorisée pour l'adresse IP sortante du serveur dans le portail développeur Tripadvisor."""

    platform = "tripadvisor"
    name = "live"
    can_reply = False
    REQUEST_TIMEOUT_S = 30

    def __init__(self, api_key: str, language: str = "fr", transport: httpx.BaseTransport | None = None,
                 timeout_s: float = REQUEST_TIMEOUT_S):
        self.api_key = api_key
        self.language = language
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def _get(self, path: str, what: str) -> dict[str, Any]:
        try:
            r = self._client.get(f"{CONTENT_API}{path}", params={"key": self.api_key, "language": self.language},
                                 headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise TripadvisorError(f"Tripadvisor {what} injoignable : {e.__class__.__name__}") from e
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        if r.status_code in (401, 403):
            raise TripadvisorAuthError(f"Tripadvisor {what} : clé Content API refusée (HTTP {r.status_code}) ; "
                                       "vérifiez TRIPADVISOR_API_KEY et l'adresse IP autorisée dans le portail")
        if r.status_code == 429:
            raise TripadvisorError(f"Tripadvisor {what} : quota de la clé dépassé (HTTP 429), réessai au "
                                   "prochain intervalle")
        if r.status_code >= 400:
            message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
            raise TripadvisorError(f"Tripadvisor {what} : HTTP {r.status_code} {message or r.text[:200]}")
        return body if isinstance(body, dict) else {}

    def list_location_reviews(self, location_id: str) -> list[TripadvisorReview]:
        location_id = _check_location_id(location_id)
        data = self._get(f"/location/{location_id}/reviews", "liste des avis")
        return [TripadvisorReview.from_api(raw, location_id) for raw in data.get("data", []) if isinstance(raw, dict)]

    def get_location(self, location_id: str) -> dict[str, Any]:
        location_id = _check_location_id(location_id)
        return _location_info(location_id, self._get(f"/location/{location_id}/details", "détails de la fiche"))

    # --- protocole PlatformClient ---
    def fetch_reviews(self, source: ReviewSource, credentials: str | None) -> list[RemoteReview]:
        return list(self.list_location_reviews(source.external_id))

    def publish_reply(self, source: ReviewSource, credentials: str | None, review_name: str,
                      text: str) -> dict[str, Any]:
        raise TripadvisorError(NO_REPLY_API_MESSAGE)

    def verify_source(self, external_id: str, credentials: str | None) -> dict[str, Any]:
        return self.get_location(external_id)


def build_tripadvisor_client(settings: AppSettings):
    if settings.tripadvisor_mode == "live":
        return LiveTripadvisorClient(settings.tripadvisor_api_key or "")
    return MockTripadvisorClient(settings.tripadvisor_fixtures_file)
