"""Push du numéro vers la plateforme d'envoi.

- `beehiiv` : API v2, `POST {base}/publications/{publication_id}/posts` avec le HTML et le statut
  `draft`. Dry-run par défaut : la requête exacte est écrite dans `out/push-beehiiv-NNN.json`.
  Repli documenté dans le README si l'endpoint n'est pas ouvert sur le plan : copier-coller du HTML.
- `kessel` : pas d'API publique connue ; on écrit les fichiers et la marche à suivre (copier-coller).
- `file` : régénère simplement les fichiers HTML/texte depuis le markdown relu.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import db
from .draft import issue_meta
from .render import rerender_from_markdown
from .settings import Settings

TARGETS = ("beehiiv", "kessel", "file")


class PushError(RuntimeError):
    pass


@dataclass
class PushResult:
    target: str
    live: bool
    number: int
    paths: dict[str, Path]
    request_path: Path | None = None
    response: dict[str, Any] | None = None
    messages: list[str] = field(default_factory=list)


def build_beehiiv_request(settings: Settings, issue: sqlite3.Row, html: str, meta: dict[str, Any]) -> dict[str, Any]:
    publication = settings.beehiiv_publication_id or "pub_XXXXXXXX"
    payload: dict[str, Any] = {
        "title": issue["title"],
        "subtitle": meta.get("preheader") or settings.newsletter_tagline,
        "status": "draft",
        "content_tags": list(settings.beehiiv_content_tags),
        "body_content": html,
        "email_settings": {"preview_text": meta.get("preheader") or ""},
        "web_settings": {"hide_from_feed": False},
    }
    return {
        "method": "POST",
        "url": f"{settings.beehiiv_base_url.rstrip('/')}/publications/{publication}/posts",
        "headers": {"Authorization": "Bearer ${BEEHIIV_API_KEY}", "Content-Type": "application/json",
                    "Accept": "application/json"},
        "json": payload,
    }


def _prepare(conn: sqlite3.Connection, settings: Settings, number: int, *,
             render: bool) -> tuple[sqlite3.Row, dict, dict]:
    issue = db.get_issue(conn, number)
    if issue is None:
        raise PushError(f"numéro {number} introuvable : lance d'abord `np draft --issue {number}`")
    md_path = Path(issue["md_path"])
    if not md_path.exists():
        raise PushError(f"fichier markdown absent : {md_path}")
    meta = issue_meta(settings, issue)
    if render:
        paths = rerender_from_markdown(md_path, meta)
    else:
        paths = {"md": md_path, "html": md_path.with_suffix(".html"), "txt": md_path.with_suffix(".txt")}
    return issue, meta, paths


def push_issue(conn: sqlite3.Connection, settings: Settings, number: int, target: str, *, live: bool = False,
               client: httpx.Client | None = None, render: bool = True) -> PushResult:
    if target not in TARGETS:
        raise PushError(f"cible inconnue : {target!r} (attendu : {', '.join(TARGETS)})")
    issue, meta, paths = _prepare(conn, settings, number, render=render)
    out_dir = Path(settings.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = PushResult(target=target, live=live, number=number, paths=paths)
    html = paths["html"].read_text(encoding="utf-8")

    if target == "file":
        copy = out_dir / f"push-file-{number:03d}.html"
        shutil.copyfile(paths["html"], copy)
        result.request_path = out_dir / f"push-file-{number:03d}.json"
        result.request_path.write_text(json.dumps(
            {"target": "file", "number": number, "title": issue["title"],
             "files": {k: str(v) for k, v in paths.items()}, "copy": str(copy)}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        result.messages.append(f"HTML prêt à coller : {copy}")
        return result

    if target == "kessel":
        result.request_path = out_dir / f"push-kessel-{number:03d}.json"
        result.request_path.write_text(json.dumps({
            "target": "kessel", "mode": "manuel", "number": number, "title": issue["title"],
            "publication_url": settings.kessel_publication_url,
            "html_path": str(paths["html"]), "txt_path": str(paths["txt"]),
            "instructions": [
                "Kessel n'expose pas d'API publique de création de brouillon (vérifié au moment de l'écriture).",
                "Ouvrir l'éditeur Kessel → nouveau numéro → coller le contenu du fichier HTML (ou le markdown).",
                "Vérifier le titre, l'aperçu, le sponsor, puis programmer l'envoi du mardi 7 h.",
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if live:
            raise PushError("Kessel : pas d'API publique, envoi --live impossible ; "
                            f"marche à suivre dans {result.request_path}")
        result.messages.append(f"Marche à suivre écrite dans {result.request_path}")
        return result

    # beehiiv
    request = build_beehiiv_request(settings, issue, html, meta)
    result.request_path = out_dir / f"push-beehiiv-{number:03d}.json"
    result.request_path.write_text(json.dumps(
        {"live": live, "note": "Requête exacte ; la clé API est lue dans BEEHIIV_API_KEY au moment de l'envoi.",
         **request}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not live:
        result.messages.append(f"Dry-run : requête écrite dans {result.request_path} (ajoute --live pour envoyer)")
        return result
    if not settings.beehiiv_api_key or not settings.beehiiv_publication_id:
        raise PushError("BEEHIIV_API_KEY et BEEHIIV_PUBLICATION_ID sont requis pour --live")
    headers = {**request["headers"], "Authorization": f"Bearer {settings.beehiiv_api_key}"}
    http = client or httpx.Client(timeout=60)
    try:
        response = http.post(request["url"], json=request["json"], headers=headers)
    except httpx.HTTPError as exc:
        raise PushError(f"beehiiv injoignable : {exc}") from exc
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:2000]}
    response_path = out_dir / f"push-beehiiv-{number:03d}.response.json"
    response_path.write_text(json.dumps({"status_code": response.status_code, "body": body},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
    if response.status_code >= 400:
        hint = (" Repli : copier-coller le HTML dans l'éditeur beehiiv (voir README)."
                if response.status_code in (401, 402, 403, 404) else "")
        raise PushError(f"beehiiv HTTP {response.status_code} : {str(body)[:300]}.{hint}")
    result.response = body if isinstance(body, dict) else {"body": body}
    db.save_issue(conn, number, status="pushed", pushed_target="beehiiv", pushed_at=db.now_iso())
    post_id = (result.response.get("data") or {}).get("id") if isinstance(result.response.get("data"), dict) else None
    suffix = f" (id {post_id})" if post_id else ""
    result.messages.append(f"Brouillon créé sur beehiiv{suffix} ; réponse : {response_path}")
    return result
