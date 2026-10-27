import pytest

from newsletter_pipeline.cases import load_cases, pick_case
from newsletter_pipeline.settings import APP_ROOT


def test_library_has_six_cases_with_prompts():
    cases = load_cases(APP_ROOT / "cases")
    assert len(cases) == 6
    assert len({c.slug for c in cases}) == 6
    assert {"relance-pieces-manquantes", "lettre-de-mission", "bilan-commente", "veille-client-sectorielle",
            "questions-recurrentes-clients", "tri-emails-cabinet"} == {c.slug for c in cases}
    for c in cases:
        assert c.title and c.themes and "```" in c.body and "prêt à copier" in c.body


def test_pick_case_prefers_week_themes_and_rotates():
    cases = load_cases(APP_ROOT / "cases")
    assert pick_case(cases, issue_number=1, themes=["recrutement", "social", "fiscal"]).slug == "veille-client-sectorielle"
    assert pick_case(cases, issue_number=1, themes=["tenue", "tenue"]).slug == "relance-pieces-manquantes"
    assert pick_case(cases, issue_number=1, themes=["tenue"], recent_slugs=["relance-pieces-manquantes"]).slug == "tri-emails-cabinet"
    first = pick_case(cases, issue_number=1, themes=[]).slug
    second = pick_case(cases, issue_number=2, themes=[]).slug
    assert first != second
    assert pick_case(cases, issue_number=9, forced_slug="bilan-commente").slug == "bilan-commente"
    with pytest.raises(LookupError):
        pick_case(cases, issue_number=1, forced_slug="inconnu")


def test_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path)
