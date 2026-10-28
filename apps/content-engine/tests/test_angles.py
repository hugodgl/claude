"""Score des angles : normalisation par plateforme et par âge, lissage bayésien (petits effectifs),
pause / réactivation, sélection exploitation / exploration dans `run-daily`."""

import json
import math
from datetime import UTC, datetime, timedelta

from content_engine.angles import (
    MIN_AGE_DAYS,
    age_factor,
    angle_scores,
    content_scores,
    pause_margin,
    paused_angles,
    set_angle_status,
    shrink,
    strong_angles,
    update_angle_status,
)
from content_engine.planning import run_daily
from content_engine.topics import add_topic, pick_topics, select_topics

NOW = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
_counter = {"n": 0}


def measured(conn, product, angle, platform, views, *, age_days=30.0, measured_at=NOW):
    """Un contenu mesuré : sujet (consommé) → brouillon publié → publication réelle → relevé."""
    _counter["n"] += 1
    n = _counter["n"]
    topic_id = add_topic(conn, product, f"Question mesurée numéro {n} ?", angle, source="manual")
    payload = {"hook": "a", "body": ["b"], "cta": "c", "title": f"Titre {n}", "hashtags": []}
    with conn:
        conn.execute("UPDATE topics SET status = 'used' WHERE id = ?", (topic_id,))
        cur = conn.execute(
            "INSERT INTO drafts (topic_id, format, variant, payload_json, status, created_at) "
            "VALUES (?, 'short', 1, ?, 'published', ?)",
            (topic_id, json.dumps(payload), NOW.isoformat()),
        )
        draft_id = int(cur.lastrowid)
        published_at = (measured_at - timedelta(days=age_days)).isoformat()
        conn.execute(
            "INSERT INTO publications (draft_id, platform, dry_run, remote_id, published_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (draft_id, platform, f"r{draft_id}", published_at),
        )
        conn.execute(
            "INSERT INTO metrics (platform, remote_id, draft_id, views, imported_at, "
            "measured_at, source) VALUES (?, ?, ?, ?, ?, ?, 'api')",
            (
                platform,
                f"r{draft_id}",
                draft_id,
                views,
                measured_at.isoformat(),
                measured_at.isoformat(),
            ),
        )
    return draft_id


def by_angle(scores, product):
    return {a.angle: a for a in scores if a.product == product}


def test_formulas():
    assert age_factor(None) == 1.0
    assert math.isclose(age_factor(7), 1 - math.exp(-1))
    assert age_factor(1) == age_factor(MIN_AGE_DAYS)  # borné : pas de ×8 sur un relevé d'un jour
    assert age_factor(60) > 0.99
    assert shrink(0, 0.0, 0.5, 5) == 0.5
    assert math.isclose(shrink(20, 1.0, 0.0, 5), 0.8)
    assert math.isclose(shrink(2, 2.1, 0.0, 5), 0.6)  # 2 contenus : les 5/7 du poids à l'a priori
    assert pause_margin(0.5) == 1.0 and pause_margin(0.25) == 2.0 and pause_margin(0) == math.inf


def test_small_sample_does_not_crush_large_sample(conn):
    for _ in range(20):
        measured(conn, "avis", "pas-a-pas", "youtube", 1300)
    for _ in range(2):
        measured(conn, "avis", "mythe", "youtube", 3000)  # 2 vidéos à 2,3× les vues
    for _ in range(10):
        measured(conn, "avis", "outil", "youtube", 1000)
    s = by_angle(angle_scores(conn), "avis")
    big, small, low = s["pas-a-pas"], s["mythe"], s["outil"]
    assert big.n == 20 and small.n == 2 and low.n == 10
    assert small.raw_mean - big.raw_mean > 1.0  # brut : l'angle à 2 vidéos domine largement
    # lissé : l'écart est réduit d'au moins deux tiers et les deux angles restent privilégiés
    assert small.score - big.score < (small.raw_mean - big.raw_mean) / 3
    assert big.above_median and small.above_median and not low.above_median
    assert strong_angles(angle_scores(conn)) == {"avis": {"pas-a-pas", "mythe"}}
    # l'angle moins bon n'est pas « nettement » sous la médiane : pas de pause
    assert update_angle_status(conn, angle_scores(conn)) == [] and paused_angles(conn) == set()
    assert s["pas-a-pas"].views_avg == 1300 and sorted(s) == ["mythe", "outil", "pas-a-pas"]


def test_platform_and_age_normalization(conn):
    for _ in range(3):
        measured(conn, "marches", "checklist", "pinterest", 5000)  # impressions
    for _ in range(3):
        measured(conn, "marches", "pas-a-pas", "youtube", 300)
    s = by_angle(angle_scores(conn), "marches")
    # 5 000 impressions Pinterest ne valent pas plus que 300 vues YouTube : chacun est la
    # médiane de sa plateforme
    assert s["checklist"].score == s["pas-a-pas"].score == 0.0
    assert s["checklist"].platforms == {"pinterest": 3}
    measured(conn, "marches", "outil", "youtube", 1200)  # 4× la médiane YouTube
    s = by_angle(angle_scores(conn), "marches")
    assert s["outil"].score > s["pas-a-pas"].score == s["checklist"].score
    assert s["outil"].raw_mean > 1.9 and s["outil"].ratio > 1.0
    # âge : à vues égales, un contenu jeune est projeté plus haut qu'un contenu mûr ; un relevé de
    # moins de deux jours est écarté (trop récent)
    young = measured(conn, "cabinets", "mythe", "youtube", 500, age_days=3)
    old = measured(conn, "cabinets", "mythe", "youtube", 500, age_days=40)
    fresh = measured(conn, "cabinets", "mythe", "youtube", 500, age_days=0.5)
    contents = {c.draft_id: c for c in content_scores(conn)}
    assert contents[young].projected > contents[old].projected > 500
    assert contents[fresh].too_recent and not contents[old].too_recent
    assert contents[young].x > contents[old].x and contents[fresh].x == 0
    s = by_angle(angle_scores(conn), "cabinets")
    assert s["mythe"].n == 2 and s["mythe"].too_recent == 1


def test_pause_reactivation_and_manual_overrides(conn):
    for _ in range(8):
        measured(conn, "avis", "pas-a-pas", "youtube", 1000)
    for _ in range(8):
        measured(conn, "avis", "outil", "youtube", 900)  # l'angle médian
    for _ in range(8):
        measured(conn, "avis", "mythe", "youtube", 150)  # 0,15× : nettement sous la médiane
    scores = angle_scores(conn)
    decisions = update_angle_status(conn, scores, min_contents=6, pause_ratio=0.5)
    assert [(d["product"], d["angle"], d["status"]) for d in decisions] == [
        ("avis", "mythe", "paused")
    ]
    assert "après 8 contenus" in decisions[0]["reason"]
    assert paused_angles(conn) == {("avis", "mythe")}
    # l'angle médian est privilégié aussi (≥ médiane : inclusif quand peu d'angles sont mesurés)
    assert strong_angles(scores) == {"avis": {"pas-a-pas", "outil"}}
    row = conn.execute("SELECT * FROM angle_status").fetchone()
    assert row["decided_by"] == "auto" and row["n_contents"] == 8 and row["score"] < 0
    # pas assez de contenus pour conclure : rien ne bouge (ni pause ni réactivation)
    with conn:
        conn.execute("DELETE FROM angle_status")
    assert update_angle_status(conn, angle_scores(conn), min_contents=10) == []
    update_angle_status(conn, angle_scores(conn), min_contents=6)
    # réactivé à la main : pas remis en pause tant que 6 nouveaux contenus n'ont pas été mesurés
    set_angle_status(conn, "avis", "mythe", "active", "réactivé à la main", "manual", n=8)
    assert update_angle_status(conn, angle_scores(conn), min_contents=6) == []
    assert paused_angles(conn) == set()
    for _ in range(6):
        measured(conn, "avis", "mythe", "youtube", 150)
    decisions = update_angle_status(conn, angle_scores(conn), min_contents=6)
    assert (
        decisions and decisions[0]["status"] == "paused" and "14 contenus" in decisions[0]["reason"]
    )
    # réactivation automatique quand le score revient à mi-chemin du seuil (ici : seuil élargi)
    decisions = update_angle_status(conn, angle_scores(conn), min_contents=6, pause_ratio=0.02)
    assert [d["status"] for d in decisions] == ["active"] and "revenu" in decisions[0]["reason"]
    # pause manuelle : jamais levée automatiquement, même pour l'angle qui marche (« mythe »,
    # réactivé automatiquement ci-dessus, repasse en pause au seuil par défaut)
    set_angle_status(conn, "avis", "pas-a-pas", "paused", "mis en pause à la main", "manual")
    decisions = update_angle_status(conn, angle_scores(conn))
    assert [(d["angle"], d["status"]) for d in decisions] == [("mythe", "paused")]
    assert paused_angles(conn) == {("avis", "pas-a-pas"), ("avis", "mythe")}
    assert strong_angles(angle_scores(conn)) == {"avis": {"outil"}}
    # ANGLE_PAUSE_RATIO=0 : pause automatique désactivée
    with conn:
        conn.execute("DELETE FROM angle_status")
    assert update_angle_status(conn, angle_scores(conn), pause_ratio=0) == []


def test_select_topics_exploits_explores_and_skips_paused(conn):
    with conn:
        conn.execute("UPDATE topics SET status = 'used'")
    paused_ids = [add_topic(conn, "avis", f"Sujet en pause {i} ?", "mythe") for i in range(2)]
    strong_ids = [add_topic(conn, "avis", f"Sujet fort {i} ?", "pas-a-pas") for i in range(4)]
    other_ids = [add_topic(conn, "avis", f"Sujet autre {i} ?", "outil") for i in range(3)]
    free_id = add_topic(conn, "avis", "Sujet sans angle ?", None)
    strong, paused = {"avis": {"pas-a-pas"}}, {("avis", "mythe")}
    picks = select_topics(conn, 5, "avis", strong=strong, paused=paused, exploration_rate=0.3)
    assert [m for _, m in picks] == ["exploitation"] * 3 + ["exploration"] * 2
    assert [t["id"] for t, _ in picks] == strong_ids[:3] + other_ids[:2]
    assert not {t["id"] for t, _ in picks} & set(paused_ids)
    # sans exploration : les angles forts d'abord, puis le reste par ancienneté
    picks = select_topics(conn, 6, "avis", strong=strong, paused=paused, exploration_rate=0.0)
    assert [t["id"] for t, _ in picks] == strong_ids + other_ids[:2]
    assert [m for _, m in picks] == ["exploitation"] * 4 + ["exploration"] * 2
    # exploration seule : les autres angles (y compris « libre ») d'abord
    picks = select_topics(conn, 5, "avis", strong=strong, paused=paused, exploration_rate=1.0)
    assert [t["id"] for t, _ in picks] == other_ids + [free_id, strong_ids[0]]
    # sans métriques pour ce produit : comportement historique (ancienneté), sujets en pause exclus
    picks = select_topics(conn, 3, "avis", paused=paused)
    assert [t["id"] for t, _ in picks] == strong_ids[:3]
    assert [m for _, m in picks] == ["ancienneté"] * 3
    assert [t["id"] for t in pick_topics(conn, 2, "avis")] == paused_ids


def test_pick_topics_alternates_products_oldest_first(conn):
    rows = pick_topics(conn, 6)
    assert [r["product"] for r in rows] == ["avis", "marches", "cabinets"] * 2
    for product in ("avis", "marches", "cabinets"):
        ids = [r["id"] for r in rows if r["product"] == product]
        assert ids == sorted(ids)


def test_run_daily_without_metrics_is_unchanged(conn, llm, settings):
    expected = [t["id"] for t in pick_topics(conn, 5)]
    report = run_daily(conn, settings, llm, today=NOW.date(), scripts_per_day=5)
    assert [s["topic_id"] for s in report["scripts"]] == expected
    assert {s["mode"] for s in report["scripts"]} == {"ancienneté"}
    assert report["angles"] == {
        "decisions": [],
        "paused": [],
        "favored": {},
        "exploration_rate": 0.3,
    }
    assert conn.execute("SELECT COUNT(*) FROM angle_status").fetchone()[0] == 0


def test_run_daily_with_metrics_prefers_strong_angles_and_pauses_bad_ones(conn, llm, settings):
    for _ in range(8):
        measured(conn, "avis", "script-pret-a-dire", "youtube", 2000)
    for _ in range(8):
        measured(conn, "avis", "outil", "youtube", 900)
    for _ in range(8):
        measured(conn, "avis", "mythe", "youtube", 120)
    report = run_daily(conn, settings, llm, today=NOW.date(), scripts_per_day=5)
    angles = report["angles"]
    # l'angle médian (outil) est privilégié avec le meilleur ; le mauvais est mis en pause
    assert angles["paused"] == ["avis/mythe"]
    assert angles["favored"] == {"avis": ["outil", "script-pret-a-dire"]}
    assert [(d["angle"], d["status"]) for d in angles["decisions"]] == [("mythe", "paused")]
    assert len(report["scripts"]) == 5 and report["errors"] == []
    products = {r["id"]: r["product"] for r in conn.execute("SELECT id, product FROM topics")}
    for item in report["scripts"]:
        if products[item["topic_id"]] == "avis":  # produit mesuré : exploitation / exploration
            assert item["mode"] == "exploitation" and item["angle"] in angles["favored"]["avis"]
        else:  # produits sans métriques : comportement historique
            assert item["mode"] == "ancienneté"
    modes = {s["topic_id"]: s["mode"] for s in report["scripts"]}
    assert modes[1] == modes[3] == "exploitation"  # #2 (avis/mythe, en pause) est sauté
    # la pause vaut pour (avis, mythe) seulement : marches/mythe reste scriptable
    assert all(
        s["angle"] != "mythe" for s in report["scripts"] if products[s["topic_id"]] == "avis"
    )
    # le prompt d'idées pour avis ne propose plus l'angle en pause
    ideas_prompts = [c["prompt"] for c in llm.calls if '"questions"' in c["prompt"]]
    avis_prompt = next(p for p in ideas_prompts if "Produit : avis" in p)
    assert "  - mythe :" not in avis_prompt and "  - pas-a-pas :" in avis_prompt
    assert (
        conn.execute(
            "SELECT status FROM angle_status WHERE product = 'avis' AND angle = 'mythe'"
        ).fetchone()[0]
        == "paused"
    )
