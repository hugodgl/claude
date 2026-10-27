"""Génération des scripts (3 variantes par sujet et par format) et contrôles automatiques."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from core.llm import LLM, LLMError, complete_json
from pydantic import BaseModel, Field, ValidationError, field_validator

from .db import utc_now_iso
from .products import get_product
from .prompts import APPROACHES, SYSTEM_PROMPT, script_prompt
from .topics import get_topic, set_topic_status

FORMATS = ("short", "long", "linkedin", "pin")
DRAFT_STATUSES = ("draft", "approved", "rejected", "rendered", "published")


@dataclass(frozen=True)
class FormatSpec:
    name: str
    label: str
    max_duration_s: int
    renders_video: bool


FORMAT_SPECS: dict[str, FormatSpec] = {
    "short": FormatSpec("short", "Short vertical (YouTube Shorts, TikTok)", 45, True),
    "long": FormatSpec("long", "Vidéo YouTube longue (plan en 5 parties)", 600, False),
    "linkedin": FormatSpec("linkedin", "Post LinkedIn (150 à 220 mots)", 90, False),
    "pin": FormatSpec("pin", "Épingle Pinterest (titre + description SEO)", 20, False),
}


class ScriptPayload(BaseModel):
    hook: str = Field(min_length=3)
    body: list[str] = Field(min_length=1)
    cta: str = Field(min_length=3)
    title: str = Field(min_length=3)
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    duration_s: int = 0

    @field_validator("hook", "cta", "title", "description", mode="before")
    @classmethod
    def _strip(cls, v):
        return " ".join(str(v).split()) if v is not None else ""

    @field_validator("body", mode="before")
    @classmethod
    def _body(cls, v):
        if isinstance(v, str):
            v = [p for p in re.split(r"\n+", v) if p.strip()]
        return [" ".join(str(p).split()) for p in v if str(p).strip()]

    @field_validator("hashtags", mode="before")
    @classmethod
    def _hashtags(cls, v):
        if isinstance(v, str):
            v = re.split(r"[\s,]+", v)
        out, seen = [], set()
        for tag in v or []:
            tag = re.sub(r"[^0-9a-zà-ÿ_]", "", str(tag).strip().lstrip("#").lower().replace(" ", ""))
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out[:8]

    @field_validator("duration_s", mode="before")
    @classmethod
    def _duration(cls, v):
        try:
            return max(0, int(float(v)))
        except (TypeError, ValueError):
            return 0


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
RISKY_NUMBER_RE = re.compile(
    r"\d[\d\s ]*(?:[.,]\d+)?\s*(?:%|€|k€|m€|euros?|millions?|milliers?|fois)|\b\d{3,}\b",
    re.IGNORECASE,
)


def narration_parts(payload: dict) -> list[str]:
    """Texte dit à voix haute, dans l'ordre : hook, corps, CTA."""
    return [payload["hook"], *payload["body"], payload["cta"]]


def narration_text(payload: dict) -> str:
    return " ".join(p.strip() for p in narration_parts(payload) if p.strip())


def word_count(text: str) -> int:
    return len(re.findall(r"[\wÀ-ÿ'’-]+", text))


def estimate_duration_s(text: str, words_per_second: float = 2.6, pause_s: float = 0.35) -> float:
    """Durée estimée à voix haute : ~155 mots/min plus une courte pause par phrase."""
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]
    return round(word_count(text) / words_per_second + pause_s * max(1, len(sentences)), 1)


def check_payload(payload: dict, fmt: str) -> dict:
    """Contrôles automatiques affichés à la relecture (jamais bloquants)."""
    spec = FORMAT_SPECS[fmt]
    text = narration_text(payload)
    words = word_count(text)
    est = estimate_duration_s(text)
    warnings: list[str] = []
    spoken = " ".join([payload["hook"], *payload["body"], payload["cta"], payload["title"]])
    if RISKY_NUMBER_RE.search(spoken) and "source" not in payload.get("description", "").lower():
        warnings.append("chiffre ou montant sans « Source : » dans la description")
    if re.search(r"\b(the|and|with|your|business)\b", spoken, re.IGNORECASE):
        warnings.append("mots anglais détectés")
    if fmt == "short" and est > spec.max_duration_s:
        warnings.append(f"trop long pour un short : ~{est:.0f} s (max {spec.max_duration_s} s)")
    if fmt == "long" and len(payload["body"]) != 5:
        warnings.append(f"le plan doit avoir 5 parties ({len(payload['body'])} trouvées)")
    if fmt == "linkedin" and not 150 <= words <= 220:
        warnings.append(f"post LinkedIn de {words} mots (attendu : 150 à 220)")
    if fmt == "pin":
        if len(payload["title"]) > 100:
            warnings.append(f"titre de pin trop long ({len(payload['title'])} > 100 caractères)")
        if len(payload.get("description", "")) > 500:
            warnings.append("description de pin trop longue (> 500 caractères)")
    if not payload.get("hashtags"):
        warnings.append("aucun hashtag")
    if len(payload["title"]) > 100:
        warnings.append("titre de plus de 100 caractères (limite YouTube)")
    return {"word_count": words, "estimated_duration_s": est, "warnings": warnings}


def _request_variant(llm: LLM, prompt: str) -> ScriptPayload:
    data = complete_json(llm, prompt, system=SYSTEM_PROMPT, max_tokens=3000)
    try:
        return ScriptPayload.model_validate(data)
    except ValidationError as e:
        retry = (
            prompt + "\n\nTa réponse précédente ne respectait pas le schéma demandé : "
            + str(e).splitlines()[0]
            + ". Recommence en respectant exactement les champs et leurs types."
        )
        data = complete_json(llm, retry, system=SYSTEM_PROMPT, max_tokens=3000)
        try:
            return ScriptPayload.model_validate(data)
        except ValidationError as e2:
            raise LLMError(f"script invalide après relance : {e2}") from e2


def generate_scripts(conn: sqlite3.Connection, llm: LLM, topic_id: int, fmt: str,
                     variants: int = 3) -> list[int]:
    """Génère `variants` brouillons pour un sujet et un format ; retourne leurs identifiants."""
    if fmt not in FORMAT_SPECS:
        raise ValueError(f"format inconnu : {fmt!r} (choix : {', '.join(FORMATS)})")
    topic = get_topic(conn, topic_id)
    product = get_product(topic["product"])
    ids: list[int] = []
    for variant in range(1, variants + 1):
        approach = variant if variant in APPROACHES else ((variant - 1) % len(APPROACHES)) + 1
        payload = _request_variant(
            llm, script_prompt(product, topic["question"], topic["angle"], fmt, approach)
        )
        data = payload.model_dump()
        data["checks"] = check_payload(data, fmt)
        data["approach"] = APPROACHES[approach]
        with conn:
            cur = conn.execute(
                "INSERT INTO drafts (topic_id, format, variant, payload_json, status, created_at)"
                " VALUES (?, ?, ?, ?, 'draft', ?)",
                (topic_id, fmt, variant, json.dumps(data, ensure_ascii=False), utc_now_iso()),
            )
        ids.append(int(cur.lastrowid))
    if topic["status"] == "new":
        set_topic_status(conn, topic_id, "used")
    return ids


_DRAFT_SELECT = (
    "SELECT d.*, t.product, t.question, t.angle FROM drafts d JOIN topics t ON t.id = d.topic_id"
)


def get_draft(conn: sqlite3.Connection, draft_id: int) -> sqlite3.Row:
    row = conn.execute(_DRAFT_SELECT + " WHERE d.id = ?", (draft_id,)).fetchone()
    if row is None:
        raise LookupError(f"brouillon #{draft_id} introuvable")
    return row


def draft_payload(row: sqlite3.Row) -> dict:
    return json.loads(row["payload_json"])


def list_drafts(conn: sqlite3.Connection, status: str | None = None, fmt: str | None = None,
                product: str | None = None, limit: int | None = None) -> list[sqlite3.Row]:
    sql, params = _DRAFT_SELECT + " WHERE 1=1", []
    if status:
        statuses = status.split(",")
        sql += f" AND d.status IN ({','.join('?' * len(statuses))})"
        params += statuses
    if fmt:
        sql += " AND d.format = ?"
        params.append(fmt)
    if product:
        sql += " AND t.product = ?"
        params.append(product)
    sql += " ORDER BY d.id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def set_draft_status(conn: sqlite3.Connection, draft_id: int, status: str,
                     reason: str | None = None) -> None:
    if status not in DRAFT_STATUSES:
        raise ValueError(f"statut inconnu : {status}")
    with conn:
        conn.execute(
            "UPDATE drafts SET status = ?, reject_reason = COALESCE(?, reject_reason), updated_at = ?"
            " WHERE id = ?",
            (status, reason, utc_now_iso(), draft_id),
        )
