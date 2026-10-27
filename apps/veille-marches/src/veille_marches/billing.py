"""Stripe : Checkout (abonnement), portail client, webhooks signés et idempotents, synchronisation des statuts.

Deux passerelles : `StripeGateway` (SDK officiel, clés de test ou réelles) et `MockStripeGateway` (aucun appel réseau,
paiement simulé sur des pages locales) utilisée quand `STRIPE_SECRET_KEY` est vide et dans les tests.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from core.mail import Mailer

from . import db
from .accounts import send_welcome_email
from .dates import utcnow
from .models import Subscriber
from .settings import VMSettings

log = logging.getLogger(__name__)

# statut Stripe de l'abonnement → (status abonné, envois actifs ?)
SUBSCRIPTION_STATUS_MAP: dict[str, tuple[str, bool]] = {
    "active": ("active", True),
    "trialing": ("active", True),
    "past_due": ("past_due", True),          # impayé en cours de relance : accès maintenu le temps des réessais
    "unpaid": ("unpaid", False),             # relances épuisées : plus d'envoi
    "canceled": ("canceled", False),
    "incomplete": ("pending_payment", False),
    "incomplete_expired": ("canceled", False),
    "paused": ("paused", False),
}
HANDLED_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded",
                  "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted")


class BillingError(RuntimeError):
    pass


@dataclass
class CheckoutSession:
    id: str
    url: str


class StripeLike(Protocol):
    mode: str

    def create_checkout_session(self, sub: Subscriber, *, success_url: str, cancel_url: str) -> CheckoutSession: ...

    def create_portal_session(self, sub: Subscriber, *, return_url: str) -> str: ...

    def construct_event(self, payload: bytes, sig_header: str | None) -> dict[str, Any]: ...

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]: ...


def _plain(obj: Any) -> Any:
    """StripeObject → dict (les objets du SDK ne sont pas des mappings)."""
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return json.loads(json.dumps(to_dict(), default=str))
    return obj


class StripeGateway:
    """SDK Stripe : import paresseux, clé posée à chaque appel (le module est global)."""

    mode = "live"

    def __init__(self, settings: VMSettings):
        self.settings = settings
        if not settings.stripe_secret_key:
            raise BillingError("STRIPE_SECRET_KEY manquant")

    def _stripe(self):
        import stripe

        stripe.api_key = self.settings.stripe_secret_key
        stripe.max_network_retries = 2
        return stripe

    def create_checkout_session(self, sub: Subscriber, *, success_url: str, cancel_url: str) -> CheckoutSession:
        price = self.settings.stripe_price(sub.plan, sub.billing_period)
        if not price:
            raise BillingError(f"prix Stripe non configuré pour {sub.plan} / {sub.billing_period} "
                               f"(STRIPE_PRICE_{sub.plan.upper()}_{sub.billing_period.upper()})")
        meta = {"subscriber_id": str(sub.id), "plan": sub.plan, "billing_period": sub.billing_period}
        params: dict[str, Any] = dict(
            mode="subscription",
            line_items=[{"price": price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(sub.id),
            metadata=meta,
            subscription_data={"metadata": meta},
            locale="fr",
            allow_promotion_codes=True,
            billing_address_collection="required",
        )
        if sub.stripe_customer_id:
            params["customer"] = sub.stripe_customer_id
        else:
            params["customer_email"] = sub.email
        session = self._stripe().checkout.Session.create(**params)
        return CheckoutSession(id=str(session.id), url=str(session.url))

    def create_portal_session(self, sub: Subscriber, *, return_url: str) -> str:
        if not sub.stripe_customer_id:
            raise BillingError("abonné sans client Stripe")
        session = self._stripe().billing_portal.Session.create(customer=sub.stripe_customer_id, return_url=return_url)
        return str(session.url)

    def construct_event(self, payload: bytes, sig_header: str | None) -> dict[str, Any]:
        """Vérifie la signature (`t=…,v1=…`, tolérance 5 min) puis retourne l'événement en dict."""
        stripe = self._stripe()
        secret = self.settings.stripe_webhook_secret
        if not secret:
            raise BillingError("STRIPE_WEBHOOK_SECRET manquant")
        try:
            stripe.Webhook.construct_event(payload, sig_header or "", secret)
        except stripe.SignatureVerificationError as e:
            raise BillingError(f"signature Stripe invalide : {e}") from e
        except ValueError as e:
            raise BillingError(f"charge utile illisible : {e}") from e
        return json.loads(payload)

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        return _plain(self._stripe().Subscription.retrieve(subscription_id))


@dataclass
class MockStripeGateway:
    """Aucun appel réseau : la page `/demo/checkout/<id>` joue le rôle de Stripe Checkout."""

    settings: VMSettings
    mode: str = "mock"
    subscriptions: dict[str, dict[str, Any]] = field(default_factory=dict)
    portals: list[dict[str, Any]] = field(default_factory=list)

    def create_checkout_session(self, sub: Subscriber, *, success_url: str, cancel_url: str) -> CheckoutSession:
        return CheckoutSession(id=f"cs_demo_{sub.id}", url=f"/demo/checkout/{sub.id}")

    def create_portal_session(self, sub: Subscriber, *, return_url: str) -> str:
        self.portals.append({"subscriber_id": sub.id, "return_url": return_url})
        return f"/demo/portal/{sub.id}"

    def construct_event(self, payload: bytes, sig_header: str | None) -> dict[str, Any]:
        raise BillingError("webhook indisponible en mode mock (STRIPE_SECRET_KEY et STRIPE_WEBHOOK_SECRET absents)")

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self.subscriptions.get(subscription_id, {"id": subscription_id, "status": "active"})


def get_gateway(settings: VMSettings) -> StripeLike:
    return StripeGateway(settings) if settings.stripe_mode == "live" else MockStripeGateway(settings)


# --------------------------------------------------------------------------------------------
# Application des événements
# --------------------------------------------------------------------------------------------
def _get(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _id_of(value: Any) -> str | None:
    """Stripe renvoie tantôt un identifiant, tantôt l'objet développé."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return None


def resolve_subscriber(conn: sqlite3.Connection, obj: dict[str, Any]) -> Subscriber | None:
    for ref in (obj.get("client_reference_id"), _get(obj, "metadata", "subscriber_id")):
        if ref and str(ref).isdigit():
            sub = db.find_subscriber(conn, int(ref))
            if sub:
                return sub
    subscription_id = obj.get("id") if obj.get("object") == "subscription" else _id_of(obj.get("subscription"))
    sub = db.find_subscriber_by_stripe(conn, customer_id=_id_of(obj.get("customer")), subscription_id=subscription_id)
    if sub:
        return sub
    email = obj.get("customer_email") or _get(obj, "customer_details", "email")
    return db.get_subscriber_by_email(conn, email) if email else None


def activate_subscriber(conn: sqlite3.Connection, settings: VMSettings, sub: Subscriber, *,
                        customer_id: str | None, subscription_id: str | None, mailer: Mailer | None,
                        now: datetime | None = None) -> Subscriber:
    """Paiement confirmé : envois actifs, identifiants Stripe mémorisés, email de bienvenue (une seule fois)."""
    now = now or utcnow()
    was_active = sub.active and sub.status == "active"
    fields: dict[str, Any] = {"active": True, "status": "active"}
    if customer_id:
        fields["stripe_customer_id"] = customer_id
    if subscription_id:
        fields["stripe_subscription_id"] = subscription_id
    updated = db.update_subscriber(conn, sub.id, now=now, **fields)
    if mailer is not None and not was_active:
        try:
            send_welcome_email(settings, mailer, updated, now=now)
        except Exception:  # noqa: BLE001 - l'email ne doit pas faire échouer le webhook (Stripe réessaierait)
            log.exception("email de bienvenue non envoyé à %s", updated.email)
    return updated


def apply_subscription_status(conn: sqlite3.Connection, settings: VMSettings, sub: Subscriber,
                              subscription: dict[str, Any], *, now: datetime | None = None) -> Subscriber:
    """Reflète un objet `subscription` Stripe (statut, prix → formule et période, identifiants)."""
    status, active = SUBSCRIPTION_STATUS_MAP.get(str(subscription.get("status") or ""), ("active", True))
    fields: dict[str, Any] = {"status": status, "active": active}
    if subscription.get("id"):
        fields["stripe_subscription_id"] = subscription["id"]
    customer = _id_of(subscription.get("customer"))
    if customer:
        fields["stripe_customer_id"] = customer
    items = _get(subscription, "items", "data")
    price_id = _id_of(_get(items[0], "price")) if isinstance(items, list) and items else None
    resolved = settings.plan_for_price(price_id)
    if resolved:
        fields["plan"], fields["billing_period"] = resolved
    return db.update_subscriber(conn, sub.id, now=now, **fields)


def handle_stripe_event(conn: sqlite3.Connection, settings: VMSettings, event: dict[str, Any], *,
                        mailer: Mailer | None = None, now: datetime | None = None) -> str:
    """Applique un événement déjà vérifié. Retourne applied | duplicate | ignored | unmatched."""
    now = now or utcnow()
    etype = str(event.get("type") or "")
    event_id = str(event.get("id") or "")
    if etype not in HANDLED_EVENTS:
        return "ignored"
    if event_id and not db.record_stripe_event(conn, event_id, etype, now):
        return "duplicate"
    obj = _get(event, "data", "object") or {}
    sub = resolve_subscriber(conn, obj)
    result = "applied"
    if sub is None:
        log.warning("webhook Stripe %s %s : aucun abonné correspondant", etype, event_id)
        result = "unmatched"
    elif etype.startswith("checkout.session."):
        if obj.get("mode", "subscription") != "subscription":
            result = "ignored"
        elif etype == "checkout.session.completed" and obj.get("payment_status") == "unpaid":
            # paiement différé (prélèvement SEPA…) : on attend async_payment_succeeded
            db.update_subscriber(conn, sub.id, now=now, stripe_customer_id=_id_of(obj.get("customer")),
                                 stripe_subscription_id=_id_of(obj.get("subscription")))
            result = "pending"
        else:
            activate_subscriber(conn, settings, sub, customer_id=_id_of(obj.get("customer")),
                                subscription_id=_id_of(obj.get("subscription")), mailer=mailer, now=now)
    elif etype == "customer.subscription.deleted":
        db.update_subscriber(conn, sub.id, now=now, status="canceled", active=False)
    else:  # created / updated
        apply_subscription_status(conn, settings, sub, obj, now=now)
    if event_id:
        db.set_stripe_event_result(conn, event_id, result)
    return result


# --------------------------------------------------------------------------------------------
# Synchronisation (CLI `vm subscribers sync-stripe`)
# --------------------------------------------------------------------------------------------
@dataclass
class SyncResult:
    subscriber: Subscriber
    remote_status: str | None
    before: str
    after: str
    error: str | None = None

    @property
    def changed(self) -> bool:
        return self.before != self.after


def sync_subscriptions(conn: sqlite3.Connection, settings: VMSettings, gateway: StripeLike, *, dry_run: bool = False,
                       now: datetime | None = None) -> list[SyncResult]:
    """Relit chaque abonnement Stripe connu et aligne `status` / `active` (filet de sécurité si un webhook manque)."""
    now = now or utcnow()
    results: list[SyncResult] = []
    for sub in db.list_subscribers(conn, with_stripe_subscription=True):
        try:
            remote = gateway.retrieve_subscription(sub.stripe_subscription_id)
        except Exception as e:  # noqa: BLE001 - une erreur par abonné ne doit pas arrêter le passage
            results.append(SyncResult(sub, None, sub.status, sub.status, error=str(e)))
            continue
        remote_status = str(remote.get("status") or "")
        status, _ = SUBSCRIPTION_STATUS_MAP.get(remote_status, ("active", True))
        if dry_run:
            results.append(SyncResult(sub, remote_status, sub.status, status))
            continue
        updated = apply_subscription_status(conn, settings, sub, remote, now=now)
        results.append(SyncResult(sub, remote_status, sub.status, updated.status))
    return results
