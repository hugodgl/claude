import json

import pytest
from core.llm import MockLLM

from newsletter_pipeline.linkedin import (
    MAX_WORDS,
    MIN_WORDS,
    check_posts,
    generate_linkedin_posts,
    word_count,
)


def test_linkedin_posts_written(conn, settings, llm, drafted):
    result = generate_linkedin_posts(conn, settings, llm, 1)
    assert result.path == settings.out_dir / "linkedin-001.md" and result.path.exists()
    assert len(result.posts) == 3 and result.warnings == []
    content = result.path.read_text(encoding="utf-8")
    assert content.count("## Post ") == 3 and "premier commentaire" in content
    for post in result.posts:
        assert MIN_WORDS <= word_count(post["texte"]) <= MAX_WORDS
    call = llm.calls[-1]
    assert call["prompt"].startswith("Tâche : linkedin") and '<item id="numero-1"' in call["prompt"]
    assert "Guide de style" in call["system"]


def test_linkedin_retries_once_when_constraints_fail(conn, settings, drafted):
    short = json.dumps({"posts": [{"angle": "a", "texte": "trop court"}] * 3})
    good = json.dumps({"posts": [{"angle": "a", "texte": " ".join(["mot"] * 180)}] * 3})
    llm = MockLLM([short, good])
    result = generate_linkedin_posts(conn, settings, llm, 1)
    assert len(llm.calls) == 2 and "ne respectait pas" in llm.calls[1]["prompt"]
    assert result.warnings == [] and all(word_count(p["texte"]) == 180 for p in result.posts)


def test_linkedin_keeps_warnings_after_second_failure(conn, settings, drafted):
    bad = json.dumps({"posts": [{"angle": "a", "texte": "https://ex.fr " + " ".join(["mot"] * 300)}] * 2})
    result = generate_linkedin_posts(conn, settings, MockLLM(bad), 1)
    assert any("mots" in w for w in result.warnings) and any("lien" in w for w in result.warnings)
    assert any("seulement 2" in w for w in result.warnings)
    assert "## À vérifier" in result.path.read_text(encoding="utf-8")


def test_check_posts_rules():
    ok = " ".join(["mot"] * 160)
    assert check_posts([{"texte": ok}] * 3) == []
    problems = check_posts([{"texte": ok + " #a #b #c #d"}, {"texte": "court"}])
    assert any("hashtags" in p for p in problems) and any("post 2" in p for p in problems)


def test_linkedin_unknown_issue(conn, settings, llm):
    with pytest.raises(LookupError):
        generate_linkedin_posts(conn, settings, llm, 99)
