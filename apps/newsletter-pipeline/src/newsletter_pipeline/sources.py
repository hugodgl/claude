"""Chargement de `sources.yaml` et synchronisation dans la table `sources`."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import db

KINDS = ("rss", "page")
CATEGORIES = ("editeurs", "presse_pro", "institutions", "ia_generale", "newsletters_en", "autre")


@dataclass
class SourceSpec:
    name: str
    url: str
    kind: str = "rss"
    category: str = "autre"
    lang: str = "fr"
    weight: float = 1.0
    active: bool = True
    verify: bool = False
    include_patterns: list[str] = field(default_factory=list)
    notes: str | None = None

    def validate(self) -> None:
        if not self.name or not self.url:
            raise ValueError("source sans nom ou sans url")
        if self.kind not in KINDS:
            raise ValueError(f"source {self.name!r} : kind doit être rss ou page (reçu {self.kind!r})")
        if self.category not in CATEGORIES:
            raise ValueError(f"source {self.name!r} : catégorie inconnue {self.category!r}")
        if not 0 < float(self.weight) <= 3:
            raise ValueError(f"source {self.name!r} : weight doit être dans ]0, 3]")


def load_sources(path: str | Path) -> list[SourceSpec]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"fichier de sources introuvable : {p}")
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for raw in data.get("sources") or []:
        merged = {**defaults, **raw}
        allowed = {k: merged[k] for k in SourceSpec.__dataclass_fields__ if k in merged}
        spec = SourceSpec(**allowed)
        spec.weight = float(spec.weight)
        spec.active = bool(spec.active)
        spec.verify = bool(spec.verify)
        spec.include_patterns = list(spec.include_patterns or [])
        spec.validate()
        if spec.name in seen:
            raise ValueError(f"source en double dans {p.name} : {spec.name!r}")
        seen.add(spec.name)
        specs.append(spec)
    return specs


def sync_sources(conn: sqlite3.Connection, specs: list[SourceSpec]) -> dict[str, int]:
    """Insère ou met à jour chaque source du YAML. Les sources absentes du YAML sont désactivées
    (jamais supprimées : leurs items restent exploitables)."""
    before = {r["name"] for r in db.list_sources(conn)}
    names = set()
    for spec in specs:
        db.upsert_source(conn, asdict(spec))
        names.add(spec.name)
    removed = before - names
    if removed:
        marks = ",".join("?" * len(removed))
        with conn:
            conn.execute(
                f"UPDATE sources SET active = 0, updated_at = ? WHERE name IN ({marks})",
                (db.now_iso(), *removed),
            )
    return {"total": len(specs), "inserted": len(names - before), "updated": len(names & before),
            "deactivated": len(removed)}
