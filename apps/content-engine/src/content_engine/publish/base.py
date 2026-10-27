"""Contrat commun des connecteurs : une publication est d'abord une liste de requêtes HTTP décrites
(dry-run : écrites dans out/<id>/publish-<plateforme>.json), puis éventuellement envoyées (--live)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..db import utc_now_iso
from ..products import Product
from ..settings import Settings

SECRET_HEADERS = {"authorization", "xi-api-key", "x-api-key"}


class PublishError(RuntimeError):
    """Publication impossible : fichier manquant, clé absente, format incompatible, erreur API."""


def redact(value: str) -> str:
    """Masque un secret dans la trace dry-run (les marqueurs <…> restent lisibles)."""
    if "<" in value:
        return value
    scheme, _, token = value.partition(" ")
    if not token:
        token, scheme = scheme, ""
    masked = token[:4] + "…[masqué]" if len(token) > 8 else "[masqué]"
    return f"{scheme} {masked}".strip()


@dataclass
class FileRef:
    field: str
    path: str
    size: int
    content_type: str


def file_ref(field_name: str, path: Path, content_type: str) -> FileRef:
    return FileRef(field_name, str(path), path.stat().st_size, content_type)


@dataclass
class PublishRequest:
    step: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    files: list[FileRef] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["headers"] = {k: (redact(v) if k.lower() in SECRET_HEADERS else v)
                        for k, v in self.headers.items()}
        return d


@dataclass
class PublishPlan:
    platform: str
    draft_id: int
    requests: list[PublishRequest]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"platform": self.platform, "draft_id": self.draft_id, "summary": self.summary,
                "requests": [r.to_dict() for r in self.requests]}


@dataclass
class PublishOutcome:
    platform: str
    remote_id: str | None
    url: str | None
    response: Any = None


@dataclass
class PublishContext:
    draft: dict
    payload: dict
    product: Product
    settings: Settings
    out_dir: Path
    render: dict | None = None

    def file(self, name: str) -> Path:
        return self.out_dir / name

    def require_file(self, name: str, hint: str) -> Path:
        p = self.file(name)
        if not p.exists():
            raise PublishError(f"fichier {p} absent : {hint}")
        return p

    @property
    def synthetic(self) -> bool:
        """Voix ou image synthétique → drapeau IA sur YouTube et TikTok (vrai par défaut)."""
        if not self.render:
            return True
        return bool(self.render.get("synthetic_voice") or self.render.get("synthetic_image"))

    def bearer(self, token: str | None, env_name: str) -> str:
        return f"Bearer {token}" if token else f"Bearer <{env_name}>"


class Publisher(Protocol):
    platform: str

    def build(self, ctx: PublishContext) -> PublishPlan: ...

    def send(self, plan: PublishPlan, ctx: PublishContext, client: httpx.Client) -> PublishOutcome: ...


def write_dry_run(plan: PublishPlan, out_dir: Path, live: bool = False) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"publish-{plan.platform}.json"
    data = {"dry_run": not live, "generated_at": utc_now_iso(), **plan.to_dict()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def require_token(token: str | None, env_name: str) -> str:
    if not token:
        raise PublishError(f"{env_name} manquant dans .env : publication réelle impossible")
    return token


def raise_for_status(r: httpx.Response, platform: str) -> None:
    if r.status_code >= 400:
        raise PublishError(f"{platform} : HTTP {r.status_code} — {r.text[:400]}")
