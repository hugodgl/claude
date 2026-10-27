"""Extraction de 3 posts LinkedIn à partir du numéro relu (markdown)."""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.llm import LLM, LLMError, complete_json

from . import db
from .prompts import item_block, system_prompt
from .settings import Settings

log = logging.getLogger(__name__)

MIN_WORDS, MAX_WORDS = 150, 220
MAX_HASHTAGS = 3

INSTRUCTIONS = (
    "À partir du numéro ci-dessous, écris 3 posts LinkedIn en français, destinés aux experts-comptables "
    "et chefs de mission. Contraintes strictes pour chaque post :\n"
    f"- entre {MIN_WORDS} et {MAX_WORDS} mots ;\n"
    "- UN seul message par post (une actualité, le cas d'usage, ou le chiffre) ; les trois posts ne se "
    "répètent pas ;\n"
    "- la première ligne est un crochet : une phrase courte, concrète, sans « Découvrez » ni question "
    "rhétorique creuse ; puis des paragraphes courts, une idée par ligne ;\n"
    "- pas de lien dans le texte (il ira en premier commentaire) ; termine par une phrase qui invite "
    "à s'abonner à la newsletter, sans insistance ;\n"
    f"- au plus {MAX_HASHTAGS} hashtags, à la toute fin, pas d'émojis en rafale ;\n"
    "- aucun fait qui ne figure pas dans le numéro ; pas de conseil fiscal personnalisé.\n"
    'Réponds {"posts": [{"angle": "actualité | cas d\'usage | chiffre", "texte": "..."}, ...]}'
)


@dataclass
class LinkedInResult:
    number: int
    path: Path
    posts: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def hashtag_count(text: str) -> int:
    return len(re.findall(r"(?<!\w)#\w+", text or ""))


def parse_posts(data: Any) -> list[dict[str, Any]]:
    rows = data.get("posts") if isinstance(data, dict) else data
    posts: list[dict[str, Any]] = []
    for raw in rows or []:
        if isinstance(raw, dict) and raw.get("texte"):
            posts.append({"angle": str(raw.get("angle") or "").strip(), "texte": str(raw["texte"]).strip()})
        elif isinstance(raw, str) and raw.strip():
            posts.append({"angle": "", "texte": raw.strip()})
    return posts[:3]


def check_posts(posts: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for i, post in enumerate(posts, 1):
        n = word_count(post["texte"])
        if not MIN_WORDS <= n <= MAX_WORDS:
            problems.append(f"post {i} : {n} mots (attendu {MIN_WORDS}-{MAX_WORDS})")
        if hashtag_count(post["texte"]) > MAX_HASHTAGS:
            problems.append(f"post {i} : trop de hashtags")
        if re.search(r"https?://", post["texte"]):
            problems.append(f"post {i} : contient un lien (à mettre en commentaire)")
    if len(posts) < 3:
        problems.append(f"seulement {len(posts)} post(s) rendus")
    return problems


def build_prompt(md_text: str, number: int, max_chars: int = 16000) -> str:
    """Le numéro entier (un numéro fait 6 000 à 10 000 caractères avec le cas d'usage) ; la borne ne
    sert qu'à protéger le modèle local d'un markdown anormalement long."""
    return f"Tâche : linkedin\n\n{INSTRUCTIONS}\n\n" + item_block(
        f"numero-{number}", {"type": "numero de newsletter"}, md_text, max_chars)


def generate_linkedin_posts(conn: sqlite3.Connection, settings: Settings, llm: LLM, number: int) -> LinkedInResult:
    issue = db.get_issue(conn, number)
    if issue is None:
        raise LookupError(f"numéro {number} introuvable : lance d'abord `np draft --issue {number}`")
    md_path = Path(issue["md_path"])
    if not md_path.exists():
        raise FileNotFoundError(f"fichier markdown absent : {md_path} (relance `np draft --issue {number} --force`)")
    md_text = md_path.read_text(encoding="utf-8")
    system = system_prompt(settings)
    prompt = build_prompt(md_text, number)
    warnings: list[str] = []
    posts: list[dict[str, Any]] = []
    for attempt in range(2):
        try:
            data = complete_json(llm, prompt, system=system, max_tokens=1600)
        except LLMError as exc:
            raise RuntimeError(f"génération LinkedIn impossible : {exc}") from exc
        posts = parse_posts(data)
        problems = check_posts(posts)
        if not problems:
            break
        if attempt == 0:
            prompt += ("\n\nTa réponse précédente ne respectait pas les contraintes : " + " ; ".join(problems)
                       + ". Corrige et renvoie les 3 posts complets.")
        else:
            warnings += problems
    out_dir = Path(settings.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"linkedin-{number:03d}.md"
    lines = [f"# Posts LinkedIn — {settings.newsletter_name} n° {number}", "",
             f"Tirés de : {issue['md_path']}. Le lien vers le numéro va en premier commentaire.", ""]
    for i, post in enumerate(posts, 1):
        lines += [f"## Post {i}" + (f" — {post['angle']}" if post["angle"] else "") +
                  f" ({word_count(post['texte'])} mots)", "", post["texte"], "", "---", ""]
    if warnings:
        lines += ["## À vérifier", ""] + [f"- {w}" for w in warnings] + [""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return LinkedInResult(number=number, path=path, posts=posts, warnings=warnings)
