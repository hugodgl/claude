"""Bibliothèque de cas d'usage (`cases/*.md`, en-tête YAML + corps markdown prêt à copier)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class UseCase:
    slug: str
    title: str
    body: str
    path: Path
    themes: list[str] = field(default_factory=list)
    summary: str = ""
    duration: str = ""
    tools: str = ""


def _split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            return (meta if isinstance(meta, dict) else {}), parts[2].strip()
    return {}, text.strip()


def load_cases(cases_dir: str | Path) -> list[UseCase]:
    cases: list[UseCase] = []
    for path in sorted(Path(cases_dir).glob("*.md")):
        meta, body = _split_front_matter(path.read_text(encoding="utf-8"))
        slug = str(meta.get("slug") or path.stem)
        title = str(meta.get("title") or slug.replace("-", " ").capitalize())
        cases.append(UseCase(
            slug=slug, title=title, body=body, path=path,
            themes=[str(t) for t in (meta.get("themes") or [])],
            summary=str(meta.get("summary") or ""), duration=str(meta.get("duration") or ""),
            tools=str(meta.get("tools") or ""),
        ))
    if not cases:
        raise FileNotFoundError(f"aucun cas d'usage dans {cases_dir}")
    return cases


def pick_case(cases: list[UseCase], *, issue_number: int, themes: list[str] | None = None,
              recent_slugs: list[str] | None = None, forced_slug: str | None = None) -> UseCase:
    """Choisit le cas du numéro : slug imposé, sinon celui qui recoupe le plus les thèmes de la
    semaine parmi ceux non utilisés récemment, égalité départagée par rotation sur le numéro."""
    if forced_slug:
        for case in cases:
            if case.slug == forced_slug:
                return case
        raise LookupError(f"cas d'usage inconnu : {forced_slug!r} ({', '.join(c.slug for c in cases)})")
    recent = set(recent_slugs or [])
    pool = [c for c in cases if c.slug not in recent] or cases
    counts = Counter(themes or [])
    best = max(sum(counts[t] for t in c.themes) for c in pool)
    tied = [c for c in pool if sum(counts[t] for t in c.themes) == best]
    return tied[(issue_number - 1) % len(tied)]
