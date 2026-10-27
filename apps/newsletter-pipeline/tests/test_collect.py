from pathlib import Path

import httpx
import pytest
from conftest import FIXTURES, write_sources_yaml

from newsletter_pipeline import db
from newsletter_pipeline.collect import Collector, discover_links, extract_article, html_to_text
from newsletter_pipeline.settings import APP_ROOT
from newsletter_pipeline.sources import load_sources


def test_html_to_text():
    assert html_to_text("<p>Bonjour <b>monde</b></p><script>x()</script><p>Suite &amp; fin</p>") == "Bonjour monde\nSuite & fin"
    assert html_to_text(None) == ""


def test_seed_sources_yaml_is_valid():
    specs = load_sources(APP_ROOT / "sources.yaml")
    assert 30 <= len(specs) <= 40
    assert {s.category for s in specs} >= {"editeurs", "presse_pro", "institutions", "ia_generale", "newsletters_en"}
    assert all(s.kind in ("rss", "page") for s in specs)
    assert len({s.name for s in specs}) == len(specs)


def test_collect_rss_fixtures(conn, settings):
    collector = Collector(conn, settings)
    stats = collector.sync_from_yaml()
    assert stats["total"] == 3 and stats["inserted"] == 3
    report = collector.collect_source(db.get_source(conn, "Éditeur test"))
    assert report.error is None
    assert report.seen == 9 and report.inserted == 7 and report.duplicates == 2
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    assert len(rows) == 7
    first = rows[0]
    assert first["url"] == "https://blog.editeur-test.fr/articles/assistant-ia-cabinets"  # utm retirés
    assert first["published_at"] == "2026-10-19T06:00:00+00:00"
    assert first["author"] == "Équipe produit"
    assert "déploiement général" in first["content_text"]  # content:encoded préféré au résumé
    assert "<p>" not in first["content_text"]
    assert first["status"] == "new" and first["score"] is None
    assert all(r["title_hash"] for r in rows)


def test_collect_atom_and_idempotence(conn, settings):
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    r1 = collector.collect_source(db.get_source(conn, "Institution test"))
    assert r1.inserted == 5 and r1.error is None
    row = conn.execute("SELECT * FROM items WHERE url LIKE '%decret-information%'").fetchone()
    assert row["published_at"] == "2026-10-21T09:00:00+00:00"
    r2 = collector.collect_source(db.get_source(conn, "Institution test"))
    assert r2.inserted == 0 and r2.duplicates == 5
    src = db.get_source(conn, "Institution test")
    assert src["last_fetched_at"] and src["last_error"] is None


def test_collect_error_does_not_stop_batch(conn, settings):
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    report = collector.run()
    names = {s.name: s for s in report.sources}
    assert names["Source cassée"].error
    assert names["Éditeur test"].inserted == 7 and names["Institution test"].inserted == 5
    assert report.inserted == 12 and len(report.errors) == 1
    assert db.get_source(conn, "Source cassée")["last_error"]


def test_collect_single_unknown_source(conn, settings):
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    with pytest.raises(LookupError):
        collector.run("N'existe pas")


def test_collect_dry_run_writes_nothing(conn, settings):
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    report = collector.run("Éditeur test", dry_run=True)
    assert report.inserted == 7 and report.sources[0].titles
    assert conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"] == 0
    assert db.get_source(conn, "Éditeur test")["last_fetched_at"] is None


def test_discover_links_filters_navigation_and_externals():
    html = (FIXTURES / "page_listing.html").read_text(encoding="utf-8")
    links = discover_links(html, "https://blog.page-test.fr/blog/")
    assert links == [
        "https://blog.page-test.fr/blog/2026/10/revision-assistee-par-ia",
        "https://blog.page-test.fr/blog/2026/10/lettre-de-mission-clause-ia",
        "https://blog.page-test.fr/blog/2026/10/breve-trop-courte",
    ]
    only = discover_links(html, "https://blog.page-test.fr/blog/", ["lettre-de-mission"])
    assert only == ["https://blog.page-test.fr/blog/2026/10/lettre-de-mission-clause-ia"]


def test_extract_article_metadata():
    html = (FIXTURES / "page_article_1.html").read_text(encoding="utf-8")
    art = extract_article(html, "https://blog.page-test.fr/blog/2026/10/revision-assistee-par-ia")
    assert art["title"].startswith("Révision assistée par IA")
    assert art["author"] == "Marie Durand"
    assert art["published_at"] == "2026-10-21"
    assert "le réviseur décide" in art["text"] and len(art["text"]) > 300


def _mock_client(requests: list[str]) -> httpx.Client:
    pages = {
        "/blog/": "page_listing.html",
        "/blog/2026/10/revision-assistee-par-ia": "page_article_1.html",
        "/blog/2026/10/lettre-de-mission-clause-ia": "page_article_2.html",
        "/blog/2026/10/breve-trop-courte": "page_article_3.html",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        name = pages.get(request.url.path)
        if not name:
            return httpx.Response(404, text="introuvable")
        return httpx.Response(200, text=(FIXTURES / name).read_text(encoding="utf-8"),
                              headers={"content-type": "text/html; charset=utf-8"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_collect_page_source_with_delay(conn, settings, workdir: Path):
    extra = """
  - name: Page test
    url: https://blog.page-test.fr/blog/
    kind: page
    category: presse_pro
"""
    settings.sources_file = write_sources_yaml(workdir / "sources_page.yaml", with_broken=False, extra=extra)
    settings.request_delay_s = 0.5
    requests: list[str] = []
    sleeps: list[float] = []
    collector = Collector(conn, settings, client=_mock_client(requests), sleep=sleeps.append)
    collector.sync_from_yaml()
    report = collector.collect_source(db.get_source(conn, "Page test"))
    assert report.error is None
    assert report.inserted == 2 and report.seen == 2  # la brève trop courte est ignorée
    assert requests == ["/blog/", "/blog/2026/10/revision-assistee-par-ia",
                        "/blog/2026/10/lettre-de-mission-clause-ia", "/blog/2026/10/breve-trop-courte"]
    assert sleeps == [0.5, 0.5, 0.5]  # un délai entre chaque requête, pas avant la première
    row = conn.execute("SELECT * FROM items WHERE url LIKE '%lettre-de-mission%'").fetchone()
    assert row["author"] == "Paul Martin" and row["published_at"] == "2026-10-22"
    assert len(row["content_text"]) > 300
    # second passage : les articles connus ne sont pas retéléchargés
    requests.clear()
    report2 = collector.collect_source(db.get_source(conn, "Page test"))
    assert report2.inserted == 0
    assert requests == ["/blog/", "/blog/2026/10/breve-trop-courte"]


def test_collect_page_http_error_recorded(conn, settings, workdir: Path):
    extra = """
  - name: Page absente
    url: https://blog.page-test.fr/absent/
    kind: page
    category: presse_pro
"""
    settings.sources_file = write_sources_yaml(workdir / "sources_page.yaml", with_broken=False, extra=extra)
    collector = Collector(conn, settings, client=_mock_client([]))
    collector.sync_from_yaml()
    report = collector.collect_source(db.get_source(conn, "Page absente"))
    assert report.error and "404" in report.error
    assert "404" in db.get_source(conn, "Page absente")["last_error"]
