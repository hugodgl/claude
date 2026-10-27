"""Banque de sujets : amorçage depuis topics.yaml, dédoublonnage, idées générées par le LLM."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

import yaml
from core.llm import LLM, LLMError, complete_json

from .db import utc_now_iso
from .products import ANGLES, PRODUCTS, get_product
from .prompts import SYSTEM_PROMPT, ideas_prompt

MAX_QUESTION_CHARS = 300  # une question de prospect tient en une ligne ; au-delà, c'est un texte
IDEA_LENGTH = (12, 200)  # bornes acceptées pour une question proposée par le LLM


def normalize_question(question: str) -> str:
    """Clé de dédoublonnage : sans accents, minuscules, sans ponctuation, espaces réduits."""
    s = unicodedata.normalize("NFKD", question)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_duplicate(key: str, existing_keys: list[str], threshold: float = 0.8) -> bool:
    return any(key == k or _jaccard(key, k) >= threshold for k in existing_keys)


def load_topics_yaml(path: str | Path) -> dict[str, list[dict]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: dict[str, list[dict]] = {}
    for slug, block in (data.get("products") or {}).items():
        get_product(slug)  # valide le produit
        items = []
        for item in block.get("questions") or []:
            if isinstance(item, str):
                items.append({"question": item, "angle": None})
            else:
                items.append(
                    {"question": item.get("q") or item.get("question"), "angle": item.get("angle")}
                )
        out[slug] = [i for i in items if i["question"]]
    return out


def add_topic(
    conn: sqlite3.Connection,
    product: str,
    question: str,
    angle: str | None = None,
    source: str = "manual",
) -> int | None:
    """Insère un sujet ; retourne None si la question existe déjà (clé normalisée)."""
    get_product(product)
    question = " ".join(question.split())
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(
            f"question trop longue ({len(question)} caractères, maximum {MAX_QUESTION_CHARS})"
        )
    if angle and angle not in ANGLES:
        angle = None
    key = normalize_question(question)
    if not key:
        return None
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO topics (product, question, question_key, angle, status, source, "
                "created_at)"
                " VALUES (?, ?, ?, ?, 'new', ?, ?)",
                (product, question, key, angle, source, utc_now_iso()),
            )
    except sqlite3.IntegrityError:
        return None
    return int(cur.lastrowid)


def seed_topics(conn: sqlite3.Connection, path: str | Path) -> int:
    """Charge topics.yaml dans la table ; retourne le nombre de sujets ajoutés."""
    added = 0
    for slug, items in load_topics_yaml(path).items():
        for item in items:
            if (
                add_topic(conn, slug, item["question"], item.get("angle"), source="seed")
                is not None
            ):
                added += 1
    return added


def list_topics(
    conn: sqlite3.Connection,
    product: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    sql, params = "SELECT * FROM topics WHERE 1=1", []
    if product:
        sql += " AND product = ?"
        params.append(product)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def count_topics(conn: sqlite3.Connection, product: str | None = None, status: str = "new") -> int:
    sql, params = "SELECT COUNT(*) FROM topics WHERE status = ?", [status]
    if product:
        sql += " AND product = ?"
        params.append(product)
    return int(conn.execute(sql, params).fetchone()[0])


def get_topic(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if row is None:
        raise LookupError(f"sujet #{topic_id} introuvable")
    return row


def set_topic_status(conn: sqlite3.Connection, topic_id: int, status: str) -> None:
    with conn:
        conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))


def pick_topics(conn: sqlite3.Connection, n: int, product: str | None = None) -> list[sqlite3.Row]:
    """Sujets `new` à traiter : les plus anciens d'abord, en alternant les produits."""
    products = [product] if product else list(PRODUCTS)
    queues = {p: list(list_topics(conn, p, "new")) for p in products}
    picked: list[sqlite3.Row] = []
    while len(picked) < n and any(queues.values()):
        for p in products:
            if queues[p] and len(picked) < n:
                picked.append(queues[p].pop(0))
    return picked


def generate_ideas(conn: sqlite3.Connection, llm: LLM, product: str, count: int) -> list[dict]:
    """Demande `count` questions nouvelles au LLM, écarte les doublons, insère le reste."""
    prod = get_product(product)
    existing_rows = list_topics(conn, product)
    existing_questions = [r["question"] for r in existing_rows]
    existing_keys = [r["question_key"] for r in existing_rows]
    data = complete_json(
        llm, ideas_prompt(prod, count, existing_questions), system=SYSTEM_PROMPT, max_tokens=2048
    )
    items = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise LLMError("réponse inattendue : liste `questions` absente")
    inserted: list[dict] = []
    for item in items:
        if isinstance(item, str):
            item = {"question": item}
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question", "")).split())
        if not IDEA_LENGTH[0] <= len(question) <= IDEA_LENGTH[1]:
            continue
        key = normalize_question(question)
        if is_duplicate(key, existing_keys):
            continue
        angle = item.get("angle")
        topic_id = add_topic(
            conn, product, question, angle if angle in ANGLES else None, source="llm"
        )
        if topic_id is None:
            continue
        existing_keys.append(key)
        inserted.append({"id": topic_id, "question": question, "angle": angle})
        if len(inserted) >= count:
            break
    return inserted
