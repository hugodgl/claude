"""Brouillon du numéro : sélection diversifiée, 3 appels LLM courts, rendu markdown/HTML/texte."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from core.llm import LLM, LLMError, complete_json

from . import db
from .cases import UseCase, load_cases, pick_case
from .prompts import item_block, system_prompt
from .render import date_fr, render_markdown, write_issue_files
from .selection import min_published_iso, select_diverse
from .settings import Settings

log = logging.getLogger(__name__)


@dataclass
class DraftResult:
    number: int
    issue_date: date
    title: str
    paths: dict[str, Path]
    item_ids: list[int]
    used_item_ids: list[int]
    case_slug: str
    warnings: list[str] = field(default_factory=list)


def next_tuesday(today: date | None = None) -> date:
    """Premier mardi strictement après aujourd'hui (le lundi donne le lendemain)."""
    today = today or datetime.now(UTC).date()
    days = (1 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def load_sponsor(path: Path, issue_date: date) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("name"):
        return None
    start, end = data.get("from"), data.get("until")
    if start and issue_date < (start if isinstance(start, date) else date.fromisoformat(str(start))):
        return None
    if end and issue_date > (end if isinstance(end, date) else date.fromisoformat(str(end))):
        return None
    return {"name": str(data["name"]), "tagline": str(data.get("tagline") or ""),
            "url": str(data.get("url") or ""), "mention": str(data.get("mention") or "Partenaire de ce numéro")}


def _score_json(item: sqlite3.Row) -> dict[str, Any]:
    try:
        return json.loads(item["score_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _items_prompt(items: list[sqlite3.Row], settings: Settings, max_chars: int = 900) -> str:
    blocks = []
    for item in items:
        sj = _score_json(item)
        body = "\n".join(filter(None, [
            f"Résumé : {sj.get('resume_1_phrase', '')}" if sj.get("resume_1_phrase") else None,
            f"Pourquoi ça compte : {sj.get('pourquoi_ca_compte', '')}" if sj.get("pourquoi_ca_compte") else None,
            f"Extrait : {(item['content_text'] or item['summary'] or '')}",
        ]))
        blocks.append(item_block(
            item["id"],
            {"source": item["source_name"], "date": item["published_at"], "theme": item["theme"],
             "titre": item["title"], "url": item["url"]},
            body, max_chars,
        ))
    return "\n\n".join(blocks)


class Drafter:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, llm: LLM):
        self.conn, self.settings, self.llm = conn, settings, llm
        self.system = system_prompt(settings)

    # ------------------------------------------------------------------ LLM
    def _ask(self, task: str, prompt: str, max_tokens: int) -> dict[str, Any] | None:
        try:
            data = complete_json(self.llm, f"Tâche : {task}\n\n{prompt}", system=self.system,
                                 max_tokens=max_tokens)
        except LLMError as exc:
            log.warning("appel LLM « %s » en échec : %s", task, exc)
            return None
        return data if isinstance(data, dict) else None

    def _news(self, items: list[sqlite3.Row]) -> tuple[list[dict[str, Any]], list[str]]:
        by_id = {i["id"]: i for i in items}
        warnings: list[str] = []
        prompt = (
            "Voici les items retenus cette semaine. Choisis les 3 plus utiles pour un cabinet (3 thèmes "
            "différents si possible) et rédige pour chacun :\n"
            "- \"item_id\" : l'id de l'item ;\n"
            "- \"titre\" : 12 mots maximum, informatif, sans point d'exclamation ;\n"
            "- \"corps\" : exactement 3 phrases factuelles, fondées uniquement sur l'item ;\n"
            "- \"ce_que_ca_change\" : 1 à 2 phrases concrètes pour un cabinet de 2 à 50 personnes.\n"
            'Réponds {"actualites": [{"item_id": 0, "titre": "", "corps": "", "ce_que_ca_change": ""}, ...]}\n\n'
            + _items_prompt(items, self.settings)
        )
        data = self._ask("actualites", prompt, 1200) or {}
        news: list[dict[str, Any]] = []
        seen: set[int] = set()
        for raw in data.get("actualites") or []:
            if not isinstance(raw, dict):
                continue
            try:
                item_id = int(raw.get("item_id"))
            except (TypeError, ValueError):
                continue
            if item_id not in by_id or item_id in seen:
                continue
            item = by_id[item_id]
            news.append({
                "item_id": item_id, "titre": str(raw.get("titre") or item["title"]).strip(),
                "corps": str(raw.get("corps") or "").strip(),
                "ce_que_ca_change": str(raw.get("ce_que_ca_change") or "").strip(),
                "source": item["source_name"], "url": item["url"], "theme": item["theme"],
            })
            seen.add(item_id)
            if len(news) == 3:
                break
        if len(news) < 3:
            warnings.append(f"le modèle n'a rendu que {len(news)} actualité(s) : "
                            "complété avec les résumés de classement")
            for item in items:
                if len(news) == 3:
                    break
                if item["id"] in seen:
                    continue
                sj = _score_json(item)
                news.append({
                    "item_id": item["id"], "titre": item["title"],
                    "corps": f"[À RELIRE] {sj.get('resume_1_phrase') or (item['summary'] or '')[:300]}",
                    "ce_que_ca_change": sj.get("pourquoi_ca_compte") or "[À COMPLÉTER]",
                    "source": item["source_name"], "url": item["url"], "theme": item["theme"],
                })
                seen.add(item["id"])
        return news, warnings

    def _extras(self, items: list[sqlite3.Row]) -> tuple[dict | None, dict | None, list[str]]:
        if not items:
            return None, None, ["aucun item disponible pour le chiffre et l'outil"]
        by_id = {i["id"]: i for i in items}
        prompt = (
            "À partir des items ci-dessous, propose :\n"
            "- \"chiffre\" : UN chiffre sourcé présent textuellement dans un item (pourcentage, montant, "
            "nombre), avec \"item_id\", \"valeur\" (ex. « 60 % ») et \"phrase\" (une phrase de contexte) ; "
            "null si aucun item ne contient de chiffre fiable ;\n"
            "- \"outil\" : UN outil ou une fonctionnalité concrète décrite dans un item, avec \"item_id\", "
            "\"nom\", \"usage\" (ce qu'il fait, pour qui), \"verdict\" (une phrase, prudente : non testé par "
            "nous sauf mention contraire) et \"limite\" (une phrase) ; null si rien ne convient.\n"
            'Réponds {"chiffre": {...} | null, "outil": {...} | null}\n\n' + _items_prompt(items, self.settings)
        )
        data = self._ask("chiffre_outil", prompt, 700) or {}
        warnings: list[str] = []
        chiffre = outil = None
        raw = data.get("chiffre")
        if isinstance(raw, dict) and raw.get("valeur"):
            try:
                item = by_id.get(int(raw.get("item_id")))
            except (TypeError, ValueError):
                item = None
            chiffre = {"valeur": str(raw["valeur"]).strip(), "phrase": str(raw.get("phrase") or "").strip(),
                       "url": item["url"] if item else "", "source": item["source_name"] if item else "",
                       "item_id": item["id"] if item else None}
            if not item:
                warnings.append("chiffre sans item identifiable : lien source à compléter")
        raw = data.get("outil")
        if isinstance(raw, dict) and raw.get("nom"):
            try:
                item = by_id.get(int(raw.get("item_id")))
            except (TypeError, ValueError):
                item = None
            outil = {"nom": str(raw["nom"]).strip(), "usage": str(raw.get("usage") or "").strip(),
                     "verdict": str(raw.get("verdict") or "").strip(), "limite": str(raw.get("limite") or "").strip(),
                     "url": item["url"] if item else "", "source": item["source_name"] if item else "",
                     "item_id": item["id"] if item else None}
        return chiffre, outil, warnings

    def _edito(self, number: int, news: list[dict], case: UseCase, chiffre: dict | None) -> dict[str, Any]:
        lines = "\n".join(f"- {n['titre']}" for n in news)
        prompt = (
            f"Numéro {number}. Actualités du numéro :\n{lines}\n"
            f"Cas d'usage du numéro : {case.title}\n"
            + (f"Chiffre : {chiffre['valeur']} — {chiffre['phrase']}\n" if chiffre else "")
            + "\nRédige :\n"
            "- \"titre_numero\" : titre du numéro, 10 mots max, concret, sans jargon ;\n"
            "- \"preheader\" : une phrase d'aperçu (15 mots max) ;\n"
            "- \"edito\" : environ 120 mots, ton personnel à la première personne, phrases courtes, un seul "
            "angle, qui relie l'actualité au quotidien d'un cabinet ; c'est un premier jet que l'auteur réécrira ;\n"
            "- \"intro_cas\" : 1 à 2 phrases qui introduisent le cas d'usage.\n"
            'Réponds {"titre_numero": "", "preheader": "", "edito": "", "intro_cas": ""}'
        )
        data = self._ask("edito", prompt, 700) or {}
        fallback_title = f"{self.settings.newsletter_name} n° {number}"
        if news:
            fallback_title += f" — {news[0]['titre']}"
        return {
            "title": str(data.get("titre_numero") or fallback_title).strip(),
            "preheader": str(data.get("preheader") or "").strip(),
            "edito": str(data.get("edito") or "[ÉDITO À ÉCRIRE]").strip(),
            "intro_cas": str(data.get("intro_cas") or "").strip(),
        }

    # ------------------------------------------------------------------ pipeline
    def run(self, number: int, issue_date: date | None = None, *, force_case: str | None = None,
            force: bool = False) -> DraftResult:
        s = self.settings
        issue_date = issue_date or next_tuesday()
        existing = db.get_issue(self.conn, number)
        if existing and not force:
            raise FileExistsError(
                f"le numéro {number} existe déjà ({existing['md_path']}) : utilise --force pour le regénérer"
            )
        if existing and force:
            with self.conn:
                self.conn.execute(
                    "UPDATE items SET status = 'new', used_in_issue = NULL WHERE used_in_issue = ?", (number,)
                )
        rows = db.candidate_items(self.conn, min_published=min_published_iso(s.max_item_age_days, issue_date))
        if not rows:
            raise RuntimeError("aucun item classé disponible : lance `np collect` puis `np rank`")
        selected = select_diverse(rows, limit=s.issue_items, max_per_theme=s.max_per_theme,
                                  max_per_source=s.max_per_source)
        ids = [r["id"] for r in selected]
        db.set_items_status(self.conn, ids, "selected")
        warnings: list[str] = []
        if len(selected) < s.issue_items:
            warnings.append(f"seulement {len(selected)} items disponibles (cible {s.issue_items})")

        recent = [r["case_slug"] for r in db.list_issues(self.conn) if r["case_slug"]][-3:]
        cases = load_cases(s.cases_dir)
        case = pick_case(cases, issue_number=number, themes=[r["theme"] for r in selected],
                         recent_slugs=recent, forced_slug=force_case)

        news, w = self._news(selected)
        warnings += w
        used = {n["item_id"] for n in news}
        remaining = [r for r in selected if r["id"] not in used] or selected
        chiffre, outil, w = self._extras(remaining)
        warnings += w
        for extra in (chiffre, outil):
            if extra and extra.get("item_id"):
                used.add(extra["item_id"])
        head = self._edito(number, news, case, chiffre)
        sponsor = load_sponsor(s.sponsor_file, issue_date)

        context: dict[str, Any] = {
            "number": number, "issue_date": issue_date.isoformat(), "date_fr": date_fr(issue_date),
            "newsletter_name": s.newsletter_name, "newsletter_tagline": s.newsletter_tagline,
            "author_name": s.author_name, "author_signature": s.author_signature,
            "reply_to_email": s.reply_to_email, "archive_url": s.archive_url, "sponsor": sponsor,
            "title": head["title"], "preheader": head["preheader"], "edito": head["edito"],
            "intro_cas": head["intro_cas"], "actualites": news, "chiffre": chiffre, "outil": outil,
            "case": {"slug": case.slug, "title": case.title, "body": case.body},
        }
        md_text = render_markdown(context)
        paths = write_issue_files(s.issues_dir, number, issue_date, md_text, context)
        used_ids = [i for i in ids if i in used]
        db.set_items_status(self.conn, used_ids, "used", issue_number=number)
        db.set_items_status(self.conn, [i for i in ids if i not in used], "new")
        stored = {k: v for k, v in context.items() if k != "case"} | {"case": {"slug": case.slug, "title": case.title}}
        db.save_issue(self.conn, number, issue_date=issue_date.isoformat(), title=head["title"],
                      case_slug=case.slug, md_path=str(paths["md"]), html_path=str(paths["html"]),
                      txt_path=str(paths["txt"]), item_ids=used_ids, content_json=stored, status="draft")
        return DraftResult(number=number, issue_date=issue_date, title=head["title"], paths=paths,
                           item_ids=ids, used_item_ids=used_ids, case_slug=case.slug, warnings=warnings)


def issue_meta(settings: Settings, issue: sqlite3.Row) -> dict[str, Any]:
    """Contexte minimal pour re-rendre le HTML depuis le markdown relu."""
    content = json.loads(issue["content_json"] or "{}")
    d = date.fromisoformat(issue["issue_date"])
    return {
        "number": issue["number"], "date_fr": date_fr(d), "title": issue["title"],
        "preheader": content.get("preheader", ""), "newsletter_name": settings.newsletter_name,
        "newsletter_tagline": settings.newsletter_tagline, "archive_url": settings.archive_url,
    }
