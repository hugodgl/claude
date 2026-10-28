"""Site public et paiement : landing, inscription → Checkout, webhooks signés, espace abonné, mode simulé."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import timedelta

from core.llm import MockLLM
from fastapi.testclient import TestClient
from test_digest import SUMMARY_NO, SUMMARY_YES, seed_notices

from veille_marches import db
from veille_marches.accounts import make_account_token
from veille_marches.billing import handle_stripe_event
from veille_marches.digest import send_digests
from veille_marches.models import Subscriber
from veille_marches.scoring import score_pending

# fixtures partagées (live_settings, stripe_calls, mailer, client, mock_client) : voir conftest.py
SIGNUP = {"email": "Contact@Paysages69.fr", "company": "Paysages 69", "trade": "espaces_verts", "cpv_extra": "",
          "departments": ["69", "01"], "amount_min": "", "amount_max": "500k", "plan": "pro",
          "billing_period": "yearly", "accept_terms": "1"}


def sign(payload: bytes, secret: str = "whsec_test", ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def event(etype: str, obj: dict, event_id: str = "evt_1") -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": etype, "data": {"object": obj}}).encode()


def post_event(client: TestClient, etype: str, obj: dict, event_id: str = "evt_1") -> str:
    payload = event(etype, obj, event_id)
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def signup(client: TestClient, **overrides) -> Subscriber:
    data = {**SIGNUP, **overrides}
    r = client.post("/inscription", data=data)
    assert r.status_code == 303, r.text
    return r


# --------------------------------------------------------------------------------------------
def test_landing_offer_prices_example_and_legal_pages(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "Les marchés publics qui valent le coup, résumés chaque matin." in html
    assert "29 €" in html and "49 €" in html and "290 €" in html and "490 €" in html and "HT / mois" in html
    assert "10 mois payés" in html and 'href="/inscription?plan=pro&amp;period=yearly"' in html
    # exemple d'alerte construit depuis la fixture : carte complète en priorité, cartes compactes ensuite
    assert "Entretien des espaces verts des bâtiments communaux" in html and "Accord-cadre de 4 ans" in html
    assert "Six lots géographiques" not in html and 'href="/exemple"' in html
    for word in ("Quels marchés sont couverts", "résilier", "D'où viennent les données", "intelligence artificielle"):
        assert word in html
    assert "Mode démonstration" not in html
    for name in ("mentions", "cgv", "confidentialite"):
        page = client.get(f"/legal/{name}")
        assert page.status_code == 200 and "À COMPLÉTER" in page.text
    assert "29 €" in client.get("/legal/cgv").text
    assert client.get("/legal/autre").status_code == 404
    example = client.get("/exemple")
    assert example.status_code == 200 and "Voir l'avis original" in example.text
    assert "Résumé assisté par IA" in example.text
    assert client.get("/health").json()["stripe"] == "live"
    assert "Disallow: /compte" in client.get("/robots.txt").text


def test_signup_creates_inactive_subscriber_and_checkout_session(client, conn, stripe_calls, live_settings):
    r = signup(client)
    assert r.headers["location"] == "https://checkout.stripe.com/c/pay/cs_test_123"
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub is not None and sub.active is False and sub.status == "pending_payment"
    assert (sub.plan, sub.billing_period, sub.company) == ("pro", "yearly", "Paysages 69")
    assert sub.cpv_prefixes == ["773"] and sub.departments == ["69", "01"] and sub.amount_max == 500000.0
    assert sub.checkout_session_id == "cs_test_123" and sub.stripe_customer_id is None
    call = stripe_calls["checkout"][-1]
    assert call["mode"] == "subscription" and call["line_items"] == [{"price": "price_pro_y", "quantity": 1}]
    assert call["client_reference_id"] == str(sub.id) and call["customer_email"] == "contact@paysages69.fr"
    assert call["success_url"] == "http://testserver/merci?session_id={CHECKOUT_SESSION_ID}"
    assert call["cancel_url"] == "http://testserver/inscription" and call["locale"] == "fr"
    assert call["metadata"]["subscriber_id"] == str(sub.id) and call["subscription_data"]["metadata"]["plan"] == "pro"
    # formulaire pré-rempli par la page des formules
    form = client.get("/inscription?plan=pro&period=yearly").text
    assert 'value="pro" checked' in form and 'value="yearly" checked' in form
    # tant que le paiement n'est pas confirmé : page merci en attente, pas d'email
    r = client.get("/merci?session_id=cs_test_123")
    assert r.status_code == 200 and "en cours de confirmation" in r.text and 'http-equiv="refresh"' in r.text


def test_signup_validation_errors_and_honeypot(client, conn, stripe_calls):
    r = client.post("/inscription", data={**SIGNUP, "plan": "essentiel", "departments": ["69", "01", "38"]})
    assert r.status_code == 400 and "2 départements au maximum" in r.text and "passez en Pro" in r.text
    r = client.post("/inscription", data={**SIGNUP, "accept_terms": ""})
    assert r.status_code == 400 and "accepter les conditions" in r.text
    r = client.post("/inscription", data={**SIGNUP, "trade": "autre", "cpv_extra": ""})
    assert r.status_code == 400 and "au moins un préfixe CPV" in r.text
    r = client.post("/inscription", data={**SIGNUP, "cpv_extra": "77A"})
    assert r.status_code == 400 and "préfixe CPV invalide" in r.text
    r = client.post("/inscription", data={**SIGNUP, "email": "pas-un-email", "amount_min": "900000"})
    assert r.status_code == 400 and "adresse email valide" in r.text and "supérieur au minimal" in r.text
    assert 'value="Paysages 69"' in r.text    # valeurs conservées
    r = client.post("/inscription", data={**SIGNUP, "website": "http://spam.example"})
    assert r.status_code == 303 and r.headers["location"] == "/merci"
    assert db.list_subscribers(conn) == [] and stripe_calls["checkout"] == []


def test_signup_price_missing_shows_unavailable(client, conn, stripe_calls, live_settings):
    live_settings.stripe_price_pro_yearly = None
    r = client.post("/inscription", data=SIGNUP)
    assert r.status_code == 503 and "momentanément indisponible" in r.text
    assert db.get_subscriber_by_email(conn, "contact@paysages69.fr").status == "pending_payment"


def test_webhook_checkout_completed_activates_once_and_sends_welcome(client, conn, stripe_calls, mailer, now):
    signup(client)
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    obj = {"object": "checkout.session", "id": "cs_test_123", "mode": "subscription", "payment_status": "paid",
           "client_reference_id": str(sub.id), "customer": "cus_123", "subscription": "sub_123",
           "customer_details": {"email": "contact@paysages69.fr"}}
    assert post_event(client, "checkout.session.completed", obj) == "applied"
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub.active is True and sub.status == "active"
    assert (sub.stripe_customer_id, sub.stripe_subscription_id) == ("cus_123", "sub_123")
    assert len(mailer.sent) == 1
    mail = mailer.sent[0]
    assert mail.to == ["contact@paysages69.fr"] and "Bienvenue" in mail.subject and mail.reply_to == "hugo@example.com"
    assert "http://testserver/compte?token=" in mail.html and "http://testserver/compte?token=" in mail.text
    assert "69 – Rhône, 01 – Ain" in mail.text and "773" in mail.text and "jusqu'à 500 000 € HT" in mail.text
    assert "mercredi 28 octobre 2026 vers 7 h" in mail.text          # premier digest (inscription à 08:00 UTC)
    assert "dimanche 1 novembre 2026 vers 18 h" in mail.text          # premier brief (Pro)
    assert "490 € HT / an" in mail.text
    # rejoué par Stripe : idempotent, pas de second email
    assert post_event(client, "checkout.session.completed", obj) == "duplicate"
    assert len(mailer.sent) == 1
    assert conn.execute("SELECT result FROM stripe_events WHERE id = 'evt_1'").fetchone()[0] == "applied"
    # page merci : confirmation, prochaine étape, lien vers le compte
    r = client.get("/merci?session_id=cs_test_123")
    assert r.status_code == 200 and "Bienvenue, Paysages 69" in r.text and "Première alerte" in r.text
    token = re.search(r'href="http://testserver/compte\?token=([^"]+)"', r.text).group(1)
    assert client.get(f"/compte?token={token}").status_code == 200
    # types non gérés et événements sans abonné
    assert post_event(client, "invoice.paid", {"object": "invoice"}, "evt_2") == "ignored"
    assert post_event(client, "customer.subscription.updated", {"object": "subscription", "id": "sub_x",
                                                                 "customer": "cus_x", "status": "active"},
                      "evt_3") == "unmatched"


def test_webhook_rejects_bad_or_missing_signature(client, conn):
    payload = event("checkout.session.completed", {"object": "checkout.session"})
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": "t=1,v1=00"})
    assert r.status_code == 400 and "signature" in r.json()["error"]
    assert client.post("/webhooks/stripe", content=payload).status_code == 400
    wrong_secret = sign(payload, secret="whsec_autre")
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": wrong_secret})
    assert r.status_code == 400
    old = sign(payload, ts=int(time.time()) - 3600)
    assert client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": old}).status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0] == 0


def test_webhook_subscription_updates_and_deletion(client, conn, stripe_calls, mailer):
    signup(client)
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    post_event(client, "checkout.session.completed", {"object": "checkout.session", "mode": "subscription",
                                                      "client_reference_id": str(sub.id), "customer": "cus_123",
                                                      "subscription": "sub_123"})

    def subscription(status: str, price: str = "price_pro_y") -> dict:
        return {"object": "subscription", "id": "sub_123", "customer": "cus_123", "status": status,
                "items": {"data": [{"price": {"id": price}}]}, "metadata": {"subscriber_id": str(sub.id)}}

    assert post_event(client, "customer.subscription.updated", subscription("past_due"), "evt_pd") == "applied"
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub.status == "past_due" and sub.active is True        # relances en cours : accès maintenu
    post_event(client, "customer.subscription.updated", subscription("unpaid"), "evt_un")
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub.status == "unpaid" and sub.active is False
    # retour à la normale avec changement de formule via le prix (portail Stripe)
    post_event(client, "customer.subscription.updated", subscription("active", "price_ess_m"), "evt_ok")
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert (sub.status, sub.active, sub.plan, sub.billing_period) == ("active", True, "essentiel", "monthly")
    post_event(client, "customer.subscription.deleted", {"object": "subscription", "id": "sub_123",
                                                         "customer": "cus_123", "status": "canceled"}, "evt_del")
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub.status == "canceled" and sub.active is False
    assert len(mailer.sent) == 1                                    # un seul email de bienvenue
    # réinscription : la fiche (et le client Stripe) sont réutilisés, Checkout rattaché au client existant
    signup(client, plan="essentiel", departments=["69"])
    sub = db.get_subscriber_by_email(conn, "contact@paysages69.fr")
    assert sub.status == "pending_payment" and sub.active is False and sub.plan == "essentiel"
    last_call = stripe_calls["checkout"][-1]
    assert last_call["customer"] == "cus_123" and "customer_email" not in last_call
    assert len(db.list_subscribers(conn)) == 1


def test_account_page_valid_expired_and_tampered_links(client, conn, live_settings, now):
    sub = db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", company="Pro EV", cpv_prefixes=["773"],
                                             departments=["69", "01"], amount_max=800000, plan="pro",
                                             stripe_customer_id="cus_9", stripe_subscription_id="sub_9"))
    token = make_account_token(live_settings, sub.id, now=now)
    r = client.get(f"/compte?token={token}")
    assert r.status_code == 200 and "Mes critères" in r.text and "Pro EV" in r.text
    assert 'value="69" selected' in r.text and 'value="01" selected' in r.text and 'value="38" selected' not in r.text
    assert 'value="espaces_verts" selected' in r.text and 'value="800000"' in r.text
    # mise à jour des critères
    r = client.post("/compte", data={"token": token, "trade": "espaces_verts", "cpv_extra": "45112700",
                                      "departments": ["69", "38", "01"], "amount_min": "20000", "amount_max": ""})
    assert r.status_code == 303 and r.headers["location"] == f"/compte?token={token}&saved=1"
    assert "Réglages enregistrés" in client.get(r.headers["location"]).text
    sub = db.get_subscriber(conn, sub.id)
    assert sub.cpv_prefixes == ["773", "45112700"] and sub.departments == ["69", "38", "01"]
    assert sub.amount_min == 20000.0 and sub.amount_max is None
    # limite de la formule respectée
    r = client.post("/compte", data={"token": token, "trade": "espaces_verts", "departments": list("1234567")})
    assert r.status_code == 400 and "6 départements au maximum" in r.text
    # lien expiré (émis il y a 8 jours) → 403 et formulaire de nouveau lien ; lien falsifié → 403
    expired = make_account_token(live_settings, sub.id, now=now, days=-1)
    r = client.get(f"/compte?token={expired}")
    assert r.status_code == 403 and "expiré" in r.text and 'action="/compte/lien"' in r.text
    tampered = token[:-4] + "AAAA"
    assert client.get(f"/compte?token={tampered}").status_code == 403
    assert client.get(f"/compte?token={sub.id + 1}.9999999999.abc").status_code == 403
    assert client.get("/compte").status_code == 200       # sans lien : explication + formulaire


def test_account_portal_and_link_request(client, conn, live_settings, stripe_calls, mailer, now):
    sub = db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", cpv_prefixes=["773"], departments=["69"],
                                             stripe_customer_id="cus_9", stripe_subscription_id="sub_9"))
    token = make_account_token(live_settings, sub.id, now=now)
    r = client.post("/compte/portail", data={"token": token})
    assert r.status_code == 303 and r.headers["location"] == "https://billing.stripe.com/p/session/test"
    call = stripe_calls["portal"][-1]
    assert call["customer"] == "cus_9" and call["return_url"] == f"http://testserver/compte?token={token}"
    # abonné géré à la main (sans client Stripe) : message au lieu du portail
    manual = db.add_subscriber(conn, Subscriber(email="manuel@b.fr", cpv_prefixes=["773"]))
    r = client.post("/compte/portail", data={"token": make_account_token(live_settings, manual.id, now=now)})
    assert r.status_code == 200 and "géré manuellement" in r.text and len(stripe_calls["portal"]) == 1
    # demande d'un nouveau lien : même réponse connue / inconnue, email seulement si l'adresse existe
    r = client.post("/compte/lien", data={"email": "PRO@espaces-verts.fr"})
    assert r.status_code == 200 and "vient de partir" in r.text
    assert len(mailer.sent) == 1 and "/compte?token=" in mailer.sent[0].text
    link = re.search(r"(http://testserver/compte\?token=\S+)", mailer.sent[0].text).group(1)
    assert client.get(link.replace("http://testserver", "")).status_code == 200
    r = client.post("/compte/lien", data={"email": "inconnu@nulle-part.fr"})
    assert r.status_code == 200 and "vient de partir" in r.text and len(mailer.sent) == 1


def test_digest_goes_only_to_active_subscribers(conn, settings, now, live_settings, mailer):
    pending = db.add_subscriber(conn, Subscriber(email="attente@b.fr", cpv_prefixes=["773"], departments=["69"],
                                                 active=False, status="pending_payment"))
    db.add_subscriber(conn, Subscriber(email="paye@b.fr", cpv_prefixes=["773"], departments=["69"]))
    db.add_subscriber(conn, Subscriber(email="resilie@b.fr", cpv_prefixes=["773"], departments=["69"], active=False,
                                       status="canceled"))
    seed_notices(conn, now)
    score_pending(conn, settings, llm=MockLLM([SUMMARY_YES, SUMMARY_NO, SUMMARY_NO]), now=now)
    outcomes = send_digests(conn, settings, mailer, send=True, now=now)
    assert [o.digest.subscriber.email for o in outcomes] == ["paye@b.fr"]
    # paiement confirmé : l'abonné en attente reçoit le digest suivant
    handle_stripe_event(conn, live_settings, json.loads(event("checkout.session.completed", {
        "object": "checkout.session", "mode": "subscription", "client_reference_id": str(pending.id),
        "customer": "cus_p", "subscription": "sub_p"})), mailer=mailer, now=now)
    outcomes = send_digests(conn, settings, mailer, send=True, now=now)
    assert [o.digest.subscriber.email for o in outcomes] == ["attente@b.fr"]
    # digest, email de bienvenue, digest
    assert [e.to for e in mailer.sent] == [["paye@b.fr"], ["attente@b.fr"], ["attente@b.fr"]]
    # sans APP_SECRET_KEY le digest renvoie vers la réponse par email ; avec, il contient le lien signé
    assert "/compte?token=" not in mailer.sent[0].text and "répondez à cet email" in mailer.sent[0].text
    outcomes = send_digests(conn, live_settings, mailer, dry_run=True, now=now - timedelta(days=1))
    assert outcomes and all("http://testserver/compte?token=" in o.text and "votre espace" in o.html for o in outcomes)


def test_mock_mode_simulated_checkout_and_portal(mock_client, conn, mailer):
    assert "Mode démonstration" in mock_client.get("/").text
    r = mock_client.post("/inscription", data=SIGNUP)
    assert r.status_code == 303 and r.headers["location"].startswith("/demo/checkout/cs_demo_")
    checkout_url = r.headers["location"]
    session_id = checkout_url.rsplit("/", 1)[1]
    assert db.get_subscriber(conn, 1).active is False
    page = mock_client.get(checkout_url)
    assert page.status_code == 200 and "Simuler un paiement" in page.text and "490 € HT / an" in page.text
    r = mock_client.post(checkout_url)
    assert r.status_code == 303 and r.headers["location"] == f"/merci?session_id={session_id}"
    sub = db.get_subscriber(conn, 1)
    assert sub.active and sub.status == "active" and sub.stripe_subscription_id == "sub_demo_1"
    assert len(mailer.sent) == 1 and "Bienvenue" in mailer.sent[0].subject
    merci = mock_client.get(f"/merci?session_id={session_id}").text
    token = re.search(r"compte\?token=([^\"&]+)", merci).group(1)
    r = mock_client.post("/compte/portail", data={"token": token})
    assert r.status_code == 303 and r.headers["location"].startswith("/demo/portal/1?token=")
    assert mock_client.get(r.headers["location"]).status_code == 200
    r = mock_client.post("/demo/portal/1", data={"token": token, "action": "cancel"})
    assert r.status_code == 303
    sub = db.get_subscriber(conn, 1)
    assert sub.active is False and sub.status == "canceled"
    assert "résilié" in mock_client.get(f"/compte?token={token}").text
    # le webhook n'existe pas sans secret
    assert mock_client.post("/webhooks/stripe", content=b"{}").status_code == 400


def test_demo_pages_hidden_in_live_mode(client, conn):
    db.add_subscriber(conn, Subscriber(email="a@b.fr", cpv_prefixes=["773"]))
    assert client.get("/demo/checkout/1").status_code == 404
    assert client.post("/demo/checkout/1").status_code == 404
    assert client.get("/demo/portal/1").status_code == 404
