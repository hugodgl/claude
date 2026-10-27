"""Fixtures communes : réglages isolés dans un dossier temporaire, base SQLite, LLM scripté."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from core.llm import MockLLM

from newsletter_pipeline import db as dbmod
from newsletter_pipeline.collect import Collector
from newsletter_pipeline.draft import Drafter
from newsletter_pipeline.rank import Ranker
from newsletter_pipeline.settings import APP_ROOT, Settings

FIXTURES = Path(__file__).parent / "fixtures"


def write_sources_yaml(path: Path, *, with_broken: bool = True, extra: str = "") -> Path:
    broken = f"""
  - name: Source cassée
    url: {FIXTURES / 'inexistant.xml'}
    kind: rss
    category: presse_pro
""" if with_broken else ""
    path.write_text(f"""
defaults:
  lang: fr
  weight: 1.0
sources:
  - name: Éditeur test
    url: {FIXTURES / 'feed_editeur.xml'}
    kind: rss
    category: editeurs
    weight: 0.9
  - name: Institution test
    url: {FIXTURES / 'feed_institution.atom'}
    kind: rss
    category: institutions
    weight: 1.2
{broken}{extra}
""", encoding="utf-8")
    return path


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def settings(workdir: Path) -> Settings:
    return Settings(
        llm_provider="mock",
        data_dir=workdir / "data",
        issues_dir=workdir / "issues",
        out_dir=workdir / "out",
        sources_file=write_sources_yaml(workdir / "sources.yaml"),
        sponsor_file=workdir / "sponsor.yaml",
        cases_dir=APP_ROOT / "cases",
        style_file=APP_ROOT / "style.md",
        request_delay_s=0,
        max_item_age_days=0,
        rank_batch_size=5,
        max_per_source=4,  # deux sources seulement dans les fixtures : 4 + 4 = 8 items
        _env_file=None,
    )


@pytest.fixture
def env(settings: Settings) -> dict[str, str]:
    """Variables d'environnement équivalentes, pour les tests CLI (CliRunner)."""
    return {
        "LLM_PROVIDER": "mock",
        "DATA_DIR": str(settings.data_dir),
        "ISSUES_DIR": str(settings.issues_dir),
        "OUT_DIR": str(settings.out_dir),
        "SOURCES_FILE": str(settings.sources_file),
        "SPONSOR_FILE": str(settings.sponsor_file),
        "REQUEST_DELAY_S": "0",
        "MAX_ITEM_AGE_DAYS": "0",
        "RANK_BATCH_SIZE": "5",
        "MAX_PER_SOURCE": "4",
    }


@pytest.fixture
def conn(settings: Settings):
    c = dbmod.open_db(settings)
    yield c
    c.close()


# ------------------------------------------------------------------ LLM scripté
_ITEM_RE = re.compile(r'<item id="(\d+)"([^>]*)>')
_TITLE_RE = re.compile(r'titre="([^"]*)"')

THEME_KEYWORDS = [
    ("tva", "fiscal"), ("fiscal", "fiscal"), ("paie", "social"), ("urssaf", "social"), ("dsn", "social"),
    ("recrut", "recrutement"), ("candidat", "recrutement"), ("factur", "tenue"), ("notes de frais", "tenue"),
    ("client", "relation_client"), ("outil", "outils"), ("assistant", "outils"), ("décret", "reglementation"),
    ("commentaires", "reglementation"), ("lettre de mission", "reglementation"), ("révision", "revision"),
]


def _theme_for(title: str) -> str:
    low = title.lower()
    for key, theme in THEME_KEYWORDS:
        if key in low:
            return theme
    return "ia_generale"


def _items_in(prompt: str) -> list[tuple[int, str]]:
    out = []
    for m in _ITEM_RE.finditer(prompt):
        t = _TITLE_RE.search(m.group(2))
        out.append((int(m.group(1)), t.group(1) if t else ""))
    return out


def _words(n: int) -> str:
    base = ("Chaque jeudi, un collaborateur relance les pièces manquantes. Un modèle rédige, il relit, "
            "il envoie. Vingt minutes au lieu de deux heures. ")
    words = (base * 20).split()
    return " ".join(words[:n])


def scripted_response(prompt: str, system: str | None) -> str:
    if prompt.startswith("Tâche : actualites"):
        items = _items_in(prompt)[:3]
        return json.dumps({"actualites": [
            {"item_id": i, "titre": f"Actualité {k + 1} : {title[:40]}",
             "corps": "Première phrase factuelle. Deuxième phrase factuelle. Troisième phrase factuelle.",
             "ce_que_ca_change": "Un cabinet peut tester cela sur un dossier dès cette semaine."}
            for k, (i, title) in enumerate(items)]})
    if prompt.startswith("Tâche : chiffre_outil"):
        items = _items_in(prompt)
        chiffre = {"item_id": items[0][0], "valeur": "60 %", "phrase": "des experts-comptables utilisent l'IA pour des analyses."} if items else None
        outil = {"item_id": items[1][0], "nom": "Pré-saisie photo", "usage": "lit les tickets et propose l'écriture",
                 "verdict": "Non testé par nous : à essayer sur un mois de notes de frais.",
                 "limite": "Le taux annoncé vient de l'éditeur."} if len(items) > 1 else None
        return json.dumps({"chiffre": chiffre, "outil": outil})
    if prompt.startswith("Tâche : edito"):
        return json.dumps({"titre_numero": "Relancer sans y passer le jeudi",
                           "preheader": "Un assistant, un décret, un chiffre.",
                           "edito": _words(120), "intro_cas": "Cette semaine, le prompt exact."})
    if prompt.startswith("Tâche : linkedin"):
        return json.dumps({"posts": [
            {"angle": "actualité", "texte": _words(170) + "\n\n#expertcomptable #IA"},
            {"angle": "cas d'usage", "texte": _words(160)},
            {"angle": "chiffre", "texte": _words(200)},
        ]})
    # classement
    items = _items_in(prompt)
    return json.dumps({"items": [
        {"id": i, "pertinence_cabinet": 5 + (i % 5), "nouveaute": 4 + (i % 6), "actionnable": 3 + (i % 7),
         "theme": _theme_for(title), "resume_1_phrase": f"Résumé de l'item {i}.",
         "pourquoi_ca_compte": "Conséquence concrète pour un cabinet."}
        for i, title in items]})


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM(responses=scripted_response)


# ------------------------------------------------------------------ pipeline prêt à l'emploi
@pytest.fixture
def collected(conn, settings):
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    return collector.run()


@pytest.fixture
def ranked(conn, settings, llm, collected):
    return Ranker(conn, settings, llm).run()


@pytest.fixture
def drafted(conn, settings, llm, ranked):
    from datetime import date
    return Drafter(conn, settings, llm).run(1, date(2026, 11, 3))
