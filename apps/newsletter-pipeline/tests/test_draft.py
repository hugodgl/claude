import json
import re
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
    assert re.search(r"\*\*\d+ %\*\* — ", md) and "Pré-saisie photo" in md and "[À VÉRIFIER]" not in md
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
    assert len(content["actualites"]) == 3 and re.fullmatch(r"\d+ %", content["chiffre"]["valeur"])
    cited = db.get_items(conn, [content["chiffre"]["item_id"]])[0]
    assert content["chiffre"]["valeur"] in (cited["content_text"] or cited["summary"])  # chiffre pris dans l'item cité
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


def _llm_with(actualites=None, chiffre_outil=None, edito=None):
    """LLM scripté dont on remplace certaines réponses (les autres viennent de conftest)."""
    from conftest import scripted_response

    def respond(prompt, system):
        if prompt.startswith("Tâche : actualites") and actualites:
            return actualites(prompt)
        if prompt.startswith("Tâche : chiffre_outil") and chiffre_outil:
            return chiffre_outil(prompt)
        if prompt.startswith("Tâche : edito") and edito:
            return edito(prompt)
        return scripted_response(prompt, system)

    from core.llm import MockLLM
    return MockLLM(respond)


def test_draft_strips_urls_invented_by_llm(conn, settings, ranked):
    import re

    def actualites(prompt):
        ids = [int(m) for m in re.findall(r'<item id="(\d+)"', prompt)]
        urls = re.findall(r'url="([^"]+)"', prompt)
        return json.dumps({"actualites": [
            {"item_id": ids[0], "titre": "Titre\navec retour [doc](https://invente.test/doc)",
             "corps": f"Voir [la source]({urls[0]}) et aussi https://invente.test/x. Fin.",
             "ce_que_ca_change": "Lire ![pixel](https://invente.test/p.gif) puis [guide](mailto:x@y.fr)."},
            {"item_id": ids[1], "titre": "B", "corps": "b", "ce_que_ca_change": "b"},
            {"item_id": ids[2], "titre": "C", "corps": "c", "ce_que_ca_change": "c"}]})

    def edito(prompt):
        return json.dumps({"titre_numero": "Titre <b>numéro</b>", "preheader": "Aperçu https://invente.test/ok",
                           "edito": "Édito avec https://invente.test/e, c'est tout.", "intro_cas": "Intro."})

    result = Drafter(conn, settings, _llm_with(actualites=actualites, edito=edito)).run(1, date(2026, 11, 3))
    md = result.paths["md"].read_text(encoding="utf-8")
    assert "invente.test" not in md
    assert "### 1. Titre avec retour doc\n" in md  # titre sur une ligne, lien inventé réduit à son libellé
    item_url = db.get_items(conn, [result.used_item_ids[0]])[0]["url"]
    assert f"Voir [la source]({item_url}) et aussi [LIEN À VÉRIFIER]. Fin." in md  # l'URL d'un item sélectionné reste
    assert "Lire pixel puis guide." in md
    assert "Édito avec [LIEN À VÉRIFIER], c'est tout." in md
    assert any("lien" in w and "retiré" in w for w in result.warnings)


def test_draft_flags_unverifiable_number_and_missing_source(conn, settings, ranked):
    def wrong_number(prompt):
        import re
        ids = [int(m) for m in re.findall(r'<item id="(\d+)"', prompt)]
        return json.dumps({"chiffre": {"item_id": ids[0], "valeur": "99,5 %", "phrase": "des cabinets, dit-on."},
                           "outil": {"item_id": 424242, "nom": "Outil fantôme", "usage": "u", "verdict": "v", "limite": "l"}})

    result = Drafter(conn, settings, _llm_with(chiffre_outil=wrong_number)).run(1, date(2026, 11, 3))
    md = result.paths["md"].read_text(encoding="utf-8")
    assert "**99,5 %** — [À VÉRIFIER] des cabinets, dit-on." in md
    assert any("99,5 %" in w and "n'apparaît pas" in w for w in result.warnings)
    assert "**Outil fantôme**" in md and "Source : [SOURCE À VÉRIFIER]" in md

    def no_item(prompt):
        return json.dumps({"chiffre": {"valeur": "12 000", "phrase": "cabinets concernés."}, "outil": None})

    result = Drafter(conn, settings, _llm_with(chiffre_outil=no_item)).run(2, date(2026, 11, 10))
    md = result.paths["md"].read_text(encoding="utf-8")
    assert "**12 000** — cabinets concernés. [SOURCE À VÉRIFIER]" in md and "]()" not in md
    assert any("sans item identifiable" in w for w in result.warnings)


def test_number_in_item():
    from newsletter_pipeline.draft import number_in_item
    item = {"title": "Baromètre : 60 % des cabinets", "summary": "1 200 professionnels, contre 38 % l'an dernier.",
            "content_text": None}
    assert number_in_item("60 %", item) and number_in_item("1 200", item) and number_in_item("de 38 % à 60 %", item)
    assert not number_in_item("61 %", item) and not number_in_item("deux heures", item)


def test_load_sponsor_tolerates_datetime_and_rejects_bad_dates(workdir):
    p = workdir / "sponsor.yaml"
    p.write_text("name: S\nfrom: 2026-11-01 07:00:00\nuntil: '2026-11-30'\n", encoding="utf-8")
    assert load_sponsor(p, date(2026, 11, 15))["name"] == "S"
    assert load_sponsor(p, date(2026, 12, 1)) is None
    p.write_text("name: S\nfrom: 01/11/2026\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sponsor.yaml.*from"):
        load_sponsor(p, date(2026, 11, 15))
    p.write_text("- pas un mapping\n", encoding="utf-8")
    assert load_sponsor(p, date(2026, 11, 15)) is None


def test_sponsor_mention_is_used_in_markdown(conn, settings, llm, ranked):
    settings.sponsor_file.write_text("name: S\nurl: https://s.fr\ntagline: t\nmention: Avec le soutien de\n", encoding="utf-8")
    result = Drafter(conn, settings, llm).run(1, date(2026, 11, 3))
    md = result.paths["md"].read_text(encoding="utf-8")
    assert "> **Avec le soutien de :** [S](https://s.fr) — t *(contenu sponsorisé)*" in md
    from newsletter_pipeline.render import preheader_from_markdown
    assert preheader_from_markdown(md) == "Un assistant, un décret, un chiffre."  # l'encadré sponsor n'est pas l'aperçu
    md_without = md.replace("> Un assistant, un décret, un chiffre.\n", "")
    assert preheader_from_markdown(md_without) == ""
