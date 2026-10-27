"""Clients HTTP (httpx.MockTransport) : requêtes, pagination, exclusions, enregistrement en base."""
from datetime import date

import httpx

from veille_marches import db
from veille_marches.collectors import active_cpv_prefixes, run_collect
from veille_marches.collectors.base import CollectorError, ods_iter_records
from veille_marches.collectors.boamp import BoampCollector, build_where
from veille_marches.collectors.decp import DecpCollector
from veille_marches.collectors.ted import TedCollector
from veille_marches.mapping import BOAMP_MAPPING, DECP_MAPPING
from veille_marches.models import Subscriber

SINCE = date(2026, 10, 25)


def test_boamp_collector_paginates_and_filters(settings, apis):
    mapping = dict(BOAMP_MAPPING, page_size=2)
    collector = BoampCollector(settings, client=apis.client(), mapping=mapping)
    result = collector.fetch(SINCE, ["773"], limit=50)
    assert result.fetched == 5 and result.kept == 3 and result.excluded == 2 and result.requests == 3
    assert [n.source_id for n in result.notices] == ["26-145201", "26-145377", "26-145622"]
    first = apis.requests[0]
    assert first.url.path == "/api/explore/v2.1/catalog/datasets/boamp/records"
    assert first.url.params["where"] == "dateparution >= date'2026-10-25'"
    assert first.url.params["order_by"] == "dateparution desc"
    assert [r.url.params["offset"] for r in apis.requests] == ["0", "2", "4"]
    assert "veille-marches" not in first.headers.get("user-agent", "veille-marches")  # client fourni par le test


def test_boamp_limit_and_server_side_cpv(settings, apis):
    collector = BoampCollector(settings, client=apis.client())
    result = collector.fetch(SINCE, [], limit=2)
    assert result.fetched == 2 and result.requests == 1 and apis.requests[0].url.params["limit"] == "2"
    where = build_where(SINCE, ["773", "452"], BOAMP_MAPPING, server_side_cpv=True)
    assert where == "dateparution >= date'2026-10-25' AND (search(donnees, \"773\") OR search(donnees, \"452\"))"


def test_boamp_api_key_header(settings, apis):
    settings = settings.model_copy(update={"boamp_api_key": "secret"})
    BoampCollector(settings, client=apis.client()).fetch(SINCE, ["773"], limit=5)
    assert apis.requests[0].headers["authorization"] == "Apikey secret"


def test_ods_iter_records_v2_0_shape_and_errors(settings):
    def handler(request):
        if request.url.path.endswith("/old/records"):
            return httpx.Response(200, json={"records": [{"record": {"fields": {"id": "1"}}}]})
        return httpx.Response(503, text="maintenance")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = list(ods_iter_records(client, "https://x.test/api/explore/v2.1", "old", limit=10))
    assert rows == [{"id": "1"}]
    try:
        list(ods_iter_records(client, "https://x.test/api/explore/v2.1", "down", limit=10))
    except CollectorError as e:
        assert "503" in str(e)
    else:
        raise AssertionError("CollectorError attendue")


def test_ted_collector_query_and_pagination(settings, apis):
    settings = settings.model_copy(update={"ted_page_size": 2, "ted_api_key": "k"})
    result = TedCollector(settings, client=apis.client()).fetch(SINCE, ["773"], limit=100)
    assert result.fetched == 4 and result.kept == 2 and result.excluded == 2 and result.requests == 2
    assert [n.source_id for n in result.notices] == ["650123-2026", "651402-2026"]
    bodies = apis.ted_bodies()
    assert bodies[0]["query"] == ("(classification-cpv=773*) AND place-of-performance=FRA"
                                  " AND publication-date>=20261025")
    assert bodies[0]["page"] == 1 and bodies[1]["page"] == 2 and bodies[0]["limit"] == 2
    assert "publication-number" in bodies[0]["fields"] and bodies[0]["scope"] == "ACTIVE"
    req = apis.requests[0]
    assert req.method == "POST" and req.url.path == "/v3/notices/search"
    assert req.headers["authorization"] == "Bearer k"


def test_ted_collector_http_error(settings, apis):
    apis.fail_hosts.add("api.ted.europa.eu")
    try:
        TedCollector(settings, client=apis.client()).fetch(SINCE, ["773"], limit=10)
    except CollectorError as e:
        assert "500" in str(e)
    else:
        raise AssertionError("CollectorError attendue")


def test_decp_collector(settings, apis):
    result = DecpCollector(settings, client=apis.client()).fetch(SINCE, ["773"], limit=100)
    assert result.fetched == 6 and result.kept == 6 and not result.notices
    where = apis.requests[0].url.params["where"]
    assert where == "datenotification >= date'2026-10-25' AND (startswith(codecpv, \"773\"))"
    assert apis.requests[0].url.path == "/api/explore/v2.1/catalog/datasets/decp-v3/records"
    assert DECP_MAPPING["cpv_field"] == "codecpv"
    holders = {a.holder_label for a in result.awards}
    assert "Parcs et Jardins du Rhône SARL" in holders


def test_run_collect_stores_and_dedupes(conn, settings, apis, now):
    results = run_collect(conn, settings, since_days=2, limit=100, client=apis.client(), now=now)
    by_source = {r.source: r for r in results}
    assert by_source["boamp"].inserted == 3 and by_source["ted"].inserted == 2 and by_source["decp"].inserted == 6
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM awards").fetchone()[0] == 6
    # seconde collecte : rien de nouveau, pas de doublon
    again = run_collect(conn, settings, since_days=2, limit=100, client=apis.client(), now=now)
    assert all(r.inserted == 0 for r in again)
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 5
    runs = conn.execute("SELECT source, fetched, inserted, error FROM collect_runs ORDER BY id").fetchall()
    assert len(runs) == 6 and runs[0]["fetched"] == 5 and runs[0]["inserted"] == 3 and runs[0]["error"] is None
    # la date de départ dépend de since_days
    assert apis.requests[0].url.params["where"].startswith("dateparution >= date'2026-10-25'")


def test_run_collect_dry_run_and_partial_failure(conn, settings, apis, now):
    apis.fail_hosts.add("api.ted.europa.eu")
    results = run_collect(conn, settings, sources=["boamp", "ted"], limit=100, dry_run=True,
                          client=apis.client(), now=now)
    assert results[0].kept == 3 and results[0].inserted == 0
    assert results[1].error and "500" in results[1].error
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM collect_runs").fetchone()[0] == 0
    results = run_collect(conn, settings, sources=["boamp", "ted"], limit=100, client=apis.client(), now=now)
    assert results[0].inserted == 3 and results[1].error
    errors = conn.execute("SELECT error FROM collect_runs WHERE source = 'ted'").fetchone()
    assert "500" in errors["error"]


def test_active_cpv_prefixes_from_subscribers(conn, settings):
    assert active_cpv_prefixes(conn, settings) == ["773"]
    db.add_subscriber(conn, Subscriber(email="a@b.fr", cpv_prefixes=["452", "773"]))
    db.add_subscriber(conn, Subscriber(email="c@d.fr", cpv_prefixes=["773", "909"], active=False))
    assert active_cpv_prefixes(conn, settings) == ["452", "773"]
