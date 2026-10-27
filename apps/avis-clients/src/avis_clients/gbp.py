"""Client Google Business Profile : interface `ReviewsClient`, mock sur fixtures, implémentation réelle.

API réelle (approbation Google requise) :
- liste des avis : GET https://mybusiness.googleapis.com/v4/{accounts/*/locations/*}/reviews
- réponse : PUT https://mybusiness.googleapis.com/v4/{accounts/*/locations/*/reviews/*}/reply {"comment": ...}
- comptes et fiches : Account Management API v1 et Business Information API v1.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .db import now_iso
from .settings import AppSettings

log = logging.getLogger(__name__)

STAR_TO_INT = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
SCOPES = ["https://www.googleapis.com/auth/business.manage"]
BASE_V4 = "https://mybusiness.googleapis.com/v4"
ACCOUNTS_V1 = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO_V1 = "https://mybusinessbusinessinformation.googleapis.com/v1"
PACKAGE_FIXTURE = Path(__file__).parent / "fixtures" / "gbp_reviews.json"


class GBPError(RuntimeError):
    pass


@dataclass
class GBPReview:
    name: str  # accounts/{a}/locations/{l}/reviews/{r}
    review_id: str
    author: str
    rating: int
    text: str
    create_time: str
    update_time: str | None = None
    reply_text: str | None = None
    reply_time: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any], location_name: str | None = None) -> GBPReview:
        review_id = data.get("reviewId") or (data.get("name", "").rsplit("/", 1)[-1])
        name = data.get("name") or f"{location_name}/reviews/{review_id}"
        rating = data.get("starRating")
        rating_int = STAR_TO_INT.get(rating, rating if isinstance(rating, int) else 0)
        reply = data.get("reviewReply") or {}
        return cls(
            name=name,
            review_id=review_id,
            author=(data.get("reviewer") or {}).get("displayName") or "Anonyme",
            rating=int(rating_int or 0),
            text=data.get("comment") or "",
            create_time=data.get("createTime") or now_iso(),
            update_time=data.get("updateTime"),
            reply_text=reply.get("comment") or None,
            reply_time=reply.get("updateTime"),
        )


class ReviewsClient(Protocol):
    name: str

    def list_reviews(self, location_name: str) -> list[GBPReview]: ...

    def reply(self, review_name: str, text: str) -> dict[str, Any]: ...

    def list_locations(self) -> list[dict[str, Any]]: ...


class MockGBPClient:
    """Sert des avis depuis un fichier JSON (format v4). Les réponses publiées sont mémorisées
    (et persistées dans `state_file` si fourni) pour que le poll suivant les voie."""

    name = "mock"

    def __init__(self, fixtures_path: Path | None = None, data: dict[str, Any] | None = None,
                 state_file: Path | None = None):
        if data is None:
            path = fixtures_path or PACKAGE_FIXTURE
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.data = data
        self.state_file = state_file
        self.replies: dict[str, dict[str, Any]] = {}
        if state_file and Path(state_file).exists():
            self.replies = json.loads(Path(state_file).read_text(encoding="utf-8"))

    def _reviews_for(self, location_name: str) -> list[dict[str, Any]]:
        per_location = self.data.get("locations_reviews") or {}
        if location_name in per_location:
            return per_location[location_name]
        return self.data.get("reviews", [])

    def list_reviews(self, location_name: str) -> list[GBPReview]:
        out = []
        for raw in self._reviews_for(location_name):
            review_id = raw.get("reviewId") or raw.get("name", "").rsplit("/", 1)[-1]
            name = f"{location_name}/reviews/{review_id}"
            r = GBPReview.from_api({**raw, "name": name}, location_name)
            if name in self.replies:
                r.reply_text = self.replies[name]["comment"]
                r.reply_time = self.replies[name].get("updateTime")
            out.append(r)
        return out

    def reply(self, review_name: str, text: str) -> dict[str, Any]:
        payload = {"comment": text, "updateTime": now_iso()}
        self.replies[review_name] = payload
        if self.state_file:
            Path(self.state_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self.state_file).write_text(json.dumps(self.replies, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        log.info("[gbp mock] réponse publiée sur %s", review_name)
        return payload

    def list_locations(self) -> list[dict[str, Any]]:
        return list(self.data.get("locations", []))


class LiveGBPClient:
    """Appels réels via un jeton OAuth « application de bureau » (google-auth-oauthlib)."""

    name = "live"

    def __init__(self, token_file: Path, client_secrets_file: Path | None = None, session: Any | None = None):
        self.token_file = Path(token_file)
        self.client_secrets_file = client_secrets_file
        self._session = session

    @classmethod
    def authorize(cls, client_secrets_file: Path, token_file: Path, port: int = 0) -> Path:
        """Lance le flux OAuth dans le navigateur et enregistre le jeton (à faire une fois, sur le Mac)."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), scopes=SCOPES)
        creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")
        token_file = Path(token_file)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        token_file.chmod(0o600)
        return token_file

    def session(self) -> Any:
        if self._session is None:
            from google.auth.transport.requests import AuthorizedSession, Request
            from google.oauth2.credentials import Credentials

            if not self.token_file.exists():
                raise GBPError(f"jeton Google absent ({self.token_file}) : lancer `avis google auth`")
            creds = Credentials.from_authorized_user_file(str(self.token_file), scopes=SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_file.write_text(creds.to_json(), encoding="utf-8")
            self._session = AuthorizedSession(creds)
        return self._session

    def _check(self, r: Any, what: str) -> dict[str, Any]:
        if r.status_code >= 400:
            raise GBPError(f"Google {what} : HTTP {r.status_code} {getattr(r, 'text', '')[:300]}")
        return r.json() if getattr(r, "content", b"") else {}

    def list_reviews(self, location_name: str) -> list[GBPReview]:
        s = self.session()
        reviews: list[GBPReview] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token
            data = self._check(s.get(f"{BASE_V4}/{location_name}/reviews", params=params), "liste des avis")
            reviews.extend(GBPReview.from_api(r, location_name) for r in data.get("reviews", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return reviews

    def reply(self, review_name: str, text: str) -> dict[str, Any]:
        s = self.session()
        return self._check(s.put(f"{BASE_V4}/{review_name}/reply", json={"comment": text}), "réponse à un avis")

    def list_accounts(self) -> list[dict[str, Any]]:
        s = self.session()
        return self._check(s.get(f"{ACCOUNTS_V1}/accounts"), "comptes").get("accounts", [])

    def list_locations(self) -> list[dict[str, Any]]:
        s = self.session()
        out = []
        for account in self.list_accounts():
            data = self._check(
                s.get(f"{INFO_V1}/{account['name']}/locations",
                      params={"readMask": "name,title,metadata", "pageSize": 100}),
                "fiches",
            )
            for loc in data.get("locations", []):
                out.append({
                    "name": f"{account['name']}/{loc['name']}",  # ressource v4 accounts/*/locations/*
                    "title": loc.get("title"),
                    "placeId": (loc.get("metadata") or {}).get("placeId"),
                })
        return out


def build_gbp_client(settings: AppSettings) -> ReviewsClient:
    if settings.gbp_mode == "live":
        return LiveGBPClient(settings.resolved_token_file, settings.google_oauth_client_secrets_file)
    return MockGBPClient(settings.gbp_fixtures_file, state_file=settings.data_dir / "gbp_mock_replies.json")
