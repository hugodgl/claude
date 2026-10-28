from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from content_engine.planning import (
    build_plan,
    candidate_draft,
    choose_formats,
    due_slots,
    format_deficits,
    list_schedule,
    pair_topics_with_formats,
    run_daily,
    run_publish,
    save_plan,
    slot_age,
)
from content_engine.scripts import list_drafts
from content_engine.topics import count_topics, pick_topics
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


def test_live_run_publishes_drafts_only_simulated_before_and_is_idempotent(conn, llm, settings):
    settings = settings.model_copy(
        update={"linkedin_access_token": "lt", "linkedin_author_urn": "urn:li:person:1"}
    )
    save_plan(conn, build_plan(MONDAY, 3))  # LinkedIn lundi et mercredi 08:30
    post = make_draft(conn, llm, topic_id=16, fmt="linkedin", status="approved")
    dry = run_publish(conn, settings, now=datetime(2026, 10, 26, 9, 0, tzinfo=PARIS))
    assert [(p["platform"], p["draft_id"], p["dry_run"]) for p in dry["published"]] == [
        ("linkedin", post, True)
    ]
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wednesday = datetime(2026, 10, 28, 9, 0, tzinfo=PARIS)
    # passage en --live : le brouillon seulement simulé lundi est publié pour de bon
    live = run_publish(conn, settings, now=wednesday, live=True, client=client)
    assert [(p["draft_id"], p["dry_run"]) for p in live["published"]] == [(post, False)]
    assert len(calls) == 1
    # relancer ne republie rien (créneau consommé, publication réelle journalisée)
    again = run_publish(conn, settings, now=wednesday, live=True, client=client)
    assert again["published"] == [] and len(calls) == 1
    n = conn.execute(
        "SELECT COUNT(*) FROM publications WHERE draft_id = ? AND dry_run = 0", (post,)
    ).fetchone()[0]
    assert n == 1 and candidate_draft(conn, {"platform": "linkedin", "format": "linkedin",
                                             "product": "marches"}, live=True) is None


def test_run_publish_normalizes_timezone_and_gives_up_on_stale_failures(conn, llm, settings):
    save_plan(conn, build_plan(MONDAY, 1))
    # 11:30 UTC = 12:30 à Paris (heure d'hiver) : le short de 12:00 est bien échu
    rep = run_publish(conn, settings, now=datetime(2026, 10, 26, 11, 30, tzinfo=UTC))
    assert "2026-10-26T12:00" in {w["slot_at"] for w in rep["waiting"]}
    # un brouillon prêt mais une publication réelle impossible (pas de jeton) : retenté 24 h,
    # puis le créneau est abandonné avec le motif
    make_draft(conn, llm, topic_id=16, fmt="linkedin", status="approved")
    rep = run_publish(conn, settings, now=datetime(2026, 10, 26, 9, 0, tzinfo=PARIS), live=True)
    assert any("LINKEDIN_ACCESS_TOKEN" in s.get("error", "") for s in rep["skipped"])
    assert not [r for r in list_schedule(conn, status="skipped") if r["format"] == "linkedin"]
    run_publish(conn, settings, now=datetime(2026, 10, 27, 10, 0, tzinfo=PARIS), live=True)
    notes = {r["slot_at"]: r["note"] for r in list_schedule(conn, status="skipped")}
    assert "échec de publication" in notes["2026-10-26T08:30"]


def test_slot_age_counts_real_elapsed_time_across_dst_change():
    now = datetime(2026, 10, 25, 13, 30, tzinfo=PARIS)  # heure d'hiver depuis 03:00 ce jour-là
    assert slot_age(now, "2026-10-24T14:00") == timedelta(hours=24, minutes=30)  # pas 23 h 30


def test_format_deficits_ignore_consumed_drafts_and_formats_follow_products(conn, llm, settings):
    save_plan(conn, build_plan(MONDAY, 7))
    before = format_deficits(conn, MONDAY)["short"]
    short = make_draft(conn, llm, topic_id=1, status="rendered")  # 3 variantes = 1 sujet couvert
    assert format_deficits(conn, MONDAY)["short"] == before - 1
    fake_render(settings, short)
    run_publish(conn, settings, now=datetime(2026, 10, 26, 12, 30, tzinfo=PARIS))
    assert format_deficits(conn, MONDAY)["short"] == before  # la variante envoyée ne compte plus
    formats = ["short", "short", "linkedin", "pin", "long"]
    pairs = pair_topics_with_formats(pick_topics(conn, 5), formats)
    assert [f for _, f in pairs] == formats and len({t["id"] for t, _ in pairs}) == 5
    assert all(t["product"] != "avis" for t, f in pairs if f == "linkedin")
