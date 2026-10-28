"""YouTube Data API v3 : videos.insert (envoi reprenable) + thumbnails.set, OAuth « application de
bureau » (google-auth-oauthlib), jeton stocké dans data/youtube-token.json."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..settings import Settings
from ..texts import compose_description, hashtags_line, youtube_title
from .base import (
    PublishContext,
    PublishError,
    PublishOutcome,
    PublishPlan,
    PublishRequest,
    file_ref,
    raise_for_status,
)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"  # videos.list (vidéos privées)
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"  # reports.query
# portées demandées au consentement (+ ANALYTICS_SCOPE si YOUTUBE_ANALYTICS, voir consent_scopes)
SCOPES = [UPLOAD_SCOPE, READONLY_SCOPE]
TAGS_MAX_CHARS = 400


def consent_scopes(settings: Settings) -> list[str]:
    """Portées demandées lors du consentement OAuth (une seule fois, dans un terminal)."""
    return SCOPES + ([ANALYTICS_SCOPE] if settings.youtube_analytics else [])


def token_scopes(settings: Settings) -> set[str]:
    """Portées enregistrées dans le jeton (vide sans jeton ou jeton illisible) ; lecture JSON
    simple, sans dépendre de google-auth."""
    path = Path(settings.youtube_token_file)
    if not path.exists():
        return set()
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set(info.get("scopes") or []) if isinstance(info, dict) else set()


def get_access_token(settings: Settings, needed: Iterable[str] = (UPLOAD_SCOPE,)) -> str:
    """Jeton OAuth : lit data/youtube-token.json, le rafraîchit, ou lance le consentement local.
    `needed` : portées exigées pour l'opération (upload pour publier, readonly pour relever les
    métriques) ; un jeton enregistré sans elles demande un nouveau consentement."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise PublishError("installer l'extra : uv pip install -e '.[youtube]'") from e
    token_file, secrets = (
        Path(settings.youtube_token_file),
        Path(settings.youtube_client_secrets_file),
    )
    creds = None
    if token_file.exists():
        try:
            info = json.loads(token_file.read_text(encoding="utf-8"))
            recorded = list(info.get("scopes") or consent_scopes(settings))
            creds = Credentials.from_authorized_user_info(info, recorded)
        except (ValueError, AttributeError) as e:
            raise PublishError(f"jeton YouTube illisible ({token_file}) : {e}") from e
        missing = sorted(set(needed) - set(recorded))
        if missing:
            raise PublishError(
                f"le jeton YouTube ({token_file}) n'a pas la portée {', '.join(missing)} : "
                "supprimer ce fichier et relancer `ce publish --draft-id N --platform youtube "
                "--live` dans un terminal pour un nouveau consentement"
            )
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # RefreshError (jeton révoqué) ou réseau : message lisible
            raise PublishError(
                f"rafraîchissement du jeton YouTube impossible : {e} — supprimer {token_file} "
                "et relancer la publication dans un terminal pour un nouveau consentement"
            ) from e
    elif not creds or not creds.valid:
        if not secrets.exists():
            raise PublishError(
                f"{secrets} absent : télécharger l'identifiant OAuth « application de bureau » "
                "depuis Google Cloud (API YouTube Data v3 activée)"
            )
        if not sys.stdin.isatty():  # launchd : pas de navigateur, ne pas bloquer le job
            raise PublishError(
                "consentement OAuth YouTube requis : lancer une première fois "
                "`ce publish --draft-id N --platform youtube --live` dans un terminal "
                f"(le jeton est ensuite conservé dans {token_file})"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), consent_scopes(settings))
        creds = flow.run_local_server(port=0, open_browser=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds.token


class YouTubePublisher:
    platform = "youtube"

    def __init__(self, token: str | None = None):
        self._token = token

    def body(self, ctx: PublishContext) -> dict:
        s, p = ctx.settings, ctx.payload
        tags: list[str] = []
        for tag in hashtags_line(p, ctx.product, limit=8).replace("#", "").split():
            if sum(len(t) + 1 for t in tags) + len(tag) > TAGS_MAX_CHARS:
                break  # YouTube : 500 caractères de tags au total (invalidTags sinon)
            tags.append(tag)
        return {
            "snippet": {
                "title": youtube_title(p),
                "description": compose_description(p, ctx.product, s),
                "tags": tags,
                "categoryId": s.youtube_category_id,
                "defaultLanguage": "fr",
                "defaultAudioLanguage": "fr",
            },
            "status": {
                "privacyStatus": s.youtube_privacy_status,
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
                "containsSyntheticMedia": ctx.synthetic,
                "embeddable": True,
                "license": "youtube",
            },
        }

    def build(self, ctx: PublishContext) -> PublishPlan:
        video_name = (ctx.render or {}).get("video") or "video.mp4"
        video = ctx.require_file(
            video_name,
            "lancer `ce render --draft-id N` (ou copier la vidéo longue enregistrée sous ce nom)",
        )
        thumb = ctx.file("thumb.jpg")
        body = self.body(ctx)
        size = video.stat().st_size
        auth = self.bearer_header(ctx)
        requests = [
            PublishRequest(
                step="videos.insert : ouverture de l'envoi reprenable",
                method="POST",
                url=UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": auth,
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(size),
                },
                json=body,
                notes=[
                    f"Portées OAuth demandées au consentement : "
                    f"{' '.join(consent_scopes(ctx.settings))}",
                    "status.containsSyntheticMedia = vrai quand la voix ou l'image sont "
                    "synthétiques (étiquetage obligatoire)",
                    "status.selfDeclaredMadeForKids = faux (contenu professionnel)",
                ],
            ),
            PublishRequest(
                step="videos.insert : envoi du fichier",
                method="PUT",
                url="<Location renvoyé par l'étape précédente>",
                headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                files=[file_ref("body", video, "video/mp4")],
            ),
        ]
        if thumb.exists():
            requests.append(
                PublishRequest(
                    step="thumbnails.set",
                    method="POST",
                    url=THUMB_URL,
                    params={
                        "videoId": "<id renvoyé par l'étape précédente>",
                        "uploadType": "media",
                    },
                    headers={"Authorization": auth, "Content-Type": "image/jpeg"},
                    files=[file_ref("body", thumb, "image/jpeg")],
                    notes=["Miniature personnalisée : la chaîne doit être vérifiée (téléphone)"],
                )
            )
        summary = {
            "title": body["snippet"]["title"],
            "privacyStatus": body["status"]["privacyStatus"],
            "containsSyntheticMedia": body["status"]["containsSyntheticMedia"],
            "selfDeclaredMadeForKids": False,
            "video": str(video),
            "bytes": size,
        }
        return PublishPlan(self.platform, int(ctx.draft["id"]), requests, summary)

    def bearer_header(self, ctx: PublishContext) -> str:
        return f"Bearer {self._token}" if self._token else "Bearer <jeton OAuth YouTube>"

    def send(self, plan: PublishPlan, ctx: PublishContext, client: httpx.Client) -> PublishOutcome:
        token = self._token or get_access_token(ctx.settings)
        auth = {"Authorization": f"Bearer {token}"}
        init, upload = plan.requests[0], plan.requests[1]
        r = client.post(
            init.url, params=init.params, json=init.json, headers={**init.headers, **auth}
        )
        raise_for_status(r, "YouTube (init)")
        location = r.headers.get("Location")
        if not location:
            raise PublishError("YouTube : en-tête Location absent de la réponse d'ouverture")
        content = Path(upload.files[0].path).read_bytes()
        r2 = client.put(location, content=content, headers={"Content-Type": "video/mp4", **auth})
        raise_for_status(r2, "YouTube (upload)")
        data = r2.json()
        video_id = data.get("id")
        if not video_id:
            raise PublishError(f"YouTube : réponse sans id : {json.dumps(data)[:300]}")
        if len(plan.requests) > 2:
            thumb = plan.requests[2]
            r3 = client.post(
                thumb.url,
                params={"videoId": video_id, "uploadType": "media"},
                content=Path(thumb.files[0].path).read_bytes(),
                headers={"Content-Type": "image/jpeg", **auth},
            )
            if r3.status_code >= 400:
                data["thumbnail_error"] = r3.text[:300]
        return PublishOutcome(self.platform, video_id, f"https://youtu.be/{video_id}", data)
