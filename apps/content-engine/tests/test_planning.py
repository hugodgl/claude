from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from content_engine.planning import (
    build_plan,
    candidate_draft,
    choose_formats,
    due_slots,
    list_schedule,
    run_daily,
    run_publish,
    save_plan,
)
from content_engine.scripts import list_drafts
from content_engine.topics import count_topics
from tests.conftest import fake_render, make_draft

MONDAY = date(2026, 10, 26)
PARIS = ZoneInfo("Europe/Paris")


def test_build_plan_follows_cadence():
    slots = build_plan(MONDAY, 7)
    counts = Counter((s.platform, s.format) for s in slots)
    assert counts[("youtube", "short")] == 7 and counts[("tiktok", "short")] == 7
    assert counts[("pinterest", "pin")] == 35 and counts[("linkedin", "linkedin")] == 3
    assert counts[("youtube", "long")] == 1
    assert {s.product for s in slots if s.platform == "linkedin"} <= {"marches", "cabinets"}
    assert len({s.product for s in slots if s.platform == "pinterest"}) == 3
    assert [s.day for s in slots if s.format == "linkedin"] == [
        "2026-10-26",
        "2026-10-28",
        "2026-10-30",
    ]


def test_save_plan_is_idempotent(conn):
    slots = build_plan(MONDAY, 2)
    assert save_plan(conn, slots) == len(slots)
    assert save_plan(conn, slots) == 0
    assert len(list_schedule(conn, "2026-10-26", "2026-10-26")) == 8


def test_run_publish_dry_run_assigns_ready_drafts(conn, llm, settings):
    save_plan(conn, build_plan(MONDAY, 1))
    short = make_draft(conn, llm, topic_id=1, status="rendered")
    fake_render(settings, short)
    pin = make_draft(conn, llm, topic_id=30, fmt="pin", status="rendered")
    fake_render(settings, pin, fmt="pin")
    post = make_draft(conn, llm, topic_id=16, fmt="linkedin", status="approved")
    now = datetime(2026, 10, 26, 12, 30, tzinfo=PARIS)
    assert len(due_slots(conn, now)) == 4  # linkedin 08:30, pins 09:00 et 11:00, short 12:00
    report = run_publish(conn, settings, now=now, render_missing=False)
    published = {(p["platform"], p["draft_id"]) for p in report["published"]}
    assert published == {("linkedin", post), ("pinterest", pin), ("youtube", short)}
    assert all(p["dry_run"] for p in report["published"])
    assert len(report["waiting"]) == 1  # second pin : les variantes 2 et 3 ne sont pas rendues
    rows = list_schedule(conn, status="published")
    assert len(rows) == 3 and all("dry-run" in r["note"] for r in rows)
    assert (settings.out_dir / str(short) / "publish-youtube.json").exists()
    # le même short n'est pas réutilisé pour youtube, mais reste disponible pour tiktok
    assert (
        candidate_draft(conn, {"platform": "youtube", "format": "short", "product": "avis"}) is None
    )
    assert (
        candidate_draft(conn, {"platform": "tiktok", "format": "short", "product": "avis"})["id"]
        == short
    )
    later = run_publish(
        conn, settings, now=datetime(2026, 10, 28, 9, 0, tzinfo=PARIS), render_missing=False
    )
    assert later["skipped"] and all("24 h" in s["note"] for s in later["skipped"])
    assert list_schedule(conn, status="skipped")


def test_choose_formats_caps():
    deficits = {"short": 0, "long": 3, "linkedin": 5, "pin": 40}
    assert choose_formats(deficits, 5) == ["short", "short", "pin", "pin", "linkedin"]
    assert choose_formats({"short": 0, "long": 0, "linkedin": 0, "pin": 0}, 3) == ["short"] * 3


def test_run_daily_fills_bank_and_scripts(conn, llm, settings):
    save_plan(conn, build_plan(MONDAY, 7))
    report = run_daily(conn, settings, llm, today=MONDAY, scripts_per_day=5)
    assert set(report["ideas"]) == {"avis", "marches", "cabinets"}
    assert all(count_topics(conn, p, "new") >= 15 for p in ("avis", "marches", "cabinets"))
    assert len(report["scripts"]) == 5 and report["errors"] == []
    formats = [s["format"] for s in report["scripts"]]
    assert formats.count("short") >= 2 and formats.count("pin") <= 2
    assert len(list_drafts(conn, status="draft")) == 15
    assert report["review_file"].endswith("review-2026-10-26.md")
