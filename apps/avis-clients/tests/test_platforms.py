"""P1-4 : plateformes d'avis Facebook et Tripadvisor — fabrique par plateforme, chiffrement des jetons, clients
sur `httpx.MockTransport` (pagination, erreurs 4xx/5xx, jeton expiré), liaison et isolation entre comptes,
poll multi-plateformes avec MockLLM, flux « réponse à copier » Tripadvisor, page publique, rapport, CLI,
migration 003. Aucun appel réseau."""
import json
import re
import shutil
import sqlite3

import httpx
import pytest
from conftest import FIXTURES, TEST_TOKENS_KEY, create_establishment, flash_of, login, smart_llm
from core.db import migrate
from core.llm import MockLLM
from core.mail import ConsoleMailer
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from avis_clients.crypto import TokenCipher, TokenKeyError, generate_key
from avis_clients.db import MIGRATIONS_DIR, Database
from avis_clients.facebook import (
    FacebookAuthError,
    FacebookError,
    FacebookReview,
    LiveFacebookClient,
    MockFacebookClient,
)
from avis_clients.gbp import GoogleAdapter, LiveGBPClient, MockGBPClient
from avis_clients.platforms import PlatformAuthError, build_platform_clients
from avis_clients.repo import (
    SourceConflict,
    get_establishment,
    get_review,
    get_source,
    list_reviews,
    list_sources,
    update_establishment,
    upsert_source,
)
from avis_clients.reports import compute_monthly_stats, send_monthly_reports
from avis_clients.reviews import poll_reviews
from avis_clients.services import build_services
from avis_clients.settings import AppSettings
from avis_clients.sources import SourceLinkError, link_source
from avis_clients.tripadvisor import (
    LiveTripadvisorClient,
    MockTripadvisorClient,
    TripadvisorAuthError,
    TripadvisorError,
    TripadvisorReview,
    management_url,
    safe_tripadvisor_url,
)
from avis_clients.web import create_app

FB_PAGE = "111222333444555"
TA_LOCATION = "7654321"


def _link_all(client, est_id, token="EAAB-test-token"):
    r = client.post(f"/app/establishments/{est_id}/sources/facebook",
                    data={"external_id": FB_PAGE, "credentials": token})
    assert r.status_code == 303 and "Facebook relié" in flash_of(r), flash_of(r)
    r = client.post(f"/app/establishments/{est_id}/sources/tripadvisor", data={"external_id": TA_LOCATION})
    assert r.status_code == 303 and "Tripadvisor relié" in flash_of(r), flash_of(r)


def _reviews(services, est_id):
    with services.db.session() as conn:
        return {(r.platform, r.external_id): r for r in list_reviews(conn, [est_id], limit=100)}


# ------------------------------------------------------------------------------------------
# Fabrique, chiffrement, réglages
# ------------------------------------------------------------------------------------------
def test_platform_factory_builds_one_adapter_per_platform(tmp_path):
    base = dict(_env_file=None, llm_provider="mock", data_dir=tmp_path, gbp_fixtures_file=FIXTURES / "gbp_reviews.json",
                facebook_fixtures_file=FIXTURES / "facebook_ratings.json",
                tripadvisor_fixtures_file=FIXTURES / "tripadvisor_reviews.json")
    clients = build_platform_clients(AppSettings(**base))
    assert set(clients) == {"google", "facebook", "tripadvisor"}
    assert all(c.platform == p and c.name == "mock" for p, c in clients.items())
    assert isinstance(clients["google"], GoogleAdapter) and isinstance(clients["google"].gbp, MockGBPClient)
    assert isinstance(clients["facebook"], MockFacebookClient)
    assert isinstance(clients["tripadvisor"], MockTripadvisorClient)
    assert clients["google"].can_reply and clients["facebook"].can_reply and not clients["tripadvisor"].can_reply
    live = build_platform_clients(AppSettings(**base, gbp_mode="live", facebook_mode="live", tripadvisor_mode="live",
                                              tokens_key=TEST_TOKENS_KEY, tripadvisor_api_key="k"))
    assert isinstance(live["google"].gbp, LiveGBPClient) and live["google"].name == "live"
    assert isinstance(live["facebook"], LiveFacebookClient) and isinstance(live["tripadvisor"], LiveTripadvisorClient)


def test_token_cipher_roundtrip_and_missing_key():
    cipher = TokenCipher(TEST_TOKENS_KEY)
    enc = cipher.encrypt("EAAB-secret")
    assert enc != "EAAB-secret" and "EAAB" not in enc and cipher.decrypt(enc) == "EAAB-secret"
    disabled = TokenCipher(None)
    assert not disabled.enabled and TokenCipher("  ").enabled is False
    with pytest.raises(TokenKeyError, match="TOKENS_KEY manquant"):
        disabled.encrypt("x")
    with pytest.raises(TokenKeyError, match="TOKENS_KEY manquant"):
        disabled.decrypt(enc)
    with pytest.raises(TokenKeyError, match="a changé"):
        TokenCipher(generate_key()).decrypt(enc)
    with pytest.raises(TokenKeyError, match="invalide"):
        TokenCipher("pas-une-cle")


def test_live_modes_require_their_secrets_at_startup(tmp_path):
    base = dict(_env_file=None, data_dir=tmp_path, llm_provider="mock")
    with pytest.raises(ValueError, match="TOKENS_KEY"):
        AppSettings(**base, facebook_mode="live")
    with pytest.raises(ValueError, match="TRIPADVISOR_API_KEY"):
        AppSettings(**base, tripadvisor_mode="live")
    with pytest.raises(ValueError, match="TOKENS_KEY invalide"):
        AppSettings(**base, tokens_key="court")
    AppSettings(**base, facebook_mode="live", tokens_key=TEST_TOKENS_KEY, tripadvisor_mode="live",
                tripadvisor_api_key="k")


# ------------------------------------------------------------------------------------------
# Facebook
# ------------------------------------------------------------------------------------------
def test_facebook_recommendations_are_converted_to_stars():
    data = json.loads((FIXTURES / "facebook_ratings.json").read_text(encoding="utf-8"))["ratings"]
    reviews = [FacebookReview.from_api(d, FB_PAGE) for d in data]
    assert [r.rating for r in reviews] == [5, 5, 1, 4]
    assert reviews[0].rating_note is None
    assert "positive" in reviews[1].rating_note and "5 étoiles" in reviews[1].rating_note
    assert "negative" in reviews[2].rating_note and "1 étoile." in reviews[2].rating_note
    assert reviews[3].author == "Anonyme" and reviews[3].text == "" and reviews[3].rating_note is None
    assert reviews[0].name == f"{FB_PAGE}_1001" and reviews[0].review_id == f"{FB_PAGE}_1001"
    # avis sans publication (story masquée) : identifiant de repli stable, pas de cible de réponse ;
    # ni note ni recommandation : 3 étoiles ; un booléen n'est pas une note
    r = FacebookReview.from_api({"reviewer": {"id": "9"}, "created_time": "2026-10-01T00:00:00+0000"}, FB_PAGE)
    assert r.rating == 3 and r.review_id == "9:2026-10-01T00:00:00+0000" and r.name == ""
    assert "3 étoiles" in r.rating_note
    boolean = FacebookReview.from_api({"rating": True, "recommendation_type": "positive", "created_time": "x"}, FB_PAGE)
    assert boolean.rating == 5


def _facebook_transport(calls, *, token="tok", auth_error=False):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if auth_error or request.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(400, json={"error": {"message": "Error validating access token: Session has expired",
                                                       "type": "OAuthException", "code": 190}})
        path = request.url.path
        if path.endswith("/ratings") and "after" not in request.url.params:
            assert request.url.params["fields"].startswith("reviewer{name,id},rating,recommendation_type")
            return httpx.Response(200, json={
                "data": [{"reviewer": {"name": "A", "id": "1"}, "rating": 5, "recommendation_type": "positive",
                          "review_text": "Top", "created_time": "2026-10-01T00:00:00+0000",
                          "open_graph_story": {"id": f"{FB_PAGE}_1"}}],
                "paging": {"cursors": {"after": "c2"},
                           "next": f"https://graph.facebook.com/v21.0/{FB_PAGE}/ratings?fields=x&limit=100&after=c2"}})
        if path.endswith("/ratings"):
            return httpx.Response(200, json={
                "data": [{"reviewer": {"name": "B", "id": "2"}, "recommendation_type": "negative",
                          "review_text": "Bof", "created_time": "2026-10-02T00:00:00+0000",
                          "open_graph_story": {"id": f"{FB_PAGE}_2"}}],
                "paging": {"cursors": {"after": "c3"}}})
        if path.endswith("/comments") and request.method == "POST":
            form = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(200, json={"id": f"{path.split('/')[-2]}_c1", "echo": form["message"]})
        if path.endswith("/me"):
            return httpx.Response(200, json={"id": FB_PAGE, "name": "Boulangerie Test (Page)"})
        return httpx.Response(404, json={"error": {"message": "unknown path", "code": 803}})
    return httpx.MockTransport(handler)


def test_facebook_live_client_paginates_replies_and_verifies_page():
    calls = []
    client = LiveFacebookClient(transport=_facebook_transport(calls))
    reviews = client.list_ratings(FB_PAGE, "tok")
    assert [r.review_id for r in reviews] == [f"{FB_PAGE}_1", f"{FB_PAGE}_2"] and reviews[1].rating == 1
    assert len(calls) == 2 and calls[1].url.params["after"] == "c2"
    assert calls[0].url.host == "graph.facebook.com" and calls[0].url.path == f"/v21.0/{FB_PAGE}/ratings"
    assert calls[0].headers["authorization"] == "Bearer tok" and "tok" not in str(calls[0].url)
    out = client.comment(f"{FB_PAGE}_1", "tok", "Merci !")
    assert out["echo"] == "Merci !" and calls[-1].method == "POST"
    assert calls[-1].url.path == f"/v21.0/{FB_PAGE}_1/comments"
    assert client.get_page(FB_PAGE, "tok")["name"] == "Boulangerie Test (Page)"
    assert client.verify_source(FB_PAGE, "tok")["public_url"] == f"https://www.facebook.com/{FB_PAGE}/reviews/"
    with pytest.raises(FacebookError, match="appartient à la Page"):
        client.get_page("999999999", "tok")  # un jeton de Page ne prouve que sa propre Page
    with pytest.raises(FacebookError, match="invalide"):
        client.list_ratings("../x", "tok")
    with pytest.raises(FacebookError, match="identifiant de publication"):
        client.comment("", "tok", "x")
    with pytest.raises(ValueError):
        LiveFacebookClient(graph_version="../v1")


def test_facebook_live_client_wraps_errors():
    with pytest.raises(FacebookAuthError, match="jeton de Page refusé"):
        LiveFacebookClient(transport=_facebook_transport([], auth_error=True)).list_ratings(FB_PAGE, "tok")
    assert isinstance(FacebookAuthError("x"), PlatformAuthError)
    client = LiveFacebookClient(transport=_facebook_transport([]))
    with pytest.raises(FacebookAuthError):
        client.list_ratings(FB_PAGE, "autre-jeton")
    with pytest.raises(FacebookAuthError, match="aucun jeton"):
        client.list_ratings(FB_PAGE, None)

    def server_error(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(FacebookError, match="HTTP 500") as exc:
        LiveFacebookClient(transport=httpx.MockTransport(server_error)).list_ratings(FB_PAGE, "tok")
    assert not isinstance(exc.value, FacebookAuthError)

    def network_error(request):
        raise httpx.ConnectError("réseau coupé")

    with pytest.raises(FacebookError, match="injoignable"):
        LiveFacebookClient(transport=httpx.MockTransport(network_error)).list_ratings(FB_PAGE, "tok")

    def forbidden(request):  # permission manquante : erreur simple, pas un jeton expiré
        return httpx.Response(403, json={"error": {"message": "(#10) Permission denied", "code": 10,
                                                   "type": "FacebookApiException"}})

    with pytest.raises(FacebookError, match="Permission denied") as exc:
        LiveFacebookClient(transport=httpx.MockTransport(forbidden)).comment(f"{FB_PAGE}_1", "tok", "x")
    assert not isinstance(exc.value, FacebookAuthError)


# ------------------------------------------------------------------------------------------
# Tripadvisor
# ------------------------------------------------------------------------------------------
def test_tripadvisor_review_parsing_and_safe_urls():
    data = json.loads((FIXTURES / "tripadvisor_reviews.json").read_text(encoding="utf-8"))["reviews"]
    reviews = [TripadvisorReview.from_api(d, TA_LOCATION) for d in data]
    assert [r.review_id for r in reviews] == ["1", "2", "3"] and [r.rating for r in reviews] == [5, 2, 4]
    assert reviews[0].reply_text == "Merci Camille !" and reviews[0].reply_time == "2026-10-07T09:00:00Z"
    assert reviews[0].text == "Une adresse à garder\nPain au levain superbe." and reviews[0].author == "Camille_L"
    assert reviews[0].name.startswith("https://www.tripadvisor.fr/ShowUserReviews")
    assert reviews[2].name == ""  # URL hors domaine Tripadvisor écartée
    assert management_url(reviews[2].name) == "https://www.tripadvisor.fr/Owners"
    assert management_url(reviews[0].name) == reviews[0].name
    assert safe_tripadvisor_url("http://www.tripadvisor.fr/x") is None
    assert safe_tripadvisor_url("https://tripadvisor.com.evil.example/x") is None
    assert safe_tripadvisor_url("https://evil.example/?u=https://www.tripadvisor.fr") is None
    assert safe_tripadvisor_url("https://www.tripadvisor.co.uk/x") == "https://www.tripadvisor.co.uk/x"
    assert safe_tripadvisor_url("https://tripadvisor.com/x") == "https://tripadvisor.com/x"


def _tripadvisor_transport(calls, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params["key"] == "cle-test" and request.url.params["language"] == "fr"
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        if request.url.path.endswith("/reviews"):
            data = json.loads((FIXTURES / "tripadvisor_reviews.json").read_text(encoding="utf-8"))["reviews"]
            return httpx.Response(200, json={"data": data})
        if request.url.path.endswith("/details"):
            return httpx.Response(200, json={"location_id": TA_LOCATION, "name": "Boulangerie Test",
                                             "web_url": "https://www.tripadvisor.fr/Restaurant_Review-d7654321.html",
                                             "write_review": "https://www.tripadvisor.fr/UserReviewEdit-d7654321.html"})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def test_tripadvisor_live_client_reads_reviews_and_wraps_errors():
    calls = []
    client = LiveTripadvisorClient("cle-test", transport=_tripadvisor_transport(calls))
    reviews = client.list_location_reviews(TA_LOCATION)
    assert len(reviews) == 3 and calls[0].url.host == "api.content.tripadvisor.com"
    assert calls[0].url.path == f"/api/v1/location/{TA_LOCATION}/reviews"
    assert client.verify_source(TA_LOCATION, None) == {
        "id": TA_LOCATION, "name": "Boulangerie Test",
        "public_url": "https://www.tripadvisor.fr/UserReviewEdit-d7654321.html"}
    assert not client.can_reply
    with pytest.raises(TripadvisorError, match="pas d'API de réponse"):
        client.publish_reply(None, None, "x", "y")
    with pytest.raises(TripadvisorError, match="invalide"):
        client.list_location_reviews("abc")
    with pytest.raises(TripadvisorAuthError, match="clé Content API refusée"):
        LiveTripadvisorClient("cle-test", transport=_tripadvisor_transport([], 401)).list_location_reviews(TA_LOCATION)
    with pytest.raises(TripadvisorError, match="quota"):
        LiveTripadvisorClient("cle-test", transport=_tripadvisor_transport([], 429)).list_location_reviews(TA_LOCATION)
    with pytest.raises(TripadvisorError, match="HTTP 500"):
        LiveTripadvisorClient("cle-test", transport=_tripadvisor_transport([], 500)).get_location(TA_LOCATION)


# ------------------------------------------------------------------------------------------
# Liaison des sources et isolation entre comptes
# ------------------------------------------------------------------------------------------
def test_link_facebook_and_tripadvisor_sources_from_settings(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id, token="EAAB-secret-token")
    with services.db.session() as conn:
        fb = get_source(conn, establishment_id, "facebook")
        ta = get_source(conn, establishment_id, "tripadvisor")
        assert [s.platform for s in list_sources(conn, establishment_id)] == ["google", "facebook", "tripadvisor"]
    assert fb.display_name == "Boulangerie Test (Page)" and fb.public_url == f"https://www.facebook.com/{FB_PAGE}/reviews/"
    assert fb.credentials_enc and "EAAB" not in fb.credentials_enc
    assert services.cipher.decrypt(fb.credentials_enc) == "EAAB-secret-token"
    assert ta.display_name == "Boulangerie Test (Tripadvisor)" and ta.credentials_enc is None
    assert ta.public_url.startswith("https://www.tripadvisor.fr/UserReviewEdit")
    page = logged_client.get(f"/app/establishments/{establishment_id}").text
    assert "Boulangerie Test (Page)" in page and "chiffré" in page
    assert "EAAB-secret-token" not in page and fb.credentials_enc not in page
    r = logged_client.post(f"/app/establishments/{establishment_id}/sources/facebook", data={"external_id": "../x"})
    assert "invalide" in flash_of(r)
    r = logged_client.post(f"/app/establishments/{establishment_id}/sources/tripadvisor", data={"external_id": "d12"})
    assert "invalide" in flash_of(r)
    assert logged_client.post(f"/app/establishments/{establishment_id}/sources/google",
                              data={"external_id": "x"}).status_code == 404
    r = logged_client.post(f"/app/establishments/{establishment_id}/sources/facebook/unlink")
    assert "délié" in flash_of(r)
    with services.db.session() as conn:
        assert get_source(conn, establishment_id, "facebook") is None
        assert get_source(conn, establishment_id, "tripadvisor") is not None


def test_source_link_refused_for_id_linked_by_another_account(logged_client, establishment_id, services, app):
    _link_all(logged_client, establishment_id)
    with TestClient(app, follow_redirects=False) as other:
        login(other, services, "autre@exemple.fr")
        other_id = create_establishment(other, "Autre Commerce", "ChIJautre00000000001")
        r = other.post(f"/app/establishments/{other_id}/sources/facebook",
                       data={"external_id": FB_PAGE, "credentials": "t"})
        assert "déjà reliée à un autre établissement" in flash_of(r)
        r = other.post(f"/app/establishments/{other_id}/sources/tripadvisor", data={"external_id": TA_LOCATION})
        assert "déjà reliée" in flash_of(r)
        # l'établissement d'un autre compte est inaccessible
        assert other.post(f"/app/establishments/{establishment_id}/sources/facebook",
                          data={"external_id": "123456"}).status_code == 404
    with services.db.session() as conn:
        assert [s.platform for s in list_sources(conn, other_id)] == ["google"]
        est_other = get_establishment(conn, other_id)
        with pytest.raises(SourceLinkError, match="déjà reliée"):
            link_source(conn, services, est_other, "facebook", FB_PAGE)
        with pytest.raises(SourceConflict):
            upsert_source(conn, establishment_id=other_id, platform="facebook", external_id=FB_PAGE)
        with pytest.raises(sqlite3.IntegrityError):  # contrainte UNIQUE : dernière ligne de défense
            conn.execute("INSERT INTO review_sources (establishment_id, platform, external_id, created_at)"
                         " VALUES (?, 'facebook', ?, 'x')", (other_id, FB_PAGE))


def test_linking_with_token_requires_tokens_key(logged_client, establishment_id, services):
    services.cipher = TokenCipher(None)
    r = logged_client.post(f"/app/establishments/{establishment_id}/sources/facebook",
                           data={"external_id": FB_PAGE, "credentials": "EAAB"})
    assert "TOKENS_KEY manquant" in flash_of(r)
    with services.db.session() as conn:
        assert get_source(conn, establishment_id, "facebook") is None
    # en mode démonstration, sans jeton, rien à chiffrer : la liaison passe
    r = logged_client.post(f"/app/establishments/{establishment_id}/sources/facebook", data={"external_id": FB_PAGE})
    assert "Facebook relié" in flash_of(r)


def test_google_location_is_mirrored_in_sources(logged_client, establishment_id, services, app):
    with services.db.session() as conn:
        assert get_source(conn, establishment_id, "google").external_id == "accounts/mock/locations/boulangerie-test"
        update_establishment(conn, establishment_id, google_location_name="accounts/1/locations/2")
        src = get_source(conn, establishment_id, "google")
        assert src.external_id == "accounts/1/locations/2" and src.status == "active"
        update_establishment(conn, establishment_id, google_location_name=None)
        assert list_sources(conn, establishment_id) == []
        update_establishment(conn, establishment_id, google_location_name="accounts/1/locations/2")
    with TestClient(app, follow_redirects=False) as other:
        login(other, services, "autre@exemple.fr")
        other_id = create_establishment(other, "Autre", "ChIJautre00000000001")
    with services.db.session() as conn:
        with pytest.raises(SourceConflict, match="fiche Google"):
            update_establishment(conn, other_id, google_location_name="accounts/1/locations/2")
        assert get_source(conn, other_id, "google").external_id == "accounts/mock/locations/autre"
        assert get_establishment(conn, other_id).google_location_name == "accounts/mock/locations/autre"


# ------------------------------------------------------------------------------------------
# Poll multi-plateformes
# ------------------------------------------------------------------------------------------
def test_poll_covers_all_linked_sources_with_isolated_counters(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    mails = len(services.mailer.sent)
    with services.db.session() as conn:
        summary = poll_reviews(conn, services)
    assert summary.establishments == 1 and summary.sources == 3 and summary.errors == []
    assert summary.fetched == 5 + 4 + 3 and summary.new == 12 and summary.drafts == 10
    assert summary.by_platform["google"]["fetched"] == 5 and summary.by_platform["facebook"]["new"] == 4
    assert summary.by_platform["tripadvisor"] == {"sources": 1, "fetched": 3, "new": 3, "updated": 0, "drafts": 2,
                                                  "errors": 0}
    # alertes ≤ 2 étoiles identiques sur chaque plateforme : Google r2 (1★), Facebook négative (1★), Tripadvisor 2★
    assert summary.alerts == 3 and len(services.mailer.sent) == mails + 3
    assert all("réponse à valider" in m.subject for m in services.mailer.sent[-3:])
    fb_alert = next(m for m in services.mailer.sent[-3:] if "Facebook" in m.html)
    assert "Recommandation Facebook sans note" in fb_alert.html and "Nadia" in fb_alert.html
    ta_alert = next(m for m in services.mailer.sent[-3:] if "Tripadvisor" in m.html)
    assert "ne permet pas de publier" in ta_alert.html
    reviews = _reviews(services, establishment_id)
    nadia = reviews[("facebook", f"{FB_PAGE}_1003")]
    assert nadia.rating == 1 and nadia.alerted_at and "désolés" in nadia.reply_draft.lower()
    assert "rembours" not in nadia.reply_draft.lower()
    julien = reviews[("facebook", f"{FB_PAGE}_1002")]
    assert julien.rating == 5 and "comptée 5 étoiles" in julien.rating_note
    assert julien.external_name == f"{FB_PAGE}_1002"
    assert reviews[("tripadvisor", "1")].reply_status == "published"
    assert reviews[("tripadvisor", "1")].reply_text == "Merci Camille !"
    assert reviews[("tripadvisor", "2")].reply_status == "draft" and reviews[("tripadvisor", "2")].alerted_at
    with services.db.session() as conn:
        sources = list_sources(conn, establishment_id)
        ev = conn.execute("SELECT payload_json FROM events WHERE kind = 'poll_done'"
                          " ORDER BY id DESC LIMIT 1").fetchone()
    assert all(s.status == "active" and s.last_synced_at and s.last_error is None for s in sources)
    assert json.loads(ev[0])["by_platform"]["facebook"]["new"] == 4
    # boîte de réception : badges, mention de conversion, filtres par plateforme
    page = logged_client.get("/app/inbox?status=all").text
    assert 'tag platform facebook' in page and 'tag platform tripadvisor' in page and "comptée 5 étoiles" in page
    assert "Toutes les plateformes" in page
    only_fb = logged_client.get("/app/inbox?status=all&platform=facebook").text
    assert "Nadia B." in only_fb and "Marie L." not in only_fb and "MarcD" not in only_fb
    assert logged_client.get("/app/inbox?status=all&platform=inconnue").status_code == 200
    assert "tag platform facebook" in logged_client.get("/app").text
    # second poll : rien de nouveau, Tripadvisor relu plus tard (quota), pas de nouvelle alerte
    with services.db.session() as conn:
        again = poll_reviews(conn, services)
    assert again.new == 0 and again.alerts == 0 and again.skipped_recent == 1 and again.sources == 2
    assert len(_reviews(services, establishment_id)) == 12


def test_poll_isolates_source_errors_and_marks_expired_token(tmp_path):
    calls = []
    state = {"auth_error": True}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if state["auth_error"]:
            return httpx.Response(400, json={"error": {"message": "Session has expired", "type": "OAuthException",
                                                       "code": 190}})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": FB_PAGE, "name": "Page Live"})
        if request.url.path.endswith("/ratings"):
            return httpx.Response(200, json={"data": [
                {"reviewer": {"name": "Live U", "id": "1"}, "rating": 5, "recommendation_type": "positive",
                 "review_text": "Super", "created_time": "2026-10-01T00:00:00+0000",
                 "open_graph_story": {"id": f"{FB_PAGE}_77"}}]})
        return httpx.Response(404, json={})

    settings = AppSettings(
        _env_file=None, llm_provider="mock", mail_provider="console", sms_provider="dry-run", gbp_mode="mock",
        facebook_mode="live", tokens_key=TEST_TOKENS_KEY, data_dir=tmp_path / "data", db_path=tmp_path / "live.db",
        session_secret="secret-de-test", app_base_url="http://testserver",
        gbp_fixtures_file=FIXTURES / "gbp_reviews.json",
        tripadvisor_fixtures_file=FIXTURES / "tripadvisor_reviews.json",
    )
    services = build_services(settings, mailer=ConsoleMailer(quiet=True), llm=MockLLM(responses=smart_llm),
                              gbp=MockGBPClient(fixtures_path=FIXTURES / "gbp_reviews.json"),
                              facebook=LiveFacebookClient(transport=httpx.MockTransport(handler)))
    with TestClient(create_app(services=services), follow_redirects=False) as client:
        login(client, services)
        est_id = create_establishment(client)
        # liaison en live : jeton obligatoire, vérifié par GET /me
        r = client.post(f"/app/establishments/{est_id}/sources/facebook", data={"external_id": FB_PAGE})
        assert "requis" in flash_of(r)
        r = client.post(f"/app/establishments/{est_id}/sources/facebook",
                        data={"external_id": FB_PAGE, "credentials": "tok-expire"})
        assert "jeton de Page refusé" in flash_of(r)
        state["auth_error"] = False
        r = client.post(f"/app/establishments/{est_id}/sources/facebook",
                        data={"external_id": FB_PAGE, "credentials": "tok-ok"})
        assert "Facebook relié : Page Live" in flash_of(r)
        state["auth_error"] = True  # le jeton expire ensuite
        with services.db.session() as conn:
            summary = poll_reviews(conn, services)
        assert summary.by_platform["google"]["fetched"] == 5 and summary.new == 5  # Google n'est pas affecté
        assert summary.by_platform["facebook"]["errors"] == 1 and len(summary.errors) == 1
        assert "jeton de Page refusé" in summary.errors[0]
        with services.db.session() as conn:
            fb = get_source(conn, est_id, "facebook")
        assert fb.status == "error" and "jeton" in fb.last_error and fb.last_synced_at is None
        assert "jeton de Page refusé" in client.get(f"/app/establishments/{est_id}").text
        r = client.post("/app/inbox/sync")
        assert "Erreurs" in flash_of(r) and "Facebook" in flash_of(r)
        # jeton renouvelé : la source repasse active et les avis arrivent
        state["auth_error"] = False
        with services.db.session() as conn:
            summary = poll_reviews(conn, services)
        assert summary.errors == [] and summary.by_platform["facebook"]["new"] == 1
        with services.db.session() as conn:
            fb = get_source(conn, est_id, "facebook")
        assert fb.status == "active" and fb.last_error is None and fb.last_synced_at
        assert any(c.headers.get("authorization") == "Bearer tok-ok" and c.url.path.endswith("/ratings") for c in calls)
    # clé de chiffrement changée : erreur lisible sur la source Facebook, les autres sources continuent
    services.cipher = TokenCipher(generate_key())
    with services.db.session() as conn:
        summary = poll_reviews(conn, services)
    assert "TOKENS_KEY a changé" in summary.errors[0] and summary.by_platform["google"]["fetched"] == 5


def test_poll_platform_filter_and_tripadvisor_interval(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    with services.db.session() as conn:
        only_fb = poll_reviews(conn, services, platforms=["facebook"])
        assert set(only_fb.by_platform) == {"facebook"} and only_fb.fetched == 4 and only_fb.errors == []
        with pytest.raises(ValueError, match="plateforme inconnue"):
            poll_reviews(conn, services, platforms=["yelp"])
        ta = poll_reviews(conn, services, platforms=["tripadvisor"])
        assert ta.fetched == 3 and ta.skipped_recent == 0
        ta2 = poll_reviews(conn, services, platforms=["tripadvisor"])
        assert ta2.fetched == 0 and ta2.skipped_recent == 1 and ta2.sources == 0
        forced = poll_reviews(conn, services, platforms=["tripadvisor"], force=True)
        assert forced.fetched == 3 and forced.skipped_recent == 0
        services.settings = services.settings.model_copy(update={"tripadvisor_poll_interval_min": 0})
        assert poll_reviews(conn, services, platforms=["tripadvisor"]).fetched == 3
    r = logged_client.post("/app/inbox/sync")
    assert "Google 5, Facebook 4, Tripadvisor 3" in flash_of(r)


def test_facebook_reply_is_posted_as_comment(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    with services.db.session() as conn:
        poll_reviews(conn, services)
    claire = _reviews(services, establishment_id)[("facebook", f"{FB_PAGE}_1001")]
    r = logged_client.post(f"/app/reviews/{claire.id}/publish", data={"text": "Merci Claire, à très vite !"},
                           headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Réponse publiée" in r.text
    assert services.facebook.replies[f"{FB_PAGE}_1001"]["message"] == "Merci Claire, à très vite !"
    with services.db.session() as conn:
        assert get_review(conn, claire.id).reply_status == "published"
        again = poll_reviews(conn, services, force=True)  # le commentaire est relu comme réponse existante
    assert again.new == 0 and again.drafts == 0
    assert _reviews(services, establishment_id)[("facebook", f"{FB_PAGE}_1001")].reply_status == "published"


def test_auto_publish_respects_platform_capabilities(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    with services.db.session() as conn:
        update_establishment(conn, establishment_id, auto_publish_positive=1)
        summary = poll_reviews(conn, services)
        skipped = [json.loads(row[0]) for row in
                   conn.execute("SELECT payload_json FROM events WHERE kind = 'auto_publish_skipped'")]
    reviews = _reviews(services, establishment_id)
    assert summary.auto_published == 5  # Google r1, r5 ; Facebook 1001, 1002, 1004 ; jamais Tripadvisor (pas d'API)
    assert reviews[("facebook", f"{FB_PAGE}_1002")].reply_status == "published"
    assert f"{FB_PAGE}_1002" in services.facebook.replies and f"{FB_PAGE}_1003" not in services.facebook.replies
    assert reviews[("tripadvisor", "3")].reply_status == "draft"
    assert any(e.get("reason") == "platform_no_reply_api" and e.get("platform") == "tripadvisor" for e in skipped)


# ------------------------------------------------------------------------------------------
# Tripadvisor : flux « réponse à copier »
# ------------------------------------------------------------------------------------------
def test_tripadvisor_copy_flow_and_manual_publication(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    with services.db.session() as conn:
        poll_reviews(conn, services)
    reviews = _reviews(services, establishment_id)
    marc = reviews[("tripadvisor", "2")]
    page = logged_client.get("/app/inbox?platform=tripadvisor").text
    assert "Copier la réponse et ouvrir Tripadvisor" in page and "J'ai publié la réponse sur Tripadvisor" in page
    assert f'data-open="{marc.external_name}"' in page  # page de l'avis (bouton « Répondre » côté propriétaire)
    card = page[page.index(f'id="review-{marc.id}"'):]
    card = card[:card.index("</article>")]
    assert ">Publier<" not in card and "/publish\"" not in card
    # publication par API refusée proprement : l'avis reste à valider, pas d'état « approuvé » bloquant
    r = logged_client.post(f"/app/reviews/{marc.id}/publish", data={"text": "Désolés"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "pas de publication par API" in r.text
    with services.db.session() as conn:
        assert get_review(conn, marc.id).reply_status == "draft"
    # confirmation manuelle
    r = logged_client.post(f"/app/reviews/{marc.id}/published-manually",
                           data={"text": "Désolés Marc, passez nous voir."}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "publiée sur Tripadvisor" in r.text and "publiée par vous" in r.text
    with services.db.session() as conn:
        review = get_review(conn, marc.id)
    assert review.reply_status == "published_manually" and review.reply_published_at
    assert review.reply_text == "Désolés Marc, passez nous voir."
    assert "MarcD" in logged_client.get("/app/inbox?status=published").text
    assert "MarcD" not in logged_client.get("/app/inbox?status=draft").text
    # texte vide refusé ; refusé aussi pour une plateforme qui publie par API
    emma = reviews[("tripadvisor", "3")]
    with services.db.session() as conn:
        conn.execute("UPDATE reviews SET reply_draft = '' WHERE id = ?", (emma.id,))
    r = logged_client.post(f"/app/reviews/{emma.id}/published-manually", data={"text": "  "},
                           headers={"HX-Request": "true"})
    assert "vide" in r.text
    google = reviews[("google", "r1")]
    r = logged_client.post(f"/app/reviews/{google.id}/published-manually", data={"text": "x"},
                           headers={"HX-Request": "true"})
    assert "utilisez « Publier »" in r.text
    with services.db.session() as conn:
        assert get_review(conn, google.id).reply_status == "draft"
    # le tableau de bord compte la réponse manuelle comme publiée (Google r3 + Tripadvisor 1 + manuelle)
    assert '<span class="num">3</span><span>réponse(s) publiée(s)' in logged_client.get("/app").text
    # le poll suivant la conserve
    with services.db.session() as conn:
        poll_reviews(conn, services, force=True)
        assert get_review(conn, marc.id).reply_status == "published_manually"


# ------------------------------------------------------------------------------------------
# Page publique, rapport mensuel
# ------------------------------------------------------------------------------------------
def test_public_page_offers_secondary_links_after_google(client, logged_client, establishment_id, services):
    assert "Laisser un avis sur Facebook" not in client.get("/r/boulangerie-test").text
    _link_all(logged_client, establishment_id)
    page = client.get("/r/boulangerie-test").text
    assert "Laisser un avis Google" in page and "quelle que soit votre note" in page
    assert f"https://www.facebook.com/{FB_PAGE}/reviews/" in page
    assert "https://www.tripadvisor.fr/UserReviewEdit-g187147-d7654321-Boulangerie_Test-Paris.html" in page
    assert (page.index("Laisser un avis Google") < page.index("Laisser un avis sur Facebook")
            < page.index("Laisser un avis sur Tripadvisor") < page.index("Nous écrire en privé"))
    # pas de lien quand l'URL publique de la plateforme est inconnue (fiche hors fixtures)
    logged_client.post(f"/app/establishments/{establishment_id}/sources/tripadvisor", data={"external_id": "999"})
    page = client.get("/r/boulangerie-test").text
    assert "Laisser un avis sur Tripadvisor" not in page and "Laisser un avis sur Facebook" in page


def test_monthly_report_is_broken_down_by_platform(logged_client, establishment_id, services):
    _link_all(logged_client, establishment_id)
    with services.db.session() as conn:
        poll_reviews(conn, services)
        stats = compute_monthly_stats(conn, get_establishment(conn, establishment_id), "2026-10")
    assert stats.count == 12 and list(stats.by_platform) == ["google", "facebook", "tripadvisor"]
    assert stats.by_platform["google"]["count"] == 5 and stats.by_platform["facebook"]["avg_rating"] == 3.75
    assert stats.by_platform["tripadvisor"]["replied"] == 1 and stats.replied == 2
    with services.db.session() as conn:
        results = send_monthly_reports(conn, services, month="2026-10")
    assert results[0]["reviews"] == 12
    html = services.mailer.sent[-1].html
    assert "Par plateforme" in html and "Facebook" in html and "Tripadvisor" in html
    assert "Par plateforme" in logged_client.get(f"/app/establishments/{establishment_id}/report?month=2026-10").text


# ------------------------------------------------------------------------------------------
# CLI et migration
# ------------------------------------------------------------------------------------------
def _cli_env(tmp_path, monkeypatch, **extra):
    from avis_clients import settings as settings_module

    env = {
        "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console", "SMS_PROVIDER": "dry-run", "GBP_MODE": "mock",
        "DATA_DIR": str(tmp_path / "data"), "DB_PATH": str(tmp_path / "cli.db"), "SESSION_SECRET": "x",
        "GBP_FIXTURES_FILE": str(FIXTURES / "gbp_reviews.json"),
        "FACEBOOK_FIXTURES_FILE": str(FIXTURES / "facebook_ratings.json"),
        "TRIPADVISOR_FIXTURES_FILE": str(FIXTURES / "tripadvisor_reviews.json"),
        "TOKENS_KEY": TEST_TOKENS_KEY, **extra,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    settings_module.get_settings.cache_clear()
    return settings_module


def _poll_json(output: str) -> dict:
    return json.loads(output[output.index("{"):output.rindex("}") + 1])


def test_cli_sources_and_poll_platform(tmp_path, monkeypatch):
    from avis_clients import cli

    settings_module = _cli_env(tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["demo", "--google-only"]).exit_code == 0
    r = runner.invoke(cli.app, ["sources", "list"])
    assert r.exit_code == 0 and "Google" in r.output and "Facebook" not in r.output
    token_file = tmp_path / "jeton.txt"
    token_file.write_text("EAAB-cli-token\n", encoding="utf-8")
    r = runner.invoke(cli.app, ["sources", "link", "1", "facebook", FB_PAGE, "--token-file", str(token_file)])
    assert r.exit_code == 0 and "relié à Facebook" in r.output and "mode mock" in r.output, r.output
    r = runner.invoke(cli.app, ["sources", "link", "1", "tripadvisor", TA_LOCATION])
    assert r.exit_code == 0 and "relié à Tripadvisor" in r.output, r.output
    assert runner.invoke(cli.app, ["sources", "link", "1", "yelp", "1"]).exit_code == 2
    assert runner.invoke(cli.app, ["sources", "link", "1", "facebook", "abc"]).exit_code == 1
    assert runner.invoke(cli.app, ["sources", "link", "99", "facebook", FB_PAGE]).exit_code == 1
    r = runner.invoke(cli.app, ["sources", "list"])
    assert "Facebook" in r.output and "chiffré" in r.output and "EAAB-cli-token" not in r.output
    r = runner.invoke(cli.app, ["poll-reviews", "--platform", "facebook"])
    assert r.exit_code == 0, r.output
    data = _poll_json(r.output)
    assert list(data["by_platform"]) == ["facebook"] and data["new"] == 4
    assert runner.invoke(cli.app, ["poll-reviews", "--platform", "yelp"]).exit_code == 2
    assert _poll_json(runner.invoke(cli.app, ["poll-reviews", "-p", "tripadvisor"]).output)["new"] == 3
    assert _poll_json(runner.invoke(cli.app, ["poll-reviews", "-p", "tripadvisor"]).output)["skipped_recent"] == 1
    forced = _poll_json(runner.invoke(cli.app, ["poll-reviews", "-p", "tripadvisor", "--force"]).output)
    assert forced["skipped_recent"] == 0 and forced["fetched"] == 3
    everything = _poll_json(runner.invoke(cli.app, ["poll-reviews"]).output)
    assert set(everything["by_platform"]) == {"google", "facebook"} and everything["skipped_recent"] == 1
    r = runner.invoke(cli.app, ["sources", "unlink", "1", "facebook"])
    assert r.exit_code == 0 and "délié" in r.output
    r = runner.invoke(cli.app, ["establishments"])
    assert "Tripadvisor" in r.output and "Facebook" not in r.output
    settings_module.get_settings.cache_clear()


def test_cli_demo_links_all_mock_platforms(tmp_path, monkeypatch):
    from avis_clients import cli

    settings_module = _cli_env(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli.app, ["demo"])
    assert r.exit_code == 0, r.output
    data = _poll_json(r.output)
    assert data["new"] == 12 and set(data["by_platform"]) == {"google", "facebook", "tripadvisor"}
    assert data["alerts"] == 3 and data["errors"] == []
    r = CliRunner().invoke(cli.app, ["demo"])  # rejouable : rien de nouveau, sources inchangées
    assert r.exit_code == 0 and _poll_json(r.output)["new"] == 0
    settings_module.get_settings.cache_clear()


def test_migration_003_backfills_google_sources_and_rebuilds_reviews(tmp_path):
    old_dir = tmp_path / "migrations_old"
    old_dir.mkdir()
    for name in ("001_init.sql", "002_review_draft_source.sql"):
        shutil.copy(MIGRATIONS_DIR / name, old_dir / name)
    db = Database(tmp_path / "old.db")
    conn = db.connect()
    assert migrate(conn, old_dir) == ["001_init.sql", "002_review_draft_source.sql"]
    conn.execute("INSERT INTO accounts (id, email, created_at, trial_ends_at)"
                 " VALUES (1, 'a@b.fr', '2026-01-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00')")
    for est_id, name, location in ((1, "A", "accounts/1/locations/9"), (2, "B", None)):
        conn.execute("INSERT INTO establishments (id, account_id, name, slug, google_location_name, review_url,"
                     " request_template, created_at) VALUES (?, 1, ?, ?, ?, 'u', 't', '2026-01-01T00:00:00+00:00')",
                     (est_id, name, name.lower(), location))
    conn.execute("INSERT INTO reviews (establishment_id, platform, external_id, author, rating, text, created_at,"
                 " fetched_at, reply_status, reply_draft, reply_draft_source) VALUES (1, 'google', 'r1', 'X', 4, 'ok',"
                 " '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 'draft', 'Merci', 'llm')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # ancien schéma : statut inconnu
        conn.execute("UPDATE reviews SET reply_status = 'published_manually'")
    conn.close()
    assert db.migrate() == ["003_review_sources.sql"]
    conn = db.connect()
    rows = conn.execute("SELECT establishment_id, platform, external_id, status FROM review_sources").fetchall()
    assert [tuple(r) for r in rows] == [(1, "google", "accounts/1/locations/9", "active")]
    row = conn.execute("SELECT * FROM reviews").fetchone()
    assert row["id"] == 1 and row["reply_draft_source"] == "llm" and row["rating_note"] is None
    assert row["reply_draft"] == "Merci" and row["reply_status"] == "draft"
    conn.execute("UPDATE reviews SET reply_status = 'published_manually', rating_note = 'n'")  # accepté désormais
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3
    with pytest.raises(sqlite3.IntegrityError):  # un identifiant externe = un seul établissement
        conn.execute("INSERT INTO review_sources (establishment_id, platform, external_id, created_at)"
                     " VALUES (2, 'google', 'accounts/1/locations/9', 'x')")
    with pytest.raises(sqlite3.IntegrityError):  # une source par plateforme et par établissement
        conn.execute("INSERT INTO review_sources (establishment_id, platform, external_id, created_at)"
                     " VALUES (1, 'google', 'accounts/1/locations/10', 'x')")
    with pytest.raises(sqlite3.IntegrityError):  # plateforme inconnue refusée
        conn.execute("INSERT INTO review_sources (establishment_id, platform, external_id, created_at)"
                     " VALUES (2, 'yelp', '1', 'x')")
    conn.execute("DELETE FROM establishments WHERE id = 1")  # cascade : sources et avis
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM review_sources").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
    assert re.match(r"\d{3}_", "003_review_sources.sql")
    conn.close()
