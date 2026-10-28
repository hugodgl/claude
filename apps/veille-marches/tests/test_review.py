"""Revue croisée (QA-1) : chaque test met en évidence un défaut corrigé (voir REVIEW.md)."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from core.llm import MockLLM
from core.mail import ConsoleMailer
from fastapi.testclient import TestClient
from test_digest import SUMMARY_YES, seed_notices
from test_web import (  # noqa: F401 - fixtures réutilisées
    SIGNUP,
    client,
    event,
    live_settings,
    mailer,
    mock_client,
    post_event,
    stripe_calls,
)
from typer.testing import CliRunner

from veille_marches import billing, cli, db
from veille_marches.accounts import TokenError, make_account_token, read_account_token
from veille_marches.billing import handle_stripe_event, sync_subscriptions
from veille_marches.brief import send_briefs
from veille_marches.collectors.boamp import BoampCollector, map_boamp_record
from veille_marches.collectors.decp import DecpCollector
from veille_marches.collectors.ted import TedCollector
from veille_marches.dates import days_until, fr_date
from veille_marches.digest import send_digests
from veille_marches.filtering import match_notice
from veille_marches.forms import parse_account, parse_amount, parse_cpv_prefixes
from veille_marches.models import LLMSummary, Notice, Subscriber
from veille_marches.scoring import build_prompt, rules_score, summarize
from veille_marches.web import RedactTokensFilter, create_app

runner = CliRunner()


def checkout(sub_id: int, subscription: str = "sub_1", customer: str = "cus_1", **extra) -> dict:
    return {"object": "checkout.session", "id": "cs_test_123", "mode": "subscription", "payment_status": "paid",
            "client_reference_id": str(sub_id), "customer": customer, "subscription": subscription, **extra}


def subscription(sub_id: int, status: str, sid: str = "sub_1", customer: str = "cus_1") -> dict:
    return {"object": "subscription", "id": sid, "customer": customer, "status": status,
            "items": {"data": [{"price": {"id": "price_pro_y"}}]}, "metadata": {"subscriber_id": str(sub_id)}}


def pending_subscriber(conn, email: str = "attente@b.fr") -> Subscriber:
    return db.add_subscriber(conn, Subscriber(email=email, company="Attente SARL", cpv_prefixes=["773"],
                                              departments=["69"], plan="pro", active=False,
                                              status="pending_payment"))


# --------------------------------------------------------------------------------------------
# Webhook Stripe : événements hors ordre, idempotence, statuts inconnus
# --------------------------------------------------------------------------------------------
def test_stale_checkout_after_subscription_deleted_does_not_reactivate(conn, live_settings, mailer, now):
    sub = pending_subscriber(conn)
    deleted = json.loads(event("customer.subscription.deleted", subscription(sub.id, "canceled"), "evt_del"))
    assert handle_stripe_event(conn, live_settings, deleted, mailer=mailer, now=now) == "applied"
    sub = db.get_subscriber(conn, sub.id)
    assert sub.status == "canceled" and not sub.active and sub.stripe_subscription_id == "sub_1"
    # la livraison de checkout.session.completed avait échoué : Stripe la rejoue après la résiliation
    late = json.loads(event("checkout.session.completed", checkout(sub.id), "evt_checkout"))
    assert handle_stripe_event(conn, live_settings, late, mailer=mailer, now=now) == "stale"
    sub = db.get_subscriber(conn, sub.id)
    assert sub.status == "canceled" and not sub.active and mailer.sent == []


def test_events_of_an_old_subscription_do_not_touch_the_new_one(conn, live_settings, mailer, now):
    sub = db.add_subscriber(conn, Subscriber(email="pro@b.fr", cpv_prefixes=["773"], departments=["69"],
                                             stripe_customer_id="cus_1", stripe_subscription_id="sub_new"))
    old_deleted = json.loads(event("customer.subscription.deleted", subscription(sub.id, "canceled", sid="sub_old"),
                                   "evt_old_del"))
    assert handle_stripe_event(conn, live_settings, old_deleted, mailer=mailer, now=now) == "stale"
    old_unpaid = json.loads(event("customer.subscription.updated", subscription(sub.id, "unpaid", sid="sub_old"),
                                  "evt_old_up"))
    assert handle_stripe_event(conn, live_settings, old_unpaid, mailer=mailer, now=now) == "stale"
    sub = db.get_subscriber(conn, sub.id)
    assert sub.active and sub.status == "active" and sub.stripe_subscription_id == "sub_new"
    # l'abonnement suivi, lui, est bien résilié
    new_deleted = json.loads(event("customer.subscription.deleted", subscription(sub.id, "canceled", sid="sub_new"),
                                   "evt_new_del"))
    assert handle_stripe_event(conn, live_settings, new_deleted, mailer=mailer, now=now) == "applied"
    assert db.get_subscriber(conn, sub.id).status == "canceled"


def test_welcome_email_sent_once_whatever_the_event_order(conn, live_settings, mailer, now):
    # ordre habituel de Stripe : customer.subscription.created arrive avant checkout.session.completed
    first = pending_subscriber(conn, "un@b.fr")
    created = json.loads(event("customer.subscription.created", subscription(first.id, "active"), "evt_c1"))
    assert handle_stripe_event(conn, live_settings, created, mailer=mailer, now=now) == "applied"
    assert db.get_subscriber(conn, first.id).active and [e.to for e in mailer.sent] == [["un@b.fr"]]
    done = json.loads(event("checkout.session.completed", checkout(first.id), "evt_k1"))
    assert handle_stripe_event(conn, live_settings, done, mailer=mailer, now=now) == "applied"
    assert [e.to for e in mailer.sent] == [["un@b.fr"]]
    # ordre inverse : même résultat, un seul email
    second = pending_subscriber(conn, "deux@b.fr")
    done = json.loads(event("checkout.session.completed", checkout(second.id, "sub_2", "cus_2"), "evt_k2"))
    handle_stripe_event(conn, live_settings, done, mailer=mailer, now=now)
    created = json.loads(event("customer.subscription.created", subscription(second.id, "active", "sub_2", "cus_2"),
                               "evt_c2"))
    handle_stripe_event(conn, live_settings, created, mailer=mailer, now=now)
    assert [e.to for e in mailer.sent] == [["un@b.fr"], ["deux@b.fr"]]
    # paiement 3-D Secure en attente (incomplete) : pas d'email tant que l'abonnement n'est pas actif
    third = pending_subscriber(conn, "trois@b.fr")
    incomplete = json.loads(event("customer.subscription.created", subscription(third.id, "incomplete", "sub_3",
                                                                                "cus_3"), "evt_c3"))
    handle_stripe_event(conn, live_settings, incomplete, mailer=mailer, now=now)
    assert db.get_subscriber(conn, third.id).status == "pending_payment" and len(mailer.sent) == 2
    active = json.loads(event("customer.subscription.updated", subscription(third.id, "active", "sub_3", "cus_3"),
                              "evt_u3"))
    handle_stripe_event(conn, live_settings, active, mailer=mailer, now=now)
    assert db.get_subscriber(conn, third.id).active and [e.to for e in mailer.sent][-1] == ["trois@b.fr"]
    # impayé puis régularisation : pas de nouvel email de bienvenue
    for status in ("unpaid", "active"):
        handle_stripe_event(conn, live_settings, json.loads(event("customer.subscription.updated",
                                                                   subscription(third.id, status, "sub_3", "cus_3"),
                                                                   f"evt_{status}")), mailer=mailer, now=now)
    assert len(mailer.sent) == 3


def test_unknown_stripe_status_keeps_local_state(conn, live_settings, mailer, now, caplog):
    sub = db.add_subscriber(conn, Subscriber(email="pro@b.fr", cpv_prefixes=["773"], stripe_customer_id="cus_1",
                                             stripe_subscription_id="sub_1"))
    weird = json.loads(event("customer.subscription.updated", subscription(sub.id, "something_new"), "evt_w"))
    with caplog.at_level(logging.WARNING):
        assert handle_stripe_event(conn, live_settings, weird, mailer=mailer, now=now) == "applied"
    sub = db.get_subscriber(conn, sub.id)
    assert sub.active and sub.status == "active" and "something_new" in caplog.text
    # le prix, lui, est bien pris en compte
    assert (sub.plan, sub.billing_period) == ("pro", "yearly")


def test_failed_processing_is_not_recorded_as_already_seen(conn, live_settings, mailer, now, monkeypatch):
    sub = pending_subscriber(conn)
    done = json.loads(event("checkout.session.completed", checkout(sub.id), "evt_boom"))

    def explode(*args, **kwargs):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(billing, "activate_subscriber", explode)
    with pytest.raises(RuntimeError):
        handle_stripe_event(conn, live_settings, done, mailer=mailer, now=now)
    assert conn.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0] == 0
    monkeypatch.undo()
    # Stripe rejoue l'événement (même identifiant) : il est appliqué cette fois
    assert handle_stripe_event(conn, live_settings, done, mailer=mailer, now=now) == "applied"
    assert db.get_subscriber(conn, sub.id).active and len(mailer.sent) == 1


def test_sync_sends_welcome_when_webhook_was_missed(conn, live_settings, mailer, now):
    sub = pending_subscriber(conn)
    db.update_subscriber(conn, sub.id, stripe_subscription_id="sub_1", stripe_customer_id="cus_1")

    class Gateway:
        mode = "live"

        def retrieve_subscription(self, sid):
            return subscription(sub.id, "active")

    results = sync_subscriptions(conn, live_settings, Gateway(), mailer=mailer, now=now)
    assert results[0].changed and db.get_subscriber(conn, sub.id).active
    assert [e.to for e in mailer.sent] == ["attente@b.fr".split()]
    sync_subscriptions(conn, live_settings, Gateway(), mailer=mailer, now=now)
    assert len(mailer.sent) == 1


# --------------------------------------------------------------------------------------------
# Liens signés, clés obligatoires, en-têtes, journaux
# --------------------------------------------------------------------------------------------
def test_token_with_unicode_digits_is_rejected_cleanly(live_settings, client, now):
    for bad in ("1.²².abc", "١.1.abc", "1." + "9" * 40 + ".abc"):
        with pytest.raises(TokenError) as e:
            read_account_token(live_settings, bad, now=now)
        assert not e.value.expired
        assert client.get(f"/compte?token={bad}").status_code == 403


def test_web_refuses_to_start_with_stripe_key_but_without_secrets(settings, live_settings, mailer, now, monkeypatch):
    no_key = live_settings.model_copy(update={"app_secret_key": None})
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        with TestClient(create_app(no_key, mailer=mailer, now=lambda: now)):
            pass
    no_webhook = live_settings.model_copy(update={"stripe_webhook_secret": None})
    with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
        with TestClient(create_app(no_webhook, mailer=mailer, now=lambda: now)):
            pass
    assert no_key.web_startup_problems() and not live_settings.web_startup_problems()
    assert not settings.web_startup_problems()        # mode démonstration : clé temporaire tolérée


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("LLM_PROVIDER", "MAIL_PROVIDER", "DB_PATH", "OUT_DIR", "DATA_DIR", "STRIPE_SECRET_KEY",
                "STRIPE_WEBHOOK_SECRET", "APP_SECRET_KEY", "APP_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    return {"DB_PATH": str(tmp_path / "vm.db"), "OUT_DIR": str(tmp_path / "out"), "DATA_DIR": str(tmp_path),
            "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console"}


def test_cli_refuses_links_and_web_without_secret_key_and_invalid_criteria(cli_env, monkeypatch):
    def run(args, env, code=0):
        result = runner.invoke(cli.app, args, env=env)
        assert result.exit_code == code, result.output
        return result.output

    run(["subscribers", "add", "contact@paysages69.fr", "--cpv", "773", "--dept", "69"], cli_env)
    out = run(["subscribers", "link", "contact@paysages69.fr"], cli_env, code=2)
    assert "APP_SECRET_KEY" in out and "http" not in out
    with_key = {**cli_env, "APP_SECRET_KEY": "cle-de-test"}
    assert run(["subscribers", "link", "contact@paysages69.fr"], with_key).startswith("http://localhost:8000/compte")
    # critères invalides refusés au lieu d'être silencieusement ignorés (un préfixe perdu = aucun filtre CPV)
    assert "préfixe CPV invalide" in run(["subscribers", "add", "x@y.fr", "--cpv", "7"], cli_env, code=2)
    assert "département inconnu" in run(["subscribers", "add", "x@y.fr", "--dept", "999"], cli_env, code=2)
    assert "x@y.fr" not in run(["subscribers", "list"], cli_env)
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    out = run(["web"], {**cli_env, "STRIPE_SECRET_KEY": "sk_test_x"}, code=2)
    assert "APP_SECRET_KEY" in out and "STRIPE_WEBHOOK_SECRET" in out and calls == []
    run(["web"], {**with_key, "STRIPE_SECRET_KEY": "sk_test_x", "STRIPE_WEBHOOK_SECRET": "whsec_x"}, cli_env)
    assert len(calls) == 1


def test_security_headers_and_private_pages_not_cached(client, conn, live_settings, now):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and "script-src 'none'" in r.headers["content-security-policy"]
    assert "no-store" not in r.headers.get("cache-control", "")
    sub = db.add_subscriber(conn, Subscriber(email="pro@b.fr", cpv_prefixes=["773"], departments=["69"]))
    token = make_account_token(live_settings, sub.id, now=now)
    for path in (f"/compte?token={token}", "/merci?session_id=x", "/compte/lien"):
        assert client.get(path).headers["cache-control"] == "no-store", path


def test_webhook_errors_do_not_leak_configuration(client, mock_client):
    r = mock_client.post("/webhooks/stripe", content=b"{}")
    assert r.status_code == 400 and "STRIPE_WEBHOOK_SECRET" not in r.text and "mock" not in r.text
    payload = event("checkout.session.completed", {"object": "checkout.session"})
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": "t=1,v1=00"})
    assert r.status_code == 400 and r.json() == {"error": "signature invalide ou charge utile illisible"}


def test_access_log_filter_masks_account_tokens():
    f = RedactTokensFilter()
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:1", "GET", "/compte?token=1.1234.abcDEF&saved=1", "1.1", 200), None)
    assert f.filter(record) and record.getMessage() == '127.0.0.1:1 - "GET /compte?token=[masqué]&saved=1 HTTP/1.1" 200'
    plain = logging.LogRecord("x", logging.INFO, "", 0, "lien %s", ("http://h/compte?token=1.2.3",), None)
    f.filter(plain)
    assert plain.getMessage() == "lien http://h/compte?token=[masqué]"
    assert any(isinstance(x, RedactTokensFilter) for x in logging.getLogger("uvicorn.access").filters)


def test_public_example_pages_do_not_expose_a_signed_link(client):
    for path in ("/", "/exemple"):
        assert "compte?token=" not in client.get(path).text, path


# --------------------------------------------------------------------------------------------
# Mode démonstration : identifiants non devinables, portail protégé par le lien signé
# --------------------------------------------------------------------------------------------
def test_demo_pages_need_unguessable_session_and_valid_token(mock_client, conn, mailer, settings, now):
    r = mock_client.post("/inscription", data=SIGNUP)
    assert r.status_code == 303
    location = r.headers["location"]
    m = re.fullmatch(r"/demo/checkout/(cs_demo_[A-Za-z0-9_-]{16,})", location)
    assert m, location
    session_id = m.group(1)
    assert db.get_subscriber(conn, 1).checkout_session_id == session_id
    assert mock_client.get("/demo/checkout/1").status_code == 404
    assert mock_client.get("/demo/checkout/cs_demo_inconnu").status_code == 404
    assert mock_client.get(location).status_code == 200
    r = mock_client.post(location)
    assert r.status_code == 303 and r.headers["location"] == f"/merci?session_id={session_id}"
    assert db.get_subscriber(conn, 1).active and len(mailer.sent) == 1
    # un identifiant deviné ne donne ni récapitulatif ni lien d'accès
    guessed = mock_client.get("/merci?session_id=cs_demo_1").text
    assert "compte?token=" not in guessed and "Paysages 69" not in guessed
    assert "compte?token=" in mock_client.get(f"/merci?session_id={session_id}").text
    # le portail simulé exige le lien signé de l'abonné concerné
    other = db.add_subscriber(conn, Subscriber(email="autre@b.fr", cpv_prefixes=["773"]))
    demo_settings = settings.model_copy(update={"app_secret_key": "secret-de-test"})
    wrong = make_account_token(demo_settings, other.id, now=now)
    good = make_account_token(demo_settings, 1, now=now)
    assert mock_client.post("/demo/portal/1", data={"action": "cancel"}).status_code == 403
    assert mock_client.post("/demo/portal/1", data={"action": "cancel", "token": wrong}).status_code == 403
    assert mock_client.get("/demo/portal/1").status_code == 403
    assert db.get_subscriber(conn, 1).active
    assert mock_client.get(f"/demo/portal/1?token={good}").status_code == 200
    r = mock_client.post("/demo/portal/1", data={"action": "cancel", "token": good})
    assert r.status_code == 303 and not db.get_subscriber(conn, 1).active


# --------------------------------------------------------------------------------------------
# Inscription : réabonnement, validation stricte
# --------------------------------------------------------------------------------------------
def test_signup_refuses_unpaid_or_paused_subscriber(client, conn, stripe_calls):
    for status in ("unpaid", "paused"):
        db.add_subscriber(conn, Subscriber(email=f"{status}@b.fr", cpv_prefixes=["773"], departments=["69"],
                                           active=False, status=status, stripe_customer_id="cus_1",
                                           stripe_subscription_id="sub_1"))
        r = client.post("/inscription", data={**SIGNUP, "email": f"{status}@b.fr"})
        assert r.status_code == 400 and "lien d'accès" in r.text and "portail" in r.text
        assert db.get_subscriber_by_email(conn, f"{status}@b.fr").status == status
    assert stripe_calls["checkout"] == []


def test_form_amounts_and_cpv_prefixes_are_strict():
    for raw in ("inf", "nan", "1e308", "1_000", "0x10", "+5"):
        value, error = parse_amount(raw)
        assert value is None and error, raw
    assert "trop élevé" in parse_amount("999 999 999 999 999")[1]
    assert parse_amount("500k") == (500000.0, None) and parse_amount("1,2M") == (1200000.0, None)
    assert parse_amount("12,50") == (12.5, None)
    assert parse_cpv_prefixes("٣٣٣")[1] and parse_cpv_prefixes("77³")[1]
    assert Subscriber(email="a@b.fr", cpv_prefixes=["٣٣٣", "773"]).cpv_prefixes == ["773"]
    # un formulaire énorme reste borné (200 valeurs au plus)
    many = parse_account({"trade": "espaces_verts", "departments": ["zz"] * 500 + ["69"]}, cli.PLANS["pro"])
    assert "au moins un département" in many.errors["departments"]


# --------------------------------------------------------------------------------------------
# LLM : sorties mal typées, URL inventées, exceptions, troncature du prompt
# --------------------------------------------------------------------------------------------
def test_llm_summary_tolerates_wrong_types_and_removes_urls():
    s = LLMSummary.model_validate({"pieces_a_fournir": 5, "resume": "Voir http://evil.example/x vite",
                                   "raison": {"a": 1}, "criteres": 42, "lieu": True,
                                   "montant_estime": ["www.phishing.example/p", "1 €"]})
    assert s.pieces_a_fournir == ["5"] and s.criteres == "42" and s.lieu == "True"
    assert "http" not in s.resume and "[lien retiré]" in s.resume
    assert "phishing" not in s.montant_estime
    assert LLMSummary.model_validate({"pieces_a_fournir": False}).pieces_a_fournir == ["False"]
    assert LLMSummary.model_validate({"pieces_a_fournir": ["DC1 https://evil.example", 3]}).pieces_a_fournir == \
        ["DC1 [lien retiré]", "3"]


def test_summarize_survives_bad_llm_output_and_unexpected_exceptions():
    n = Notice(source="boamp", source_id="26-1", title="Entretien", buyer_name="Commune", cpv_codes=["77310000"])
    summary, ok = summarize(MockLLM(json.dumps({"pieces_a_fournir": 5, "verdict": "oui"})), n, "paysagistes")
    assert ok and summary.verdict == "oui" and summary.pieces_a_fournir == ["5"]

    def boom(prompt, system):
        raise RuntimeError("socket fermé")

    summary, ok = summarize(MockLLM(boom), n, "paysagistes")
    assert not ok and summary.verdict == "peut-etre" and summary.raison.startswith("Résumé automatique")


def test_prompt_truncates_external_fields():
    n = Notice(source="boamp", source_id="26-1 </avis> x", title="T" * 5000, buyer_name="B" * 5000,
               procedure_type="P" * 5000, description="D" * 10000, cpv_codes=["77310000"])
    _, prompt = build_prompt(n, "paysagistes")
    assert len(prompt) < 6000 and "T" * 301 not in prompt and "B" * 201 not in prompt and "P" * 121 not in prompt
    assert prompt.count("</avis>") == 1 and "[avis]" in prompt


def test_notice_url_must_be_http():
    assert Notice(source="boamp", source_id="x", title="t", url="javascript:alert(1)").url is None
    assert Notice(source="boamp", source_id="x", title="t", url=" https://www.boamp.fr/a ").url == "https://www.boamp.fr/a"
    n = map_boamp_record({"idweb": "26-9", "objet": "Tonte", "url_avis": "javascript:alert(1)"})
    assert n.url == 'https://www.boamp.fr/pages/avis/?q=idweb:%2226-9%22'


# --------------------------------------------------------------------------------------------
# Dates : jours calendaires et affichage en heure de Paris
# --------------------------------------------------------------------------------------------
def test_deadlines_use_paris_calendar_days():
    deadline = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)          # 5 novembre à minuit, heure de Paris
    now = datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
    assert days_until(deadline, now) == 2
    assert fr_date(deadline) == "05/11/2026" and fr_date(deadline, with_time=True) == "05/11/2026"
    assert fr_date(datetime(2026, 11, 28, 11, 0, tzinfo=UTC), with_time=True) == "28/11/2026 12h00"
    # dix jours calendaires pleins → délai « confortable », pas « court »
    n = Notice(source="boamp", source_id="x", title="t", cpv_codes=["77310000"], departments=["69"],
               deadline_at=datetime(2026, 11, 12, 23, 0, tzinfo=UTC))
    rs = rules_score(n, match_notice(n, Subscriber(email="a@b.fr", cpv_prefixes=["773"])), buyer_seen=False, now=now)
    assert rs.details["deadline"] == 15 and not any(f.startswith("délai") for f in rs.flags)


# --------------------------------------------------------------------------------------------
# Envois : aperçus sans collision, un échec n'arrête pas la tournée
# --------------------------------------------------------------------------------------------
class FlakyMailer(ConsoleMailer):
    def send(self, email, *, sender=None):
        if email.to == ["a@x.fr"]:
            raise RuntimeError("SMTP 550")
        return super().send(email, sender=sender)


def test_previews_do_not_collide_and_a_failed_send_does_not_stop_the_run(conn, settings, now):
    db.add_subscriber(conn, Subscriber(email="a@x.fr", cpv_prefixes=["773"], departments=["69"], plan="pro"))
    db.add_subscriber(conn, Subscriber(email="a@x.com", cpv_prefixes=["773"], departments=["69"], plan="pro"))
    seed_notices(conn, now)
    from veille_marches.scoring import score_pending
    score_pending(conn, settings, llm=MockLLM(SUMMARY_YES), now=now)
    outcomes = send_digests(conn, settings, None, now=now)
    files = {o.files[0] for o in outcomes}
    assert len(files) == 2 and all(f.name.endswith(".fr.html") or f.name.endswith(".com.html") for f in files)
    flaky = FlakyMailer(quiet=True)
    outcomes = send_digests(conn, settings, flaky, send=True, now=now)
    assert [(o.digest.subscriber.email, o.sent, bool(o.error)) for o in outcomes] == [("a@x.fr", False, True),
                                                                                        ("a@x.com", True, False)]
    assert [e.to for e in flaky.sent] == [["a@x.com"]]
    delivered = {r[0] for r in conn.execute("SELECT DISTINCT subscriber_id FROM deliveries")}
    assert delivered == {2}
    # le brief suit la même règle
    from test_brief import seed_awards
    seed_awards(conn, now)
    outcomes = send_briefs(conn, settings, flaky, send=True, now=now)
    assert [(o.brief.subscriber.email, o.sent) for o in outcomes] == [("a@x.fr", False), ("a@x.com", True)]
    assert outcomes[0].error and "550" in outcomes[0].error
    previews = send_briefs(conn, settings, None, now=now)
    assert len({o.files[0] for o in previews}) == 2


def test_cli_digest_reports_failed_sends(conn, settings, now, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in ("LLM_PROVIDER", "MAIL_PROVIDER", "DB_PATH", "OUT_DIR", "DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    env = {"DB_PATH": str(settings.db_path), "OUT_DIR": str(settings.out_dir), "DATA_DIR": str(tmp_path),
           "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console"}
    db.add_subscriber(conn, Subscriber(email="a@x.fr", cpv_prefixes=["773"], departments=["69"]))
    seed_notices(conn, now)
    from veille_marches.scoring import score_pending
    score_pending(conn, settings, llm=MockLLM(SUMMARY_YES), now=now)
    monkeypatch.setattr("veille_marches.cli.get_mailer", lambda s: FlakyMailer(quiet=True))
    result = runner.invoke(cli.app, ["digest", "--send"], env=env)
    assert result.exit_code == 1 and "ERREUR" in result.output and "SMTP 550" in result.output


# --------------------------------------------------------------------------------------------
# Collecte : enregistrements inattendus
# --------------------------------------------------------------------------------------------
def test_collectors_survive_malformed_records(settings, apis):
    weird = {"idweb": "26-weird", "objet": ["Tonte", "taille"], "nomacheteur": {"nom": "x"}, "donnees": 123,
             "code_departement": {"a": 1}, "datelimitereponse": {"x": 1}, "dateparution": 20261026,
             "url_avis": 123, "nature_categorise_libelle": None}
    apis.boamp["results"] = ["pas un dict", weird, None, *apis.boamp["results"]]
    result = BoampCollector(settings, client=apis.client()).fetch(datetime(2026, 10, 25, tzinfo=UTC).date(), ["773"],
                                                                 limit=50)
    assert result.error is None and result.fetched == 8 and result.kept == 4
    kept = {n.source_id: n for n in result.notices}["26-weird"]
    assert kept.title == "Tonte, taille" and kept.buyer_name is None and kept.departments == []
    assert kept.url == 'https://www.boamp.fr/pages/avis/?q=idweb:%2226-weird%22' and kept.deadline_at is None
    apis.ted["notices"] = ["x", {"publication-number": {"fra": ["1-2026"]}, "links": "nope", "notice-title": 7,
                                 "classification-cpv": {"a": "77310000"}, "estimated-value-proc": {"v": 1},
                                 "place-of-performance": "FRK26", "deadline-receipt-tender-date-lot": [None, 5]},
                           *apis.ted["notices"]]
    result = TedCollector(settings, client=apis.client()).fetch(datetime(2026, 10, 25, tzinfo=UTC).date(), ["773"],
                                                               limit=50)
    assert result.error is None and result.fetched == 6
    assert {n.source_id for n in result.notices} >= {"1-2026", "650123-2026"}
    apis.decp["results"] = [42, {"id": "d-1", "montant": "n/a", "titulaires": "[", "acheteur": 1, "dureemois": "x",
                                 "lieuexecution_code": ["69"], "codecpv": 77310000}, *apis.decp["results"]]
    result = DecpCollector(settings, client=apis.client()).fetch(datetime(2026, 10, 25, tzinfo=UTC).date(), ["773"],
                                                                limit=50)
    assert result.error is None and result.fetched == 8
    award = {a.source_id: a for a in result.awards}["d-1"]
    assert award.amount is None and award.duration_months is None and award.cpv_code == "77310000"


def test_http_client_timeout_from_settings(settings):
    from veille_marches.collectors.base import build_client
    client = build_client(settings.model_copy(update={"http_timeout_s": 7.5}),
                          transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    assert client.timeout.read == 7.5
