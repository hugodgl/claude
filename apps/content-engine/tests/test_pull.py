"""`ce metrics --pull` : adaptateurs sur réponses simulées (httpx.MockTransport), historisation
datée, erreurs isolées par plateforme, dry-run, stubs TikTok (avant audit) et LinkedIn."""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from content_engine.metrics import angle_ranking, import_csv
from content_engine.pull import published_items, pull_metrics
from content_engine.pull.pinterest import pin_metrics
from content_engine.pull.youtube import YouTubeMetricsSource
from tests.conftest import make_draft

NOW = datetime(2026, 10, 28, 22, 30, tzinfo=UTC)


def live_publication(conn, draft_id, platform, remote_id, days_ago=10, post_id=None):
    published_at = (NOW - timedelta(days=days_ago)).isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO publications (draft_id, platform, dry_run, remote_id, post_id, "
            "published_at) VALUES (?, ?, 0, ?, ?, ?)",
            (draft_id, platform, remote_id, post_id, published_at),
        )
    return int(cur.lastrowid)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def count_metrics(conn, where="1=1"):
    return int(conn.execute(f"SELECT COUNT(*) FROM metrics WHERE {where}").fetchone()[0])


YT_ITEMS = {
    "items": [
        {
            "id": "vid1",
            "statistics": {
                "viewCount": "1200",
                "likeCount": "40",
                "commentCount": "3",
                "favoriteCount": "0",
            },
            "contentDetails": {"duration": "PT42S"},
        },
        {
            "id": "vid2",
            "statistics": {"viewCount": "300", "likeCount": "9", "commentCount": "0"},
            "contentDetails": {"duration": "PT38S"},
        },
    ]
}
YT_REPORT = {
    "kind": "youtubeAnalytics#resultTable",
    "columnHeaders": [
        {"name": "video", "columnType": "DIMENSION", "dataType": "STRING"},
        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
        {"name": "estimatedMinutesWatched", "columnType": "METRIC", "dataType": "INTEGER"},
        {"name": "averageViewPercentage", "columnType": "METRIC", "dataType": "FLOAT"},
        {"name": "shares", "columnType": "METRIC", "dataType": "INTEGER"},
    ],
    "rows": [["vid1", 1150, 540.5, 62.3, 11]],
}


def test_youtube_pull_stores_dated_history(conn, llm, settings):
    d1 = make_draft(conn, llm, topic_id=1, status="published")
    d2 = make_draft(conn, llm, topic_id=2, status="published")
    live_publication(conn, d1, "youtube", "vid1", days_ago=10)
    live_publication(conn, d2, "youtube", "vid2", days_ago=3)
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.host)
        assert request.headers["Authorization"] == "Bearer t0k"
        p = request.url.params
        if request.url.host == "www.googleapis.com":
            assert request.url.path == "/youtube/v3/videos"
            assert p["part"] == "statistics,contentDetails"
            assert set(p["id"].split(",")) == {"vid1", "vid2"}
            return httpx.Response(200, json=YT_ITEMS)
        assert request.url.host == "youtubeanalytics.googleapis.com"
        assert p["ids"] == "channel==MINE" and p["dimensions"] == "video"
        end = date.fromisoformat(p["endDate"])  # fenêtre --days (90 par défaut) jusqu'au relevé
        assert p["startDate"] == (end - timedelta(days=90)).isoformat()
        assert end in (NOW.date(), NOW.date() + timedelta(days=1))
        assert "averageViewPercentage" in p["metrics"] and p["filters"].startswith("video==")
        return httpx.Response(200, json=YT_REPORT)

    sources = {"youtube": YouTubeMetricsSource(token="t0k", analytics=True)}
    rep = pull_metrics(
        conn, settings, platforms=["youtube"], client=client_for(handler), sources=sources, now=NOW
    )
    yt = rep.platforms["youtube"]
    assert yt.error is None and yt.stored == 2 and yt.publications == 2 and len(calls) == 2
    assert rep.succeeded == ["youtube"] and rep.failed == []
    rows = {r["remote_id"]: r for r in conn.execute("SELECT * FROM metrics")}
    v1 = rows["vid1"]
    assert v1["views"] == 1200 and v1["likes"] == 40 and v1["comments"] == 3
    assert v1["shares"] == 11 and v1["avg_view_pct"] == 62.3 and v1["watch_time_h"] == 9.008
    assert v1["draft_id"] == d1 and v1["source"] == "api" and v1["source_file"] is None
    assert v1["measured_at"] == "2026-10-28T22:30:00+00:00"
    assert v1["published_at"] == (NOW - timedelta(days=10)).isoformat()
    assert json.loads(v1["extra_json"])["duration"] == "PT42S"
    assert rows["vid2"]["avg_view_pct"] is None and rows["vid2"]["shares"] == 0
    # relancé le même jour : le relevé du jour est mis à jour, pas dupliqué
    pull_metrics(
        conn,
        settings,
        platforms=["youtube"],
        client=client_for(handler),
        sources=sources,
        now=NOW + timedelta(hours=1),
    )
    assert count_metrics(conn) == 2
    # le lendemain : nouvelles lignes, l'historique de la veille est conservé
    pull_metrics(
        conn,
        settings,
        platforms=["youtube"],
        client=client_for(handler),
        sources=sources,
        now=NOW + timedelta(days=1),
    )
    assert count_metrics(conn) == 4 and count_metrics(conn, "measured_at LIKE '2026-10-29%'") == 2
    # les classements ne comptent que le dernier relevé de chaque contenu
    assert sum(r["n"] for r in angle_ranking(conn)) == 2
    # un import CSV du même contenu ne touche pas à l'historique API
    csv_path = settings.out_dir / "yt.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("Content,Video title,Views\nvid1,Titre,1300\n", encoding="utf-8")
    import_csv(conn, csv_path)
    assert count_metrics(conn, "source = 'api'") == 4 and count_metrics(conn, "source = 'csv'") == 1


def test_youtube_analytics_is_optional(conn, llm, settings):
    d1 = make_draft(conn, llm, topic_id=1, status="published")
    d3 = make_draft(conn, llm, topic_id=3, status="published")
    live_publication(conn, d1, "youtube", "vid1")
    live_publication(conn, d3, "youtube", "vid3")  # absente de la réponse (supprimée)
    hosts = []

    def handler(request: httpx.Request):
        hosts.append(request.url.host)
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json=YT_ITEMS)
        return httpx.Response(403, json={"error": {"message": "insufficientPermissions"}})

    # portée analytics absente du jeton : seul videos.list est appelé, note explicite
    rep = pull_metrics(
        conn,
        settings,
        platforms=["youtube"],
        client=client_for(handler),
        sources={"youtube": YouTubeMetricsSource(token="t0k", analytics=False)},
        now=NOW,
    )
    yt = rep.platforms["youtube"]
    assert yt.error is None and yt.stored == 1 and hosts == ["www.googleapis.com"]
    assert any("yt-analytics.readonly" in n for n in yt.notes)
    assert any("vid3" in n and "absente" in n for n in yt.notes)  # vidéo supprimée : signalée
    assert count_metrics(conn, "remote_id = 'vid2'") == 0  # vidéo non demandée : ignorée
    # portée présente mais Analytics en erreur : les compteurs videos.list restent enregistrés
    rep = pull_metrics(
        conn,
        settings,
        platforms=["youtube"],
        client=client_for(handler),
        sources={"youtube": YouTubeMetricsSource(token="t0k", analytics=True)},
        now=NOW + timedelta(days=1),
    )
    yt = rep.platforms["youtube"]
    assert yt.error is None and yt.stored == 1
    assert any("Analytics ignoré" in n and "403" in n for n in yt.notes)


def test_pinterest_pull_maps_pin_analytics(conn, llm, settings):
    settings = settings.model_copy(
        update={"pinterest_access_token": "ptok", "pinterest_board_id": "b1"}
    )
    p1 = make_draft(conn, llm, topic_id=30, fmt="pin", status="published")
    p2 = make_draft(conn, llm, topic_id=31, fmt="pin", status="published")
    live_publication(conn, p1, "pinterest", "pin-1", days_ago=20)
    live_publication(conn, p2, "pinterest", "pin-2", days_ago=5)
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer ptok"
        p = request.url.params
        assert p["metric_types"] == "IMPRESSION,PIN_CLICK,OUTBOUND_CLICK,SAVE"
        assert p["start_date"] == "2026-09-28" and p["end_date"] == "2026-10-28"
        if request.url.path.endswith("/pin-2/analytics"):
            return httpx.Response(404, json={"code": 4, "message": "Pin not found"})
        return httpx.Response(
            200,
            json={
                "all": {
                    "lifetime_metrics": {
                        "IMPRESSION": 5400.0,
                        "PIN_CLICK": 80,
                        "OUTBOUND_CLICK": 37,
                        "SAVE": 12,
                    },
                    "daily_metrics": [
                        {"date": "2026-10-27", "data_status": "READY", "metrics": {"IMPRESSION": 9}}
                    ],
                }
            },
        )

    rep = pull_metrics(
        conn, settings, platforms=["pinterest"], days=30, client=client_for(handler), now=NOW
    )
    pr = rep.platforms["pinterest"]
    assert pr.error is None and pr.stored == 1 and len(seen) == 2
    assert any("pin-2" in n and "404" in n for n in pr.notes)
    row = conn.execute("SELECT * FROM metrics").fetchone()
    assert row["draft_id"] == p1 and row["views"] == 5400 and row["impressions"] == 5400
    assert row["clicks"] == 37 and row["shares"] == 12 and row["ctr"] == 0.69
    assert json.loads(row["extra_json"])["PIN_CLICK"] == 80
    # réponse sans lifetime_metrics : somme des métriques journalières
    metrics, scope = pin_metrics(
        {
            "all": {
                "daily_metrics": [
                    {"date": "2026-10-26", "metrics": {"IMPRESSION": 10, "SAVE": 1}},
                    {"date": "2026-10-27", "metrics": {"IMPRESSION": 5}},
                ]
            }
        }
    )
    assert metrics == {"IMPRESSION": 15, "SAVE": 1} and scope == "window"
    assert pin_metrics({})[0] == {}


def test_tiktok_pull_is_unavailable_before_audit_then_resolves_post_ids(conn, llm, settings):
    settings = settings.model_copy(update={"tiktok_access_token": "ttok"})
    d1 = make_draft(conn, llm, topic_id=3, status="published")
    d2 = make_draft(conn, llm, topic_id=4, status="published")
    pub1 = live_publication(conn, d1, "tiktok", "v_pub_1", days_ago=8)
    live_publication(conn, d2, "tiktok", "v_pub_2", days_ago=1)
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer ttok"
        body = json.loads(request.content)
        if request.url.path.endswith("/status/fetch/"):
            if body["publish_id"] == "v_pub_1":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "status": "PUBLISH_COMPLETE",
                            "publicaly_available_post_id": [7311111111111111111],
                        },
                        "error": {"code": "ok", "message": ""},
                    },
                )
            return httpx.Response(
                200, json={"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}}
            )
        assert request.url.path == "/v2/video/query/"
        assert request.url.params["fields"] == "id,like_count,comment_count,share_count,view_count"
        assert body == {"filters": {"video_ids": ["7311111111111111111"]}}
        return httpx.Response(
            200,
            json={
                "data": {
                    "videos": [
                        {
                            "id": 7311111111111111111,
                            "like_count": 15,
                            "comment_count": 2,
                            "share_count": 4,
                            "view_count": 980,
                        }
                    ]
                },
                "error": {"code": "ok", "message": "", "log_id": "x"},
            },
        )

    rep = pull_metrics(conn, settings, platforms=["tiktok"], client=client_for(handler), now=NOW)
    tt = rep.platforms["tiktok"]
    assert tt.error is None and not tt.available and tt.stored == 0 and calls == []
    assert any("non disponible" in n and "TIKTOK_APP_AUDITED" in n for n in tt.notes)
    assert rep.attempted == []  # rien n'a été tenté : pas un échec
    audited = settings.model_copy(update={"tiktok_app_audited": True})
    rep = pull_metrics(conn, audited, platforms=["tiktok"], client=client_for(handler), now=NOW)
    tt = rep.platforms["tiktok"]
    assert tt.error is None and tt.stored == 1
    assert calls == [
        "/v2/post/publish/status/fetch/",
        "/v2/post/publish/status/fetch/",
        "/v2/video/query/",
    ]
    assert any("pas encore publié" in n and "PROCESSING_UPLOAD" in n for n in tt.notes)
    row = conn.execute("SELECT * FROM metrics").fetchone()
    assert row["draft_id"] == d1 and row["remote_id"] == "v_pub_1" and row["views"] == 980
    assert row["likes"] == 15 and row["comments"] == 2 and row["shares"] == 4
    post_id = conn.execute("SELECT post_id FROM publications WHERE id = ?", (pub1,)).fetchone()[0]
    assert post_id == "7311111111111111111"
    # relevé suivant : l'identifiant public est connu, status/fetch n'est plus appelé pour #1
    calls.clear()
    pull_metrics(
        conn, audited, platforms=["tiktok"], client=client_for(handler), now=NOW + timedelta(days=1)
    )
    assert calls == ["/v2/post/publish/status/fetch/", "/v2/video/query/"]


def test_linkedin_pull_is_a_documented_stub(conn, llm, settings):
    post = make_draft(conn, llm, topic_id=16, fmt="linkedin", status="published")
    live_publication(conn, post, "linkedin", "urn:li:share:77")

    def handler(request: httpx.Request):
        raise AssertionError("aucun appel attendu")

    rep = pull_metrics(conn, settings, platforms=["linkedin"], client=client_for(handler), now=NOW)
    li = rep.platforms["linkedin"]
    assert li.error is None and not li.available and li.publications == 1 and li.stored == 0
    assert any("non disponible" in n and "Marketing API" in n for n in li.notes)


def test_errors_are_isolated_per_platform_and_dry_run_writes_nothing(conn, llm, settings):
    settings = settings.model_copy(
        update={"pinterest_access_token": "ptok", "pinterest_board_id": "b1"}
    )
    short = make_draft(conn, llm, topic_id=5, status="published")
    pin = make_draft(conn, llm, topic_id=32, fmt="pin", status="published")
    live_publication(conn, short, "youtube", "vid9")
    live_publication(conn, pin, "pinterest", "pin-9")
    mode = {"youtube": "network"}

    def handler(request: httpx.Request):
        if request.url.host == "www.googleapis.com":
            if mode["youtube"] == "network":
                raise httpx.ConnectError("réseau coupé", request=request)
            return httpx.Response(
                403,
                json={"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}},
            )
        return httpx.Response(
            200, json={"all": {"lifetime_metrics": {"IMPRESSION": 100, "OUTBOUND_CLICK": 1}}}
        )

    sources = {"youtube": YouTubeMetricsSource(token="t0k", analytics=False)}
    rep = pull_metrics(
        conn,
        settings,
        platforms=["youtube", "pinterest"],
        client=client_for(handler),
        sources=sources,
        now=NOW,
    )
    assert "ConnectError" in rep.platforms["youtube"].error
    assert rep.platforms["pinterest"].error is None and rep.platforms["pinterest"].stored == 1
    assert rep.failed == ["youtube"] and rep.succeeded == ["pinterest"]
    mode["youtube"] = "quota"
    rep = pull_metrics(
        conn, settings, platforms=["youtube"], client=client_for(handler), sources=sources, now=NOW
    )
    assert "quota" in rep.platforms["youtube"].error and "403" in rep.platforms["youtube"].error
    assert rep.attempted == ["youtube"] and rep.succeeded == []
    # dry-run : les relevés sont rapportés mais rien n'est écrit
    before = count_metrics(conn)
    rep = pull_metrics(
        conn,
        settings,
        platforms=["pinterest"],
        dry_run=True,
        client=client_for(handler),
        now=NOW + timedelta(days=2),
    )
    assert rep.dry_run and len(rep.platforms["pinterest"].snapshots) == 1
    assert rep.platforms["pinterest"].stored == 0 and count_metrics(conn) == before
    with pytest.raises(ValueError, match="plateforme inconnue"):
        pull_metrics(conn, settings, platforms=["mastodon"], client=client_for(handler))


def test_published_items_only_real_recent_publications(conn, llm, settings):
    published = make_draft(conn, llm, topic_id=6, status="published")
    rendered = make_draft(conn, llm, topic_id=7, status="rendered")
    live_publication(conn, published, "youtube", "recent", days_ago=5)
    live_publication(conn, published, "youtube", "old", days_ago=120)
    live_publication(conn, rendered, "youtube", "not-published-status", days_ago=5)
    with conn:
        conn.execute(
            "INSERT INTO publications (draft_id, platform, dry_run, remote_id, published_at) "
            "VALUES (?, 'youtube', 1, 'simulated', ?)",
            (published, NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO publications (draft_id, platform, dry_run, remote_id, published_at) "
            "VALUES (?, 'youtube', 0, NULL, ?)",
            (published, NOW.isoformat()),
        )
    since = (NOW - timedelta(days=90)).isoformat()
    items = published_items(conn, "youtube", since)
    assert [i.remote_id for i in items] == ["recent"]
    assert items[0].draft_id == published and items[0].product == "avis" and items[0].title
    assert [i.remote_id for i in published_items(conn, "youtube", "2000-01-01")] == [
        "recent",
        "old",
    ]
