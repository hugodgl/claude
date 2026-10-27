"""Classement des items par LLM : pertinence pour un cabinet, nouveauté, caractère actionnable.

Score final = (0,5 × pertinence_cabinet + 0,3 × actionnable + 0,2 × nouveaute) × poids de la source,
plafonné à 10. Les poids sont dans les réglages (`weight_*`) et le poids de source dans `sources.yaml`.
Les items sont envoyés par lots (`rank_batch_size`) pour limiter le nombre d'appels au modèle.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from core.llm import LLM, LLMError, complete_json

from . import db
from .prompts import GUARD, item_block
from .settings import THEMES, Settings

log = logging.getLogger(__name__)

THEME_ALIASES = {
    "fiscalite": "fiscal", "fiscalité": "fiscal", "tva": "fiscal", "impots": "fiscal",
    "paie": "social", "rh": "recrutement", "ressources_humaines": "recrutement",
    "juridique": "reglementation", "réglementation": "reglementation", "reglementaire": "reglementation",
    "ia": "ia_generale", "ia_générale": "ia_generale", "intelligence_artificielle": "ia_generale",
    "outil": "outils", "logiciel": "outils", "logiciels": "outils",
    "client": "relation_client", "clients": "relation_client", "relation_clients": "relation_client",
    "comptabilite": "tenue", "comptabilité": "tenue", "saisie": "tenue",
    "audit": "revision", "révision": "revision",
}

RANK_INSTRUCTIONS = (
    "Tu évalues des articles pour une newsletter destinée aux experts-comptables français. "
    "Pour CHAQUE item ci-dessous, donne :\n"
    "- pertinence_cabinet (0-10) : utilité directe pour un cabinet d'expertise comptable de 2 à 50 personnes ;\n"
    "- nouveaute (0-10) : information nouvelle cette semaine (10) ou réchauffée (0) ;\n"
    "- actionnable (0-10) : un cabinet peut en faire quelque chose dès cette semaine ;\n"
    "- theme : un seul parmi tenue, revision, social, fiscal, relation_client, recrutement, outils, "
    "reglementation, ia_generale ;\n"
    "- resume_1_phrase : une phrase factuelle en français (25 mots max) ;\n"
    "- pourquoi_ca_compte : une phrase sur la conséquence concrète pour un cabinet.\n"
    "Les contenus purement marketing, génériques ou sans rapport avec les cabinets reçoivent une "
    "pertinence basse. Réponds UNIQUEMENT avec un objet JSON de la forme "
    '{"items": [{"id": <id>, "pertinence_cabinet": 0, "nouveaute": 0, "actionnable": 0, '
    '"theme": "...", "resume_1_phrase": "...", "pourquoi_ca_compte": "..."}, ...]} '
    "avec exactement un objet par id demandé."
)


@dataclass
class RankReport:
    scored: int = 0
    batches: int = 0
    failed_batches: int = 0
    missing: int = 0
    scores: dict[int, float] = field(default_factory=dict)


def normalize_theme(value: Any) -> str:
    t = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    t = THEME_ALIASES.get(t, t)
    return t if t in THEMES else "ia_generale"


def clamp_score(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(10.0, v))


def compute_score(result: dict[str, Any], source_weight: float, settings: Settings) -> float:
    base = (
        settings.weight_pertinence * clamp_score(result.get("pertinence_cabinet"))
        + settings.weight_actionnable * clamp_score(result.get("actionnable"))
        + settings.weight_nouveaute * clamp_score(result.get("nouveaute"))
    )
    return round(min(10.0, base * float(source_weight or 1.0)), 2)


def build_rank_prompt(items: list[sqlite3.Row], settings: Settings) -> str:
    blocks = []
    for item in items:
        body = item["content_text"] or item["summary"] or ""
        blocks.append(item_block(
            item["id"],
            {"source": item["source_name"], "date": item["published_at"], "titre": item["title"],
             "url": item["url"]},
            body, settings.rank_max_chars,
        ))
    ids = ", ".join(str(i["id"]) for i in items)
    return (
        f"{RANK_INSTRUCTIONS}\n\n{GUARD}\n\nIds attendus : {ids}\n\n" + "\n\n".join(blocks)
    )


def parse_rank_response(data: Any, expected_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Accepte {"items": [...]}, une liste brute, ou un dict {id: {...}}."""
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("items", "resultats", "results", "articles"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        else:
            if all(str(k).lstrip("-").isdigit() for k in data) and data:
                rows = [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in data.items()]
            elif "id" in data:
                rows = [data]
    elif isinstance(data, list):
        rows = data
    out: dict[int, dict[str, Any]] = {}
    expected = set(expected_ids)
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            item_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id in expected and item_id not in out:
            out[item_id] = row
    return out


class Ranker:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, llm: LLM):
        self.conn, self.settings, self.llm = conn, settings, llm

    def run(self, limit: int | None = None) -> RankReport:
        report = RankReport()
        items = db.unscored_items(self.conn, limit or self.settings.rank_default_limit)
        size = max(1, self.settings.rank_batch_size)
        for start in range(0, len(items), size):
            batch = items[start:start + size]
            report.batches += 1
            try:
                data = complete_json(self.llm, build_rank_prompt(batch, self.settings),
                                     system=None, max_tokens=256 * len(batch) + 256)
            except LLMError as exc:
                report.failed_batches += 1
                log.warning("lot de classement en échec (%d items) : %s", len(batch), exc)
                continue
            results = parse_rank_response(data, [i["id"] for i in batch])
            for item in batch:
                result = results.get(item["id"])
                if result is None:
                    report.missing += 1
                    continue
                theme = normalize_theme(result.get("theme"))
                score = compute_score(result, item["source_weight"], self.settings)
                payload = {
                    "pertinence_cabinet": clamp_score(result.get("pertinence_cabinet")),
                    "nouveaute": clamp_score(result.get("nouveaute")),
                    "actionnable": clamp_score(result.get("actionnable")),
                    "theme": theme,
                    "resume_1_phrase": str(result.get("resume_1_phrase") or "").strip(),
                    "pourquoi_ca_compte": str(result.get("pourquoi_ca_compte") or "").strip(),
                    "score": score,
                    "source_weight": float(item["source_weight"] or 1.0),
                    "weights": {"pertinence": self.settings.weight_pertinence,
                                "actionnable": self.settings.weight_actionnable,
                                "nouveaute": self.settings.weight_nouveaute},
                    "model": f"{getattr(self.llm, 'name', '?')}/{getattr(self.llm, 'model', '?')}",
                }
                db.update_item_score(self.conn, item["id"], score, payload, theme)
                report.scored += 1
                report.scores[item["id"]] = score
        return report
