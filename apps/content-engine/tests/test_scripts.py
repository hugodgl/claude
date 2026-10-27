import json

import pytest
from core.llm import LLMError, MockLLM

from content_engine.scripts import (
    check_payload,
    draft_payload,
    estimate_duration_s,
    generate_scripts,
    get_draft,
    list_drafts,
    narration_text,
)
from content_engine.topics import get_topic

VALID = {
    "hook": "Accroche courte.",
    "body": ["Une phrase.", "Deux phrases."],
    "cta": "Lien en bio.",
    "title": "Titre",
    "description": "Desc.",
    "hashtags": ["#A", "b c"],
    "duration_s": "20",
}


def test_generate_three_variants(conn, llm):
    ids = generate_scripts(conn, llm, 1, "short")
    assert len(ids) == 3
    rows = [get_draft(conn, i) for i in ids]
    assert [r["variant"] for r in rows] == [1, 2, 3]
    assert all(r["status"] == "draft" and r["format"] == "short" for r in rows)
    payload = draft_payload(rows[0])
    for key in ("hook", "body", "cta", "title", "description", "hashtags", "duration_s", "checks"):
        assert key in payload
    assert payload["checks"]["estimated_duration_s"] <= 45 and payload["checks"]["warnings"] == []
    assert get_topic(conn, 1)["status"] == "used"
    assert len(llm.calls) == 3
    assert "Français uniquement" in llm.calls[0]["system"]
    assert "Variante 2" in llm.calls[1]["prompt"] and "Format : short" in llm.calls[1]["prompt"]
    assert "Comment demander un avis Google" in llm.calls[0]["prompt"]


@pytest.mark.parametrize("fmt", ["long", "linkedin", "pin"])
def test_other_formats_pass_their_checks(conn, llm, fmt):
    draft_id = generate_scripts(conn, llm, 16, fmt)[0]
    p = draft_payload(get_draft(conn, draft_id))
    assert p["checks"]["warnings"] == []
    if fmt == "long":
        assert len(p["body"]) == 5
    if fmt == "linkedin":
        assert 150 <= p["checks"]["word_count"] <= 220
    if fmt == "pin":
        assert len(p["title"]) <= 100 and len(p["description"]) <= 500


def test_check_payload_flags_risky_numbers_and_english():
    p = dict(VALID, body=["Tu gagnes 80 % de clients en plus."], hashtags=["x"])
    warnings = check_payload(p, "short")["warnings"]
    assert any("Source" in w for w in warnings)
    p["description"] = "Source : enquête publique 2025."
    assert not any("Source" in w for w in check_payload(p, "short")["warnings"])
    p = dict(VALID, body=["Grow your business with reviews."], hashtags=["x"])
    assert any("anglais" in w for w in check_payload(p, "short")["warnings"])
    p = dict(VALID, body=["Partie 1 — ok : phrase."] * 4, hashtags=[])
    warnings = check_payload(p, "long")["warnings"]
    assert any("5 parties" in w for w in warnings) and any("hashtag" in w for w in warnings)


def test_schema_retry_then_failure(conn):
    llm = MockLLM(['{"hook": "trop court"}', json.dumps(VALID)])
    ids = generate_scripts(conn, llm, 2, "short", variants=1)
    p = draft_payload(get_draft(conn, ids[0]))
    assert p["hashtags"] == ["a", "bc"] and p["duration_s"] == 20
    assert len(llm.calls) == 2 and "schéma" in llm.calls[1]["prompt"]
    with pytest.raises(LLMError):
        generate_scripts(conn, MockLLM("{}"), 3, "short", variants=1)
    assert list_drafts(conn, fmt="short", status="draft")[-1]["topic_id"] == 2


def test_estimate_duration_and_narration():
    text = narration_text(VALID)
    assert text.startswith("Accroche courte.") and text.endswith("Lien en bio.")
    assert 2.0 < estimate_duration_s(text) < 6.0
    assert estimate_duration_s(" ".join(["mot"] * 130)) > 45
