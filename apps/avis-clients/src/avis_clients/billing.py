"""Formules, essai, garde d'accès et Stripe (Checkout, portail client, webhooks signés)."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .db import log_event, now_iso, utcnow
from .models import Account
from .repo import find_account_by_stripe, get_account, get_account_by_email, update_account
from .settings import PLAN_MAX_ESTABLISHMENTS, PLAN_SMS_QUOTA, AppSettings

log = logging.getLogger(__name__)

ACTIVE_STATUSES = {"active", "trialing", "past_due"}
VALID_PLANS = ("solo", "pro", "reseau")


class BillingError(RuntimeError):
    pass


@dataclass
class Access:
    state: str  # "active" | "trial" | "readonly"
    plan: str  # formule effective pour les fonctionnalités
    days_left: int | None = None

    @property
    def can_write(self) -> bool:
        return self.state != "readonly"


def account_access(account: Account, settings: AppSettings, now: datetime | None = None) -> Access:
    """Abonnement actif → accès complet ; sinon essai de `trial_days` ; sinon lecture seule."""
    now = now or utcnow()
    if account.subscription_status in ACTIVE_STATUSES and account.plan in VALID_PLANS:
        return Access(state="active", plan=account.plan)
    trial_end = account.trial_end
    if trial_end and now < trial_end:
        # le dernier jour d'essai affiche « 1 jour restant », pas « 0 »
        days_left = max(1, (trial_end - now).days)
        return Access(state="trial", plan="pro", days_left=days_left)
    return Access(state="readonly", plan="none", days_left=0)


def sms_quota(access: Access, settings: AppSettings) -> int:
    if access.state == "trial":
        return settings.trial_sms_quota
    return PLAN_SMS_QUOTA.get(access.plan, 0)


def max_establishments(access: Access) -> int:
    if access.state == "trial":
        return 1
    return PLAN_MAX_ESTABLISHMENTS.get(access.plan, 0)


class StripeGateway:
    """Enveloppe fine autour du SDK Stripe, remplaçable dans les tests."""

    def __init__(self, settings: AppSettings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.stripe_secret_key)

    def _stripe(self):
        import stripe

        stripe.api_key = self.settings.stripe_secret_key
        return stripe

    def create_checkout_session(self, *, account: Account, plan: str, success_url: str, cancel_url: str) -> str:
        if plan not in VALID_PLANS:
            raise BillingError(f"formule inconnue : {plan}")
        price = self.settings.stripe_price_for(plan)
        if not self.enabled or not price:
            raise BillingError("Stripe n'est pas configuré (STRIPE_SECRET_KEY, STRIPE_PRICE_*)")
        params: dict[str, Any] = dict(
            mode="subscription",
            line_items=[{"price": price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(account.id),
            metadata={"account_id": str(account.id), "plan": plan},
            subscription_data={"metadata": {"account_id": str(account.id), "plan": plan}},
            allow_promotion_codes=True,
            locale="fr",
        )
        if account.stripe_customer_id:
            params["customer"] = account.stripe_customer_id
        else:
            params["customer_email"] = account.email
        session = self._stripe().checkout.Session.create(**params)
        return session.url

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        if not self.enabled:
            raise BillingError("Stripe n'est pas configuré")
        session = self._stripe().billing_portal.Session.create(customer=customer_id, return_url=return_url)
        return session.url

    def construct_event(self, payload: bytes, sig_header: str | None) -> dict[str, Any]:
        """Vérifie la signature du webhook et retourne l'événement sous forme de dict."""
        import stripe

        secret = self.settings.stripe_webhook_secret
        if not secret:
            raise BillingError("STRIPE_WEBHOOK_SECRET manquant")
        try:
            stripe.Webhook.construct_event(payload, sig_header or "", secret)
        except (stripe.error.SignatureVerificationError, ValueError) as e:
            raise BillingError(f"signature Stripe invalide : {e}") from e
        return json.loads(payload)


def _get(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _resolve_account(conn: sqlite3.Connection, obj: dict[str, Any]) -> Account | None:
    for ref in (obj.get("client_reference_id"), _get(obj, "metadata", "account_id")):
        if ref and str(ref).isdigit():
            acc = get_account(conn, int(ref))
            if acc:
                return acc
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else _get(obj, "customer", "id")
    subscription = obj.get("subscription") if isinstance(obj.get("subscription"), str) else None
    if obj.get("object") == "subscription":
        subscription = obj.get("id")
    acc = find_account_by_stripe(conn, customer_id=customer, subscription_id=subscription)
    if acc:
        return acc
    email = obj.get("customer_email") or _get(obj, "customer_details", "email")
    return get_account_by_email(conn, email) if email else None


def handle_stripe_event(conn: sqlite3.Connection, settings: AppSettings, event: dict[str, Any]) -> str:
    """Applique un événement Stripe (déjà vérifié) aux comptes. Idempotent sur l'identifiant d'événement."""
    event_id = event.get("id")
    if event_id:
        if conn.execute("SELECT 1 FROM stripe_events WHERE id = ?", (event_id,)).fetchone():
            return "duplicate"
        with conn:
            conn.execute("INSERT INTO stripe_events (id, type, received_at) VALUES (?, ?, ?)",
                         (event_id, event.get("type", "?"), now_iso()))
    etype = event.get("type", "")
    obj = _get(event, "data", "object") or {}
    account = _resolve_account(conn, obj)
    if account is None:
        log.warning("webhook Stripe %s : aucun compte correspondant", etype)
        log_event(conn, "stripe_unmatched", type=etype, event_id=event_id)
        return "unmatched"

    fields: dict[str, Any] = {}
    if etype == "checkout.session.completed":
        plan = _get(obj, "metadata", "plan")
        customer = obj.get("customer") if isinstance(obj.get("customer"), str) else _get(obj, "customer", "id")
        if customer:
            fields["stripe_customer_id"] = customer
        if isinstance(obj.get("subscription"), str):
            fields["stripe_subscription_id"] = obj["subscription"]
        if plan in VALID_PLANS:
            fields["plan"] = plan
        if obj.get("mode", "subscription") == "subscription":
            fields["subscription_status"] = "active"
    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        status = obj.get("status") or "active"
        price_id = _get(obj, "items", "data")
        price_id = _get(price_id[0], "price", "id") if isinstance(price_id, list) and price_id else None
        plan = settings.plan_for_price(price_id) or _get(obj, "metadata", "plan")
        fields["subscription_status"] = status
        fields["stripe_subscription_id"] = obj.get("id")
        customer = obj.get("customer") if isinstance(obj.get("customer"), str) else _get(obj, "customer", "id")
        if customer:
            fields["stripe_customer_id"] = customer
        if plan in VALID_PLANS:
            fields["plan"] = plan
        if status in ("canceled", "unpaid", "incomplete_expired"):
            fields["plan"] = "none"
    elif etype == "customer.subscription.deleted":
        fields["subscription_status"] = "canceled"
        fields["plan"] = "none"
    else:
        return "ignored"

    update_account(conn, account.id, **fields)
    log_event(conn, "stripe_event", account_id=account.id, type=etype, event_id=event_id, **fields)
    return "applied"
