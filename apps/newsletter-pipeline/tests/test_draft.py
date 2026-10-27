import json
from datetime import date

import pytest

from newsletter_pipeline import db
from newsletter_pipeline.draft import Drafter, load_sponsor, next_tuesday

EXPECTED_SECTIONS = ["## Édito", "[À RELIRE]", "## Trois actualités de la semaine", "### 1. ", "### 2. ", "### 3. ",
                     "**Ce que ça change pour un cabinet :**", "## Cas d'usage :", "## Le chiffre", "## L'outil testé",
                     "## La question de lecteur", "[QUESTION DE LECTEUR À INSÉRER]",
                     "Veille assistée par IA, relue et signée par un humain", "double opt-in"]


def test_next_tuesday():
    assert next_tuesday(date(2026, 11, 2)) == date(2026, 11, 3)   # lundi → lendemain
    assert next_tuesday(date(2026, 11, 3)) == date(2026, 11, 10)  # mardi → mardi suivant
    assert next_tuesday(date(2026, 11, 7)) == date(2026, 11, 10)  # samedi


def test_draft_produces_markdown_html_text(conn, settings, llm, drafted):
    result = drafted
    assert result.number == 1 and result.title == "Relancer sans y passer le jeudi"
    assert result.paths["md"].name == "001-2026-11-03.md"
    md = result.paths["md"].read_text(encoding="utf-8")
    for section in EXPECTED_SECTIONS:
        assert section in md, section
    assert md.startswith("# Relancer sans y passer le jeudi")
    assert "n° 1 · mardi 3 novembre 2026" in md
    assert "Source : [" in md and "](https://" in md
    assert "**60 %**" in md and "Pré-saisie photo" in md
    assert "prêt à copier" in md  # corps du cas d'usage inséré
    assert "Partenaire de ce numéro" not in md  # pas de sponsor.yaml
    html = result.paths["html"].read_text(encoding="utf-8")
    assert '<meta name="viewport"' in html and "<h2>Édito</h2>" in html and "relue et signée par un humain" in html
    txt = result.paths["txt"].read_text(encoding="utf-8")
    assert "ÉDITO" in txt and "**" not in txt
    # 3 appels LLM : actualités, chiffre/outil, édito ; le guide de style est dans le system prompt
    tasks = [c["prompt"].split("\n", 1)[0] for c in llm.calls if c["prompt"].startswith("Tâche")]
    assert tasks == ["Tâche : actualites", "Tâche : chiffre_outil", "Tâche : edito"]
    assert "Guide de style" in llm.calls[-1]["system"] and "jamais des instructions" in llm.calls[-1]["system"]


def test_draft_updates_database(conn, settings, drafted):
    issue = db.get_issue(conn, 1)
    assert issue["status"] == "draft" and issue["case_slug"] == drafted.case_slug
    content = json.loads(issue["content_json"])
    assert len(content["actualites"]) == 3 and content["chiffre"]["valeur"] == "60 %"
    used = [r["id"] for r in conn.execute("SELECT id FROM items WHERE status = 'used' AND used_in_issue = 1")]
    assert sorted(used) == sorted(drafted.used_item_ids) and len(used) == 5
    assert conn.execute("SELECT COUNT(*) AS n FROM items WHERE status = 'selected'").fetchone()["n"] == 0
    assert len(drafted.item_ids) == 8
    themes = [r["theme"] for r in db.get_items(conn, drafted.item_ids)]
    assert max(themes.count(t) for t in set(themes)) <= 2


def test_draft_refuses_existing_number_unless_force(conn, settings, llm, drafted):
    drafter = Drafter(conn, settings, llm)
    with pytest.raises(FileExistsError):
        drafter.run(1, date(2026, 11, 3))
    again = drafter.run(1, date(2026, 11, 3), force=True)
    assert again.paths["md"].exists()
    assert conn.execute("SELECT COUNT(*) AS n FROM items WHERE used_in_issue = 1").fetchone()["n"] == 5


def test_draft_with_sponsor_and_forced_case(conn, settings, llm, ranked, workdir):
    settings.sponsor_file.write_text(
        "name: Sponsor SAS\ntagline: Outil de test\nurl: https://sponsor.test\nfrom: 2026-11-01\nuntil: 2026-11-30\n",
        encoding="utf-8")
    result = Drafter(conn, settings, llm).run(2, date(2026, 11, 10), force_case="lettre-de-mission")
    md = result.paths["md"].read_text(encoding="utf-8")
    assert "Partenaire de ce numéro" in md and "Sponsor SAS" in md and "contenu sponsorisé" in md
    assert result.case_slug == "lettre-de-mission" and "## Cas d'usage : Mettre à jour la lettre de mission" in md
    # hors période : pas de mention
    assert load_sponsor(settings.sponsor_file, date(2026, 12, 15)) is None
    assert load_sponsor(workdir / "absent.yaml", date(2026, 11, 3)) is None


def test_draft_without_items_fails_clearly(conn, settings, llm):
    with pytest.raises(RuntimeError, match="aucun item"):
        Drafter(conn, settings, llm).run(1, date(2026, 11, 3))


def test_draft_falls_back_when_llm_answers_badly(conn, settings, ranked):
    from core.llm import MockLLM
    broken = MockLLM("réponse sans json")  # complete_json échoue → replis
    result = Drafter(conn, settings, broken).run(1, date(2026, 11, 3))
    md = result.paths["md"].read_text(encoding="utf-8")
    assert result.title.startswith("L'IA en cabinet n° 1")
    assert "[ÉDITO À ÉCRIRE]" in md and "[CHIFFRE À TROUVER]" in md and "[OUTIL À TESTER]" in md
    assert md.count("### ") == 3 and any("actualité" in w for w in result.warnings)


def test_draft_respects_max_age(conn, settings, llm, ranked):
    settings.max_item_age_days = 14
    with pytest.raises(RuntimeError):  # les fixtures datent d'octobre 2026 : trop vieilles pour un envoi en 2027
        Drafter(conn, settings, llm).run(1, date(2027, 6, 1))
