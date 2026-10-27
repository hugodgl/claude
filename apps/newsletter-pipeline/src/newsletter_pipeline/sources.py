"""Chargement de `sources.yaml` et synchronisation dans la table `sources`.

Toute erreur du fichier (YAML illisible, clé inconnue, type faux, regex invalide) lève une `ValueError`
qui nomme le fichier et la source concernée : le CLI l'affiche telle quelle.
"""
from __future__ import annotations

import re
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

    def normalize(self) -> None:
        """Convertit les champs vers les types attendus ; ValueError (sans nom de source) si impossible."""
        self.name = str(self.name or "").strip()
        self.url = str(self.url or "").strip()
        self.kind = str(self.kind or "").strip().lower()
        self.category = str(self.category or "").strip()
        self.lang = str(self.lang or "fr").strip()
        try:
            self.weight = float(self.weight)
        except (TypeError, ValueError):
            raise ValueError(f"weight doit être un nombre (reçu {self.weight!r})") from None
        for attr in ("active", "verify"):
            value = getattr(self, attr)
            if isinstance(value, bool):
                continue
            if value in (0, 1):
                setattr(self, attr, bool(value))
                continue
            raise ValueError(f"{attr} doit être true ou false (reçu {value!r})")
        patterns: Any = self.include_patterns or []
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ValueError("include_patterns doit être une liste de motifs (regex)")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"include_patterns : motif invalide {pattern!r} ({exc})") from None
        self.include_patterns = patterns
        self.notes = None if self.notes is None else str(self.notes)

    def validate(self) -> None:
        if not self.name or not self.url:
            raise ValueError("source sans nom ou sans url")
        if self.kind not in KINDS:
            raise ValueError(f"kind doit être rss ou page (reçu {self.kind!r})")
        if self.category not in CATEGORIES:
            raise ValueError(f"catégorie inconnue {self.category!r} (attendu : {', '.join(CATEGORIES)})")
        if not 0 < self.weight <= 3:
            raise ValueError(f"weight doit être dans ]0, 3] (reçu {self.weight})")
        if self.kind == "page" and not self.url.lower().startswith(("http://", "https://")):
            raise ValueError("une source de type page doit avoir une url http(s)")


def load_sources(path: str | Path) -> list[SourceSpec]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"fichier de sources introuvable : {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{p.name} illisible (YAML invalide) : {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{p.name} : le document doit être un mapping avec une clé `sources`")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"{p.name} : `defaults` doit être un mapping")
    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raise ValueError(f"{p.name} : `sources` doit être une liste (un tiret par source)")
    known = set(SourceSpec.__dataclass_fields__)
    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_sources, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"{p.name} : source n° {index} : attendu un mapping (name, url, kind…)")
        label = str(raw.get("name") or f"n° {index}")
        merged = {**defaults, **raw}
        unknown = sorted(str(k) for k in merged if k not in known)
        if unknown:
            raise ValueError(f"{p.name} : source {label!r} : clé(s) inconnue(s) : {', '.join(unknown)} "
                             f"(attendu : {', '.join(sorted(known))})")
        spec = SourceSpec(**{k: merged[k] for k in known if k in merged})
        try:
            spec.normalize()
            spec.validate()
        except ValueError as exc:
            raise ValueError(f"{p.name} : source {label!r} : {exc}") from None
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
