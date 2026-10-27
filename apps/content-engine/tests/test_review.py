from datetime import date

import pytest

from content_engine.review import approve, export_review, pending_drafts, reject, review_table
from content_engine.scripts import get_draft, set_draft_status
from tests.conftest import make_draft


def test_review_queue_approve_reject_export(conn, llm, settings):
    first = make_draft(conn, llm, topic_id=1)
    make_draft(conn, llm, topic_id=16, fmt="linkedin")
    assert len(pending_drafts(conn)) == 6
    assert approve(conn, first)["status"] == "approved"
    reject(conn, first + 1, "trop générique")
    assert get_draft(conn, first + 1)["reject_reason"] == "trop générique"
    assert len(pending_drafts(conn)) == 4
    with pytest.raises(ValueError):
        approve(conn, first)  # déjà approuvé
    set_draft_status(conn, first, "published")
    with pytest.raises(ValueError):
        reject(conn, first, "x")
    path = export_review(conn, settings.out_dir, date(2026, 10, 28))
    assert path.name == "review-2026-10-28.md"
    text = path.read_text(encoding="utf-8")
    assert "4 brouillon(s) en attente" in text
    assert f"## #{first + 2}" in text and f"ce approve {first + 2}" in text
    assert "## #1 " not in text.split("---")[1] if first != 1 else True
    table = review_table(pending_drafts(conn))
    assert table.row_count == 4


def test_export_review_without_drafts(conn, settings):
    text = export_review(conn, settings.out_dir).read_text(encoding="utf-8")
    assert "Aucun brouillon" in text and "rien à approuver" in text
