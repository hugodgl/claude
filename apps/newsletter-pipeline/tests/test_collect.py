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


def test_html_to_text_keeps_trailing_text_and_literal_entities():
    assert html_to_text("Session Q&A") == "Session Q&A"  # le parseur doit être fermé (close)
    assert html_to_text("<p>Tarif : 10&euro</p>") == "Tarif : 10€"
    assert html_to_text("Texte &amp;lt;script&amp;gt; littéral") == "Texte &lt;script&gt; littéral"  # un seul décodage


def test_extract_article_accepts_bytes():
    raw = (FIXTURES / "page_article_1.html").read_bytes()
    art = extract_article(raw, "https://blog.page-test.fr/blog/2026/10/revision-assistee-par-ia")
    assert art["author"] == "Marie Durand" and len(art["text"]) > 300


def _feed_client(xml: str, extra_pages: dict[str, httpx.Response] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed.xml":
            return httpx.Response(200, content=xml.encode("utf-8"), headers={"content-type": "application/rss+xml"})
        if extra_pages and request.url.path in extra_pages:
            return extra_pages[request.url.path]
        return httpx.Response(404, text="introuvable")
    return httpx.Client(transport=httpx.MockTransport(handler))


def _rss_source(settings, workdir, name="Flux HTTP", url="https://site.fr/feed.xml", **fields) -> None:
    extra = f"""
  - name: {name}
    url: {url}
    kind: rss
    category: presse_pro
""" + "".join(f"    {k}: {v}\n" for k, v in fields.items())
    settings.sources_file = write_sources_yaml(workdir / "sources_http.yaml", with_broken=False, extra=extra)


RSS_EDGE_CASES = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><link>https://site.fr/</link>
<item><title>Lien relatif</title><link>/articles/relatif</link><description>%s</description></item>
<item><title>Lien javascript</title><link>javascript:alert(1)</link><description>%s</description></item>
<item><title>Date future</title><link>https://site.fr/futur</link><pubDate>Mon, 19 Oct 2037 08:00:00 +0200</pubDate><description>%s</description></item>
<item><title>Même lien, autre titre</title><link>https://site.fr/futur?utm_source=rss</link><description>%s</description></item>
<item><title>Variante www en http</title><link>http://www.site.fr/futur</link><description>%s</description></item>
</channel></rss>""" % (("Texte de description suffisant pour l'item.",) * 5)


def test_rss_edge_cases_relative_links_future_dates_and_batch_duplicates(conn, settings, workdir):
    _rss_source(settings, workdir)
    collector = Collector(conn, settings, client=_feed_client(RSS_EDGE_CASES))
    collector.sync_from_yaml()
    report = collector.collect_source(db.get_source(conn, "Flux HTTP"))
    assert report.error is None, report.error
    urls = [r["url"] for r in conn.execute("SELECT url FROM items ORDER BY id")]
    assert urls == ["https://site.fr/articles/relatif", "https://site.fr/futur"]  # relatif résolu, javascript écarté
    assert report.inserted == 2 and report.skipped == 1 and report.duplicates == 2  # même URL (utm, www/http) = doublons
    future = conn.execute("SELECT published_at FROM items WHERE url = 'https://site.fr/futur'").fetchone()
    assert future["published_at"] is None  # date dans le futur ignorée


def test_item_exists_matches_scheme_and_www_variants(conn, settings, collected):
    source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
    db.insert_item(conn, source_id, {"url": "https://www.ex.fr/a", "title": "Titre A", "title_hash": "h-a"})
    assert db.item_exists(conn, "http://ex.fr/a", "autre-hash")
    assert db.item_exists(conn, "https://ex.fr/a")
    assert not db.item_exists(conn, "https://ex.fr/b", "autre-hash")


def test_candidate_items_age_filter_falls_back_on_fetch_date(conn, settings, ranked):
    conn.execute("UPDATE items SET published_at = NULL")
    assert len(db.candidate_items(conn, min_published="2026-10-20")) == 12  # récupérés aujourd'hui : gardés
    conn.execute("UPDATE items SET fetched_at = '2020-01-01T00:00:00+00:00'")
    assert db.candidate_items(conn, min_published="2026-10-20") == []  # sans date et vieux : écartés


def test_page_too_large_is_an_error_not_a_download(conn, settings, workdir):
    settings.max_page_bytes = 10_000
    settings.sources_file = write_sources_yaml(workdir / "s.yaml", with_broken=False, extra="""
  - name: Page énorme
    url: https://blog.page-test.fr/blog/
    kind: page
    category: presse_pro
""")
    big = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>" + "x" * 50_000, headers={"content-type": "text/html"})))
    collector = Collector(conn, settings, client=big)
    collector.sync_from_yaml()
    report = collector.collect_source(db.get_source(conn, "Page énorme"))
    assert report.error and "volumineuse" in report.error


def test_page_source_skips_non_html_and_isolates_extraction_errors(conn, settings, workdir, monkeypatch):
    settings.sources_file = write_sources_yaml(workdir / "s.yaml", with_broken=False, extra="""
  - name: Page test
    url: https://blog.page-test.fr/blog/
    kind: page
    category: presse_pro
""")
    listing = (FIXTURES / "page_listing.html").read_text(encoding="utf-8")
    article = (FIXTURES / "page_article_2.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/blog/":
            return httpx.Response(200, text=listing, headers={"content-type": "text/html; charset=utf-8"})
        if path.endswith("revision-assistee-par-ia"):
            return httpx.Response(200, content=b"%PDF-1.4 ...", headers={"content-type": "application/pdf"})
        if path.endswith("breve-trop-courte"):
            return httpx.Response(200, text="<html><body>boum</body></html>", headers={"content-type": "text/html"})
        return httpx.Response(200, text=article, headers={"content-type": "text/html; charset=utf-8"})

    import newsletter_pipeline.collect as collect_mod
    real = collect_mod.extract_article

    def exploding(html, url):
        if url.endswith("breve-trop-courte"):
            raise RuntimeError("extraction impossible")
        return real(html, url)

    monkeypatch.setattr(collect_mod, "extract_article", exploding)
    collector = Collector(conn, settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    collector.sync_from_yaml()
    report = collector.collect_source(db.get_source(conn, "Page test"))
    assert report.error is None
    assert report.inserted == 1 and report.skipped == 2  # PDF ignoré, extraction en erreur isolée
    assert conn.execute("SELECT url FROM items").fetchone()["url"].endswith("lettre-de-mission-clause-ia")


def test_page_source_discovers_new_links_beyond_known_ones(conn, settings, workdir):
    settings.max_links_per_page = 1
    settings.sources_file = write_sources_yaml(workdir / "s.yaml", with_broken=False, extra="""
  - name: Page test
    url: https://blog.page-test.fr/blog/
    kind: page
    category: presse_pro
""")
    requests: list[str] = []
    collector = Collector(conn, settings, client=_mock_client(requests))
    collector.sync_from_yaml()
    source = db.get_source(conn, "Page test")
    assert collector.collect_source(source).inserted == 1
    assert requests[-1].endswith("revision-assistee-par-ia")
    requests.clear()
    assert collector.collect_source(source).inserted == 1  # le 1er lien est connu : on passe au suivant
    assert requests == ["/blog/", "/blog/2026/10/lettre-de-mission-clause-ia"]
