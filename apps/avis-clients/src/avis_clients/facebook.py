"""Avis et recommandations d'une Page Facebook (Graph API) : mock sur fixtures et client réel.

API réelle (jeton de Page, permissions `pages_read_user_content` et `pages_manage_engagement`) :
- lecture : GET /{page-id}/ratings?fields=reviewer{name,id},rating,recommendation_type,review_text,
  created_time,open_graph_story{id},has_rating,has_review  (paginé par `paging.next`)
- réponse : POST /{open_graph_story_id}/comments  {"message": …}  (la réponse est un commentaire public)
- vérification de la liaison : GET /me?fields=id,name avec le jeton de Page ; l'identifiant renvoyé doit être
  celui saisi (un jeton de Page ne prouve la possession que de sa propre Page).
Depuis 2018, Facebook ne demande plus de note : une « recommandation » est `positive` ou `negative`.
Elle est convertie en 5 ou 1 étoile(s), avec une mention affichée dans la boîte de réception.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .db import now_iso
from .models import ReviewSource
from .platforms import PlatformAuthError, PlatformError, RemoteReview
from .settings import AppSettings

log = logging.getLogger(__name__)

GRAPH_HOST = "https://graph.facebook.com"
RATINGS_FIELDS = ("reviewer{name,id},rating,recommendation_type,review_text,created_time,open_graph_story{id},"
                  "has_rating,has_review")
PACKAGE_FIXTURE = Path(__file__).parent / "fixtures" / "facebook_ratings.json"
PAGE_ID_RE = re.compile(r"^\d{5,20}$")
STORY_ID_RE = re.compile(r"^[0-9_]{1,80}$")
RECOMMENDATION_RATING = {"positive": 5, "negative": 1}
# Codes d'erreur Graph API qui signifient « jeton à renouveler » (expiré, révoqué, mot de passe changé…)
AUTH_ERROR_CODES = {190, 102, 104, 463, 467}
MAX_PAGES = 50


class FacebookError(PlatformError):
    pass


class FacebookAuthError(PlatformAuthError, FacebookError):
    pass


def page_reviews_url(page_id: str) -> str:
    return f"https://www.facebook.com/{page_id}/reviews/"


@dataclass
class FacebookReview(RemoteReview):
    """Avis Facebook ; `name` = identifiant de l'open graph story (cible de `POST /{id}/comments`)."""

    @classmethod
    def from_api(cls, data: dict[str, Any], page_id: str) -> FacebookReview:
        story_id = str((data.get("open_graph_story") or {}).get("id") or "")
        reviewer = data.get("reviewer") or {}
        created = data.get("created_time") or now_iso()
        rating = data.get("rating")
        note = None
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            rec = (data.get("recommendation_type") or "").lower()
            if rec in RECOMMENDATION_RATING:
                rating = RECOMMENDATION_RATING[rec]
                note = (f"Recommandation Facebook sans note (« {rec} ») : comptée "
                        f"{rating} étoile{'s' if rating > 1 else ''}.")
            else:
                rating = 3
                note = "Avis Facebook sans note ni recommandation : compté 3 étoiles."
        review_id = story_id or f"{reviewer.get('id') or 'anonyme'}:{created}"
        return cls(
            name=story_id,
            review_id=review_id,
            author=reviewer.get("name") or "Anonyme",
            rating=int(rating),
            text=data.get("review_text") or "",
            create_time=created,
            update_time=None,
            reply_text=None,
            reply_time=None,
            rating_note=note,
        )


def _check_page_id(page_id: str) -> str:
    page_id = (page_id or "").strip()
    if not PAGE_ID_RE.match(page_id):
        raise FacebookError("identifiant de Page Facebook invalide (attendu : identifiant numérique)")
    return page_id


def _check_story_id(story_id: str) -> str:
    story_id = (story_id or "").strip()
    if not STORY_ID_RE.match(story_id):
        raise FacebookError("cet avis n'a pas d'identifiant de publication Facebook : réponse impossible")
    return story_id


class MockFacebookClient:
    """Sert des avis depuis un fichier JSON (format Graph API). Les commentaires publiés sont mémorisés
    (et persistés dans `state_file`) pour que le poll suivant les voie comme réponses."""

    platform = "facebook"
    name = "mock"
    can_reply = True

    def __init__(self, fixtures_path: Path | None = None, data: dict[str, Any] | None = None,
                 state_file: Path | None = None):
        if data is None:
            data = json.loads(Path(fixtures_path or PACKAGE_FIXTURE).read_text(encoding="utf-8"))
        self.data = data
        self.state_file = state_file
        self.replies: dict[str, dict[str, Any]] = {}
        if state_file and Path(state_file).exists():
            self.replies = json.loads(Path(state_file).read_text(encoding="utf-8"))

    def _ratings_for(self, page_id: str) -> list[dict[str, Any]]:
        per_page = self.data.get("pages_ratings") or {}
        return per_page.get(page_id, self.data.get("ratings", []))

    def list_ratings(self, page_id: str, token: str | None = None) -> list[FacebookReview]:
        page_id = _check_page_id(page_id)
        out = []
        for raw in self._ratings_for(page_id):
            r = FacebookReview.from_api(raw, page_id)
            if r.name in self.replies:
                r.reply_text = self.replies[r.name]["message"]
                r.reply_time = self.replies[r.name].get("created_time")
            out.append(r)
        return out

    def comment(self, story_id: str, token: str | None, message: str) -> dict[str, Any]:
        story_id = _check_story_id(story_id)
        payload = {"id": f"{story_id}_{len(self.replies) + 1}", "message": message, "created_time": now_iso()}
        self.replies[story_id] = payload
        if self.state_file:
            Path(self.state_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self.state_file).write_text(json.dumps(self.replies, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        log.info("[facebook mock] commentaire publié sur %s", story_id)
        return payload

    def get_page(self, page_id: str, token: str | None = None) -> dict[str, Any]:
        page_id = _check_page_id(page_id)
        for page in self.data.get("pages", []):
            if str(page.get("id")) == page_id:
                return {"id": page_id, "name": page.get("name")}
        return {"id": page_id, "name": f"Page Facebook {page_id} (démo)"}

    # --- protocole PlatformClient ---
    def fetch_reviews(self, source: ReviewSource, credentials: str | None) -> list[RemoteReview]:
        return list(self.list_ratings(source.external_id, credentials))

    def publish_reply(self, source: ReviewSource, credentials: str | None, review_name: str,
                      text: str) -> dict[str, Any]:
        return self.comment(review_name, credentials, text)

    def verify_source(self, external_id: str, credentials: str | None) -> dict[str, Any]:
        page = self.get_page(external_id, credentials)
        return {**page, "public_url": page_reviews_url(page["id"])}


class LiveFacebookClient:
    """Appels réels à la Graph API avec le jeton de Page de chaque source (en-tête Authorization, jamais
    dans l'URL). Délai d'attente, pagination `paging.next`, erreurs enveloppées en `FacebookError`
    (jeton expiré ou révoqué → `FacebookAuthError` : la source est marquée en erreur, le poll continue)."""

    platform = "facebook"
    name = "live"
    can_reply = True
    REQUEST_TIMEOUT_S = 30

    def __init__(self, graph_version: str = "v21.0", transport: httpx.BaseTransport | None = None,
                 timeout_s: float = REQUEST_TIMEOUT_S):
        if not re.match(r"^v\d+\.\d+$", graph_version):
            raise ValueError(f"version Graph API invalide : {graph_version}")
        self.base_url = f"{GRAPH_HOST}/{graph_version}"
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def _request(self, method: str, url: str, token: str | None, what: str, *, params: dict | None = None,
                 data: dict | None = None) -> dict[str, Any]:
        if not token:
            raise FacebookAuthError(f"Facebook {what} : aucun jeton de Page enregistré pour cette source")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = self._client.request(method, url, params=params, data=data, headers=headers)
        except httpx.HTTPError as e:
            raise FacebookError(f"Facebook {what} injoignable : {e.__class__.__name__}") from e
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        if r.status_code >= 400 or error:
            error = error or {}
            message = str(error.get("message") or r.text[:200])
            code = error.get("code")
            if code in AUTH_ERROR_CODES or error.get("type") == "OAuthException" or r.status_code == 401:
                raise FacebookAuthError(f"Facebook {what} : jeton de Page refusé ({message}) ; "
                                        "renouvelez le jeton depuis les réglages de l'établissement")
            raise FacebookError(f"Facebook {what} : HTTP {r.status_code} {message}")
        return body if isinstance(body, dict) else {}

    def list_ratings(self, page_id: str, token: str | None) -> list[FacebookReview]:
        page_id = _check_page_id(page_id)
        url: str | None = f"{self.base_url}/{page_id}/ratings"
        params: dict[str, Any] | None = {"fields": RATINGS_FIELDS, "limit": 100}
        reviews: list[FacebookReview] = []
        for _ in range(MAX_PAGES):
            data = self._request("GET", url, token, "liste des avis", params=params)
            reviews.extend(FacebookReview.from_api(raw, page_id) for raw in data.get("data", [])
                           if isinstance(raw, dict))
            url = (data.get("paging") or {}).get("next")
            params = None  # l'URL `next` porte déjà les paramètres
            if not url or not url.startswith(GRAPH_HOST):
                break
        return reviews

    def comment(self, story_id: str, token: str | None, message: str) -> dict[str, Any]:
        story_id = _check_story_id(story_id)
        return self._request("POST", f"{self.base_url}/{story_id}/comments", token, "réponse à un avis",
                             data={"message": message})

    def get_page(self, page_id: str, token: str | None) -> dict[str, Any]:
        """Identité de la Page à laquelle appartient le jeton : doit être l'identifiant saisi."""
        page_id = _check_page_id(page_id)
        me = self._request("GET", f"{self.base_url}/me", token, "vérification de la Page",
                           params={"fields": "id,name"})
        if str(me.get("id")) != page_id:
            raise FacebookError(f"le jeton fourni appartient à la Page « {me.get('name')} » (id {me.get('id')}), "
                                f"pas à l'identifiant saisi {page_id}")
        return {"id": page_id, "name": me.get("name")}

    # --- protocole PlatformClient ---
    def fetch_reviews(self, source: ReviewSource, credentials: str | None) -> list[RemoteReview]:
        return list(self.list_ratings(source.external_id, credentials))

    def publish_reply(self, source: ReviewSource, credentials: str | None, review_name: str,
                      text: str) -> dict[str, Any]:
        return self.comment(review_name, credentials, text)

    def verify_source(self, external_id: str, credentials: str | None) -> dict[str, Any]:
        page = self.get_page(external_id, credentials)
        return {**page, "public_url": page_reviews_url(page["id"])}


def build_facebook_client(settings: AppSettings):
    if settings.facebook_mode == "live":
        return LiveFacebookClient(settings.facebook_graph_version)
    return MockFacebookClient(settings.facebook_fixtures_file,
                              state_file=settings.data_dir / "facebook_mock_replies.json")
