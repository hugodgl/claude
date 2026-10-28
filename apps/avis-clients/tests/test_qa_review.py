"""Tests ajoutés par la revue croisée QA-1 : chaque test met en évidence un défaut corrigé (voir REVIEW.md)."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from conftest import FIXTURES, create_establishment, flash_of, login, smart_llm
from core.llm import MockLLM
from core.mail import ConsoleMailer
from fastapi.testclient import TestClient

from avis_clients.billing import account_access, handle_stripe_event
from avis_clients.db import month_bounds_utc
from avis_clients.drafts import check_reply, generate_reply_draft
from avis_clients.gbp import GBPError, LiveGBPClient, MockGBPClient
from avis_clients.models import Account, Review
from avis_clients.repo import (
    add_optout,
    count_messages_in_month,
    get_account_by_email,
    get_establishment,
    insert_review,
    list_reviews,
    list_reviews_in_month,
    review_url_for_place,
    update_account,
    update_establishment,
)
from avis_clients.reports import MonthlyStats, generate_recommendations, is_valid_month
from avis_clients.reviews import create_draft, poll_reviews
from avis_clients.routes.auth import _safe_next
from avis_clients.services import build_services
from avis_clients.settings import AppSettings
from avis_clients.sms import normalize_phone, render_message, twilio_signature, validate_request_template
from avis_clients.web import create_app


def _reviews(services, est_id):
    with services.db.session() as conn:
        return {r.external_id: r for r in list_reviews(conn, [est_id], limit=100)}


# ------------------------------------------------------------------------------------------
# Sécurité
# ------------------------------------------------------------------------------------------
def test_session_secret_is_required_in_production(tmp_path):
    base = dict(_env_file=None, data_dir=tmp_path, llm_provider="mock")
    # en développement (http), le secret par défaut est toléré
    AppSettings(**base, app_base_url="http://localhost:8000")
    # en production (https), le secret par défaut, le placeholder du .env.example ou un secret court sont refusés
    for bad in ("change-me-en-production", "remplacez-par-une-longue-chaine-aleatoire", "court"):
        with pytest.raises(ValueError):
            AppSettings(**base, app_base_url="https://avis.exemple.fr", session_secret=bad)
    AppSettings(**base, app_base_url="https://avis.exemple.fr", session_secret="a" * 64)


def test_safe_next_blocks_open_redirects(logged_client):
    assert _safe_next("/app/inbox?status=all") == "/app/inbox?status=all"
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "", None):
        assert _safe_next(bad) == "/app", bad
    r = logged_client.get("/login?next=/\\evil.example")
    assert r.status_code == 303 and r.headers["location"] == "/app"


def test_login_is_throttled_per_email(client, services):
    before = len(services.mailer.sent)
    assert client.post("/login", data={"email": "lent@exemple.fr"}).status_code == 200
    assert client.post("/login", data={"email": "lent@exemple.fr"}).status_code == 200
    assert len(services.mailer.sent) == before + 1  # un seul email par minute et par adresse


def test_security_headers_and_no_store_on_private_pages(client, logged_client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "referrer-policy" in r.headers
    assert logged_client.get("/app").headers["cache-control"] == "no-store"
    assert logged_client.get("/billing").headers["cache-control"] == "no-store"


def _twilio_services(tmp_path, **overrides):
    values = dict(
        _env_file=None, llm_provider="mock", mail_provider="console", gbp_mode="mock",
        data_dir=tmp_path / "data", db_path=tmp_path / "tw.db", session_secret="secret-de-test",
        app_base_url="http://testserver", gbp_fixtures_file=FIXTURES / "gbp_reviews.json",
        sms_provider="twilio", twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from="+33700000000",
    )
    values.update(overrides)
    settings = AppSettings(**values)
    return build_services(settings, mailer=ConsoleMailer(quiet=True), llm=MockLLM(responses=smart_llm),
                          gbp=MockGBPClient(fixtures_path=FIXTURES / "gbp_reviews.json"))


def _optouts(services):
    with services.db.session() as conn:
        return [r["phone"] for r in conn.execute("SELECT phone FROM optouts")]


def test_sms_inbound_webhook_requires_twilio_signature(tmp_path):
    services = _twilio_services(tmp_path)
    with TestClient(create_app(services=services), follow_redirects=False) as client:
        params = {"From": "+33612345678", "Body": "STOP"}
        r = client.post("/webhooks/sms/inbound", data=params)
        assert r.status_code == 403 and _optouts(services) == []
        r = client.post("/webhooks/sms/inbound", data=params, headers={"X-Twilio-Signature": "bidon"})
        assert r.status_code == 403 and _optouts(services) == []

        url = "http://testserver/webhooks/sms/inbound"
        expected = base64.b64encode(hmac.new(b"tok", (url + "Body" + "STOP" + "From" + "+33612345678").encode(),
                                             hashlib.sha1).digest()).decode()
        assert twilio_signature("tok", url, params) == expected
        r = client.post("/webhooks/sms/inbound", data=params, headers={"X-Twilio-Signature": expected})
        assert r.status_code == 200 and r.headers["x-optout"] == "1" and _optouts(services) == ["+33612345678"]


def test_sms_inbound_webhook_shared_token_for_smsmode(tmp_path):
    settings = dict(sms_provider="smsmode", smsmode_api_key="k")
    services = _twilio_services(tmp_path, **settings)  # smsmode sans jeton partagé : refusé
    with TestClient(create_app(services=services), follow_redirects=False) as client:
        assert client.get("/webhooks/sms/inbound?numero=33633333333&message=STOP").status_code == 403
    services = _twilio_services(tmp_path, sms_webhook_token="jeton-secret", **settings)
    with TestClient(create_app(services=services), follow_redirects=False) as client:
        assert client.get("/webhooks/sms/inbound?numero=33633333333&message=STOP&token=faux").status_code == 403
        r = client.get("/webhooks/sms/inbound?numero=33633333333&message=STOP&token=jeton-secret")
        assert r.status_code == 200 and r.text == "OK" and _optouts(services) == ["+33633333333"]


def test_csv_import_rejects_oversized_file(logged_client, establishment_id, services):
    r = logged_client.post("/app/requests/import", data={"establishment_id": establishment_id, "channel": "sms"},
                           files={"file": ("gros.csv", b"0612345678;A\n" * 100_000, "text/csv")})
    assert r.status_code == 303 and "volumineux" in flash_of(r)
    with services.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM review_requests").fetchone()["n"] == 0


def test_global_optouts_are_enforced_but_not_listed_to_merchants(logged_client, establishment_id, services):
    with services.db.session() as conn:
        add_optout(conn, "+33644444444", None, source="cli")
    assert "+33644444444" not in logged_client.get("/app/requests").text
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "0644444444"})
    with services.db.session() as conn:
        assert conn.execute("SELECT status FROM review_requests").fetchone()["status"] == "blocked_optout"
    r = logged_client.post("/app/requests/optouts/remove", data={"phone": "0644444444"})
    assert "globale" in flash_of(r) and _optouts(services) == ["+33644444444"]


def test_inbox_sync_without_establishment_does_not_poll_other_accounts(logged_client, establishment_id,
                                                                        services, app):
    with TestClient(app, follow_redirects=False) as other:
        login(other, services, "sans-etablissement@exemple.fr")
        r = other.post("/app/inbox/sync")
        assert r.status_code == 303 and "Ajoutez d'abord" in flash_of(r)
    assert _reviews(services, establishment_id) == {}


def test_location_name_cannot_point_to_another_establishment(logged_client, establishment_id, services, app):
    with TestClient(app, follow_redirects=False) as other:
        login(other, services, "autre@exemple.fr")
        other_id = create_establishment(other, "Autre Commerce", "ChIJautre00000000001")
        form = {"name": "Autre Commerce", "google_place_id": "ChIJautre00000000001",
                "request_template": "Bonjour {prenom} : {lien}. STOP pour arrêter."}
        r = other.post(f"/app/establishments/{other_id}/settings",
                       data={**form, "google_location_name": "accounts/mock/locations/boulangerie-test"})
        assert "déjà reliée" in flash_of(r)
        r = other.post(f"/app/establishments/{other_id}/settings", data={**form, "google_location_name": "../x"})
        assert "format" in flash_of(r)
    with services.db.session() as conn:
        assert get_establishment(conn, other_id).google_location_name == "accounts/mock/locations/autre-commerce"


def test_live_mode_location_must_match_place_id(tmp_path):
    class FakeLive:
        name = "live"

        def list_locations(self):
            return [{"name": "accounts/1/locations/9", "title": "Chez Lou", "placeId": "ChIJlou0000000000001"}]

        def list_reviews(self, location_name):
            return []

        def reply(self, review_name, text):
            return {}

    settings = AppSettings(
        _env_file=None, llm_provider="mock", mail_provider="console", sms_provider="dry-run", gbp_mode="live",
        data_dir=tmp_path / "data", db_path=tmp_path / "live.db", session_secret="secret-de-test",
        app_base_url="http://testserver",
    )
    services = build_services(settings, mailer=ConsoleMailer(quiet=True), llm=MockLLM(responses=smart_llm),
                              gbp=FakeLive())
    with TestClient(create_app(services=services), follow_redirects=False) as client:
        login(client, services)
        est_id = create_establishment(client, "Chez Lou", "ChIJlou0000000000001")
        form = {"name": "Chez Lou", "google_place_id": "ChIJlou0000000000001",
                "request_template": "Bonjour {prenom} : {lien}. STOP pour arrêter."}
        r = client.post(f"/app/establishments/{est_id}/settings",
                        data={**form, "google_location_name": "accounts/1/locations/10"})
        assert "Place ID" in flash_of(r)
        r = client.post(f"/app/establishments/{est_id}/settings",
                        data={**form, "google_location_name": "accounts/1/locations/9"})
        assert "enregistrés" in flash_of(r)
    with services.db.session() as conn:
        assert get_establishment(conn, est_id).google_location_name == "accounts/1/locations/9"


def test_checkout_is_refused_for_active_subscriber(logged_client, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, plan="pro", subscription_status="active", stripe_customer_id="cus_1",
                       stripe_subscription_id="sub_1")
    r = logged_client.post("/billing/checkout", data={"plan": "reseau"})
    assert r.status_code == 303 and r.headers["location"] == "https://billing.stripe.test/portal"
    assert services.stripe.checkouts == []  # pas de second abonnement facturé
    assert "portail" in logged_client.get("/billing").text.lower()


def test_stripe_events_for_another_subscription_are_ignored(logged_client, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, plan="pro", subscription_status="active", stripe_customer_id="cus_1",
                       stripe_subscription_id="sub_new")
        deleted = {"id": "evt_old", "type": "customer.subscription.deleted", "data": {"object": {
            "object": "subscription", "id": "sub_old", "customer": "cus_1", "status": "canceled"}}}
        assert handle_stripe_event(conn, services.settings, deleted) == "ignored"
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        assert (acc.plan, acc.subscription_status, acc.stripe_subscription_id) == ("pro", "active", "sub_new")


def test_stripe_event_is_replayable_when_processing_fails(logged_client, services, monkeypatch):
    import avis_clients.billing as billing

    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        event = {"id": "evt_crash", "type": "checkout.session.completed", "data": {"object": {
            "object": "checkout.session", "client_reference_id": str(acc.id), "customer": "cus_9",
            "subscription": "sub_9", "mode": "subscription", "metadata": {"plan": "pro"}}}}
        original = billing.update_account

        def boom(*args, **kwargs):
            raise RuntimeError("base indisponible")

        monkeypatch.setattr(billing, "update_account", boom)
        with pytest.raises(RuntimeError):
            handle_stripe_event(conn, services.settings, event)
        monkeypatch.setattr(billing, "update_account", original)
        assert handle_stripe_event(conn, services.settings, event) == "applied"  # pas « duplicate »
        assert get_account_by_email(conn, "gerant@exemple.fr").plan == "pro"


def test_review_url_encodes_place_id():
    assert review_url_for_place("ChIJ test&x") == "https://search.google.com/local/writereview?placeid=ChIJ%20test%26x"


# ------------------------------------------------------------------------------------------
# Injection de prompt et contrôles de sortie LLM
# ------------------------------------------------------------------------------------------
def test_auto_publish_only_clean_llm_drafts(logged_client, establishment_id, services):
    with services.db.session() as conn:
        update_establishment(conn, establishment_id, auto_publish_positive=1)
    services.llm = MockLLM("{}")  # modèle indisponible : brouillons de repli
    with services.db.session() as conn:
        summary = poll_reviews(conn, services)
    assert summary.auto_published == 0 and summary.drafts == 4
    reviews = _reviews(services, establishment_id)
    assert reviews["r1"].reply_status == "draft" and reviews["r1"].reply_draft_source == "fallback"

    # réponse nettoyée mécaniquement (lien retiré) : brouillon à valider, jamais auto-publié
    services.llm = MockLLM('{"reply": "Merci Marie ! Détails sur http://exemple.fr/promo, à bientôt. L\'équipe"}')
    with services.db.session() as conn:
        est = get_establishment(conn, establishment_id)
        review = create_draft(conn, services, est, reviews["r1"])
    assert review.reply_draft_source == "llm-cleaned" and "http" not in review.reply_draft
    assert "à personnaliser" in logged_client.get("/app/inbox").text


def test_recommendations_are_sanitized_and_bounded():
    est = SimpleNamespace(name="Chez Lou")
    review = Review(id=1, establishment_id=1, platform="google", external_id="x", external_name=None, author="A",
                    rating=5, text="bien", created_at="2026-10-01T00:00:00Z", updated_at=None,
                    fetched_at="2026-10-01T00:00:00+00:00", reply_text=None, reply_status="none", reply_draft=None,
                    reply_published_at=None, alerted_at=None, reply_draft_source=None)
    stats = MonthlyStats(month="2026-10", count=1, reviews=[review])
    llm = MockLLM(json.dumps({"recommandations": ["Répondre vite.", "Cliquez sur http://evil.example maintenant.",
                                                  "Former l'équipe."]}))
    recos, source = generate_recommendations(llm, est, stats)
    assert source == "fallback"  # une recommandation contenait un lien : écartée, il en reste moins de 3
    llm = MockLLM(json.dumps({"recommandations": [" ".join(["mot"] * 80), "Deux.", "Trois."]}))
    recos, source = generate_recommendations(llm, est, stats)
    assert source == "llm" and len(recos[0].split()) <= 40


def test_commercial_promises_and_system_prompt_word_limit():
    assert "promesse_commerciale" in check_reply("Nous vous proposons un geste commercial.", 60)
    assert "promesse_commerciale" in check_reply("Nous vous offrons un café la prochaine fois.", 60)
    assert "promesse_commerciale" in check_reply("Nous vous dédommagerons.", 60)
    assert check_reply("Merci pour votre visite, à bientôt.", 60) == []
    llm = MockLLM('{"reply": "Merci, à bientôt."}')
    generate_reply_draft(llm, "X", {"style": "sobre", "signature": "S"}, {"rating": 5, "author": "A", "text": "ok"},
                         max_words=40)
    assert "40 mots maximum" in llm.calls[0]["system"]


# ------------------------------------------------------------------------------------------
# Correction fonctionnelle
# ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("whatsapp:+33612345678", "+33612345678"),
    ("tel:+33612345678", "+33612345678"),
    ("+33 (0)6 12 34 56 78", "+33612345678"),
    ("+330612345678", "+33612345678"),
    ("0033 (0)6 12 34 56 78", "+33612345678"),
    ("06 12 34 56 78", "+33612345678"),
])
def test_normalize_phone_prefixes_and_trunk_zero(raw, expected):
    assert normalize_phone(raw) == expected


def test_whatsapp_stop_is_honored(client, logged_client, establishment_id, services):
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "whatsapp",
                                                   "recipient": "0655555555"})
    r = client.post("/webhooks/sms/inbound", data={"From": "whatsapp:+33655555555", "Body": "Stop"})
    assert r.status_code == 200 and r.headers["x-optout"] == "1"
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "0655555555"})
    with services.db.session() as conn:
        last = conn.execute("SELECT status FROM review_requests ORDER BY id DESC").fetchone()
    assert last["status"] == "blocked_optout"


def test_render_message_tolerates_braces_and_blocks_attribute_access(logged_client, establishment_id, services):
    tpl = "Bonjour {prenom, avis ? {lien} STOP {lien.__class__} {inconnu}"
    assert render_message(tpl, prenom="Léa", etablissement="X", lien="L") == \
        "Bonjour {prenom, avis ? L STOP {lien.__class__} {inconnu}"
    assert validate_request_template("Bonjour {prenom}, un avis ? STOP") and \
        "{lien}" in validate_request_template("Bonjour {prenom}, un avis ? STOP")
    assert "STOP" in validate_request_template("Bonjour {prenom}, un avis ? {lien}")
    assert validate_request_template("Bonjour {prenom}, un avis ? {lien} STOP") is None
    with services.db.session() as conn:
        update_establishment(conn, establishment_id, request_template=tpl)
    assert logged_client.get("/app/requests").status_code == 200  # plus de 500 sur un modèle mal formé
    r = logged_client.post(f"/app/establishments/{establishment_id}/settings", data={
        "name": "Boulangerie Test", "google_place_id": "ChIJtestplaceid0001", "request_template": "Bonjour {lien}"})
    assert "STOP" in flash_of(r)


def test_monthly_boundaries_follow_paris_time(logged_client, establishment_id, services):
    assert month_bounds_utc("2026-10") == ("2026-09-30T22:00:00+00:00", "2026-10-31T23:00:00+00:00")
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        for created in ("2026-09-30T22:30:00+00:00",  # 1er octobre 00:30 à Paris → octobre
                        "2026-10-31T23:30:00+00:00",  # 1er novembre 00:30 à Paris → novembre
                        "2026-10-15T12:00:00+00:00"):
            conn.execute("INSERT INTO review_requests (establishment_id, channel, recipient, message, status,"
                         " created_at) VALUES (?, 'sms', '+33600000000', 'm', 'sent', ?)", (establishment_id, created))
        conn.commit()
        assert count_messages_in_month(conn, acc.id, "2026-10") == 2
        assert count_messages_in_month(conn, acc.id, "2026-11") == 1
        for ext, created in (("a", "2026-10-31T23:30:00Z"), ("b", "2026-09-30T22:30:00.000Z")):
            insert_review(conn, establishment_id=establishment_id, platform="google", external_id=ext,
                          external_name=None, author=None, rating=5, text=None, created_at=created, updated_at=None)
        assert [r.external_id for r in list_reviews_in_month(conn, establishment_id, "2026-10")] == ["b"]
        assert [r.external_id for r in list_reviews_in_month(conn, establishment_id, "2026-11")] == ["a"]


def test_report_month_parameter_is_validated(logged_client, establishment_id):
    assert is_valid_month("2026-10") and not is_valid_month("2026-13") and not is_valid_month("abcdefg")
    for month in ("abcdefg", "2026-13", "2026-1"):
        assert logged_client.get(f"/app/establishments/{establishment_id}/report?month={month}").status_code == 200


def test_report_preview_caches_llm_and_skips_it_in_readonly(logged_client, establishment_id, services):
    with services.db.session() as conn:
        poll_reviews(conn, services)

    def reco_calls():
        return len([c for c in services.llm.calls if '"recommandations"' in c["prompt"]])

    n = reco_calls()
    assert logged_client.get(f"/app/establishments/{establishment_id}/report?month=2026-10").status_code == 200
    assert reco_calls() == n + 1
    assert logged_client.get(f"/app/establishments/{establishment_id}/report?month=2026-10").status_code == 200
    assert reco_calls() == n + 1  # même mois, mêmes avis : pas de second appel
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, trial_ends_at="2020-01-01T00:00:00+00:00")
    services.report_cache.clear()
    r = logged_client.get(f"/app/establishments/{establishment_id}/report?month=2026-10")
    assert r.status_code == 200 and reco_calls() == n + 1  # lecture seule : aucun appel au modèle
    assert "Recommandations génériques" in r.text


def test_poll_updates_modified_reviews(logged_client, establishment_id, services):
    with services.db.session() as conn:
        poll_reviews(conn, services)
    mails = len(services.mailer.sent)
    r1 = next(r for r in services.gbp.data["reviews"] if r["reviewId"] == "r1")
    r1.update({"starRating": "TWO", "comment": "Finalement déçu, le pain était rassis.",
               "updateTime": "2026-10-20T10:00:00Z"})
    r3 = next(r for r in services.gbp.data["reviews"] if r["reviewId"] == "r3")
    r3.update({"comment": "Très bien, un peu d'attente (modifié).", "updateTime": "2026-10-21T10:00:00Z"})
    with services.db.session() as conn:
        summary = poll_reviews(conn, services)
    assert summary.new == 0 and summary.updated == 2 and summary.alerts == 1
    reviews = _reviews(services, establishment_id)
    assert reviews["r1"].rating == 2 and "rassis" in reviews["r1"].text and reviews["r1"].alerted_at
    assert reviews["r1"].reply_status == "draft" and "désolés" in reviews["r1"].reply_draft.lower()
    assert reviews["r3"].reply_status == "published" and "(modifié)" in reviews["r3"].text
    assert len(services.mailer.sent) == mails + 1
    with services.db.session() as conn:
        assert poll_reviews(conn, services).updated == 0  # stable au poll suivant


def test_poll_skips_readonly_accounts(logged_client, establishment_id, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, trial_ends_at="2020-01-01T00:00:00+00:00")
        summary = poll_reviews(conn, services)
    assert summary.skipped_readonly == 1 and summary.new == 0 and summary.drafts == 0
    assert _reviews(services, establishment_id) == {}


def test_insert_review_is_idempotent(logged_client, establishment_id, services):
    with services.db.session() as conn:
        kwargs = dict(establishment_id=establishment_id, platform="google", external_id="dup", external_name=None,
                      author="A", rating=4, text="x", created_at="2026-10-01T00:00:00Z", updated_at=None)
        first = insert_review(conn, **kwargs)
        second = insert_review(conn, **kwargs)
        assert first.id == second.id
        assert conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"] == 1


def test_trial_days_left_never_shows_zero_while_active(services):
    acc = Account(id=1, email="a@exemple.fr", created_at="2026-10-01T00:00:00+00:00", plan="none",
                  stripe_customer_id=None, stripe_subscription_id=None, subscription_status=None,
                  trial_ends_at="2026-11-10T12:00:00+00:00", last_login_at=None)
    from avis_clients.db import parse_iso

    assert account_access(acc, services.settings, now=parse_iso("2026-11-10T11:00:00+00:00")).days_left == 1
    assert account_access(acc, services.settings, now=parse_iso("2026-11-08T11:00:00+00:00")).days_left == 2
    assert account_access(acc, services.settings, now=parse_iso("2026-11-10T13:00:00+00:00")).state == "readonly"


def test_public_page_views_do_not_flood_activity_feed(client, logged_client, establishment_id):
    for _ in range(3):
        assert client.get("/r/boulangerie-test").status_code == 200
    dash = logged_client.get("/app").text
    assert "public_page_view" not in dash and "establishment_created" in dash


# ------------------------------------------------------------------------------------------
# Robustesse
# ------------------------------------------------------------------------------------------
def test_live_client_wraps_network_errors_and_sets_timeout(tmp_path):
    class FlakySession:
        def __init__(self):
            self.kwargs = []

        def get(self, url, params=None, **kwargs):
            self.kwargs.append(kwargs)
            raise ConnectionError("réseau coupé")

    session = FlakySession()
    client = LiveGBPClient(tmp_path / "token.json", session=session)
    with pytest.raises(GBPError):
        client.list_reviews("accounts/1/locations/9")
    assert session.kwargs[0].get("timeout")
