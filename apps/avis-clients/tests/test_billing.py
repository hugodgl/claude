import hashlib
import hmac
import json
import time

from avis_clients.billing import account_access, handle_stripe_event
from avis_clients.repo import get_account_by_email, update_account


def sign(payload: bytes, secret: str = "whsec_test", ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def event(etype: str, obj: dict, event_id: str = "evt_1") -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": etype, "data": {"object": obj}}).encode()


def test_checkout_redirects_to_stripe(logged_client, services):
    r = logged_client.post("/billing/checkout", data={"plan": "pro"})
    assert r.status_code == 303 and r.headers["location"] == "https://checkout.stripe.test/cs_pro"
    call = services.stripe.checkouts[-1]
    assert call["plan"] == "pro" and call["account"].email == "gerant@exemple.fr"
    assert call["success_url"].endswith("/billing?success=1")
    r = logged_client.post("/billing/checkout", data={"plan": "platine"})
    assert r.status_code == 303 and r.headers["location"] == "/billing"
    assert logged_client.get("/billing").status_code == 200


def test_webhook_rejects_bad_signature(client):
    payload = event("checkout.session.completed", {})
    bad = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": "t=1,v1=00"})
    assert bad.status_code == 400
    assert client.post("/webhooks/stripe", content=payload).status_code == 400
    old = sign(payload, ts=int(time.time()) - 3600)
    assert client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": old}).status_code == 400


def test_webhook_updates_account_and_is_idempotent(client, logged_client, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
    payload = event("checkout.session.completed", {
        "object": "checkout.session", "client_reference_id": str(acc.id), "customer": "cus_123",
        "subscription": "sub_123", "mode": "subscription", "metadata": {"account_id": str(acc.id), "plan": "pro"},
    })
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)})
    assert r.status_code == 200 and r.json()["result"] == "applied"
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
    assert (acc.plan, acc.subscription_status, acc.stripe_customer_id, acc.stripe_subscription_id) == (
        "pro", "active", "cus_123", "sub_123")

    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)})
    assert r.json()["result"] == "duplicate"

    # changement de formule via l'abonnement (prix Réseau), puis suppression
    upd = event("customer.subscription.updated", {
        "object": "subscription", "id": "sub_123", "customer": "cus_123", "status": "active",
        "items": {"data": [{"price": {"id": "price_reseau"}}]}, "metadata": {},
    }, event_id="evt_2")
    client.post("/webhooks/stripe", content=upd, headers={"Stripe-Signature": sign(upd)})
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        assert acc.plan == "reseau" and account_access(acc, services.settings).state == "active"
    deleted = event("customer.subscription.deleted", {"object": "subscription", "id": "sub_123",
                                                      "customer": "cus_123", "status": "canceled"}, event_id="evt_3")
    client.post("/webhooks/stripe", content=deleted, headers={"Stripe-Signature": sign(deleted)})
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
    assert acc.plan == "none" and acc.subscription_status == "canceled"


def test_unmatched_event_is_ignored(services, client):
    with services.db.session() as conn:
        services.db.migrate()
        result = handle_stripe_event(conn, services.settings, json.loads(event(
            "customer.subscription.updated", {"object": "subscription", "id": "sub_x", "customer": "cus_x"})))
    assert result == "unmatched"


def test_readonly_after_trial_without_subscription(logged_client, establishment_id, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, trial_ends_at="2020-01-01T00:00:00+00:00")
        assert account_access(get_account_by_email(conn, "gerant@exemple.fr"), services.settings).state == "readonly"
    # lecture possible
    assert logged_client.get("/app").status_code == 200
    assert logged_client.get("/app/inbox").status_code == 200
    # écriture bloquée : redirection vers la facturation, ou 402 en HTMX
    r = logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                       "recipient": "0612345678"})
    assert r.status_code == 303 and r.headers["location"] == "/billing"
    r = logged_client.post("/app/inbox/sync", headers={"HX-Request": "true"})
    assert r.status_code == 402
    # l'abonnement rouvre l'écriture
    with services.db.session() as conn:
        update_account(conn, acc.id, plan="solo", subscription_status="active")
    assert logged_client.post("/app/inbox/sync").status_code == 303
    assert logged_client.post("/app/inbox/sync").headers["location"] == "/app/inbox"


def test_portal_requires_customer(logged_client, services):
    r = logged_client.post("/billing/portal")
    assert r.status_code == 303 and r.headers["location"] == "/billing"
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, stripe_customer_id="cus_1")
    r = logged_client.post("/billing/portal")
    assert r.headers["location"] == "https://billing.stripe.test/portal"
