from content_engine.metrics import (
    angle_ranking,
    detect_platform,
    import_csv,
    parse_number,
    unlinked_count,
)
from content_engine.scripts import draft_payload, get_draft
from tests.conftest import make_draft

YT_HEADER = (
    "Contenu,Titre de la vidéo,Heure de publication de la vidéo,Durée,Vues,"
    "Durée de visionnage (heures),Abonnés,Impressions,Taux de clics des impressions (%)\n"
)


def test_parse_number_and_platform_detection():
    assert parse_number("1 234") == 1234 and parse_number("1,234") == 1234
    assert (
        parse_number("12,5") == 12.5 and parse_number("4.2 %") == 4.2 and parse_number("") is None
    )
    assert detect_platform(["Video title", "Video views", "Likes"]) == "tiktok"
    assert detect_platform(["Content", "Views", "Watch time (hours)"]) == "youtube"


def test_import_youtube_csv_links_by_title_and_replaces(conn, llm, settings, tmp_path):
    draft_id = make_draft(conn, llm, topic_id=1, status="rendered")
    title = draft_payload(get_draft(conn, draft_id))["title"]
    csv_path = tmp_path / "youtube.csv"
    csv_path.write_text(
        YT_HEADER + 'Total,,,,"1 234",12.5,3,"20 000",4.2\n'
        f'abc123,"{title}",2026-10-20,35,"1 034",10.1,2,"15 000",4.5\n'
        'xyz789,"Vidéo inconnue",2026-10-21,40,200,2.4,1,"5 000",2.1\n',
        encoding="utf-8",
    )
    rep = import_csv(conn, csv_path)
    assert rep == {**rep, "platform": "youtube", "imported": 2, "linked": 1, "skipped": 1}
    rows = conn.execute("SELECT * FROM metrics ORDER BY id").fetchall()
    assert rows[0]["views"] == 1034 and rows[0]["draft_id"] == draft_id and rows[0]["ctr"] == 4.5
    assert rows[0]["impressions"] == 15000 and rows[1]["draft_id"] is None
    import_csv(conn, csv_path)  # réimport : remplace, ne duplique pas
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2
    assert unlinked_count(conn) == 1


def test_import_links_live_publication_by_remote_id(conn, llm, settings, tmp_path):
    draft_id = make_draft(conn, llm, topic_id=2, status="published")
    conn.execute(
        "INSERT INTO publications (draft_id, platform, dry_run, remote_id, published_at) "
        "VALUES (?, 'tiktok', 0, 'v42', '2026-10-01')",
        (draft_id,),
    )
    csv_path = tmp_path / "tiktok.csv"
    csv_path.write_text(
        "Post ID;Video title;Post time;Video views;Likes;Comments;Shares\n"
        "v42;Autre titre;2026-10-02;5 000;120;4;9\n",
        encoding="utf-8",
    )
    rep = import_csv(conn, csv_path)
    assert rep["platform"] == "tiktok" and rep["linked"] == 1
    row = conn.execute("SELECT * FROM metrics").fetchone()
    assert row["draft_id"] == draft_id and row["views"] == 5000 and row["likes"] == 120
    ranking = angle_ranking(conn)
    assert ranking[0]["angle"] == "mythe" and ranking[0]["views_avg"] == 5000
    assert angle_ranking(conn, product="cabinets") == []
