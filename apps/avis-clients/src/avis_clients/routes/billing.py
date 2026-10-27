"""Abonnement : formules, Stripe Checkout, portail client."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from ..billing import VALID_PLANS, BillingError, account_access
from ..db import log_event
from ..deps import get_db, get_services, redirect, render_template, require_account
from ..settings import PLAN_MAX_ESTABLISHMENTS, PLAN_SMS_QUOTA

router = APIRouter(prefix="/billing")

PLANS = [
    {"code": "solo", "name": "Solo", "price": 19,
     "features": ["1 établissement", "QR code et page d'avis", "Brouillons de réponse dans votre ton",
                  "Alerte immédiate sur les avis à 1 ou 2 étoiles"]},
    {"code": "pro", "name": "Pro", "price": 29, "highlight": True,
     "features": ["Tout Solo", "100 demandes d'avis par SMS ou WhatsApp par mois", "Rapport mensuel",
                  "Auto-publication des réponses aux avis 4-5 étoiles (option)"]},
    {"code": "reseau", "name": "Réseau", "price": 59,
     "features": ["Tout Pro", "Jusqu'à 5 établissements", "300 demandes d'avis par mois",
                  "Rapport par établissement"]},
]


@router.get("")
def billing_page(request: Request, success: int = 0, canceled: int = 0):
    account = require_account(request)
    services = get_services(request)
    access = account_access(account, services.settings)
    return render_template(request, "billing.html", plans=PLANS, access=access, success=success,
                           canceled=canceled, stripe_enabled=services.stripe.enabled,
                           quotas=PLAN_SMS_QUOTA, max_est=PLAN_MAX_ESTABLISHMENTS)


@router.post("/checkout")
def billing_checkout(request: Request, plan: str = Form("")):
    account = require_account(request)
    services = get_services(request)
    base = services.settings.app_base_url.rstrip("/")
    if plan not in VALID_PLANS:
        return redirect("/billing", flash="Formule inconnue.", category="error")
    try:
        url = services.stripe.create_checkout_session(
            account=account, plan=plan, success_url=f"{base}/billing?success=1",
            cancel_url=f"{base}/billing?canceled=1",
        )
    except BillingError as e:
        return redirect("/billing", flash=str(e), category="error")
    except Exception as e:  # noqa: BLE001 - erreur Stripe : on l'affiche sans planter
        return redirect("/billing", flash=f"Stripe a renvoyé une erreur : {e}", category="error")
    log_event(get_db(request), "checkout_started", account_id=account.id, plan=plan)
    return redirect(url)


@router.post("/portal")
def billing_portal(request: Request):
    account = require_account(request)
    services = get_services(request)
    if not account.stripe_customer_id:
        return redirect("/billing", flash="Aucun abonnement Stripe associé à ce compte.", category="warn")
    try:
        url = services.stripe.create_portal_session(
            customer_id=account.stripe_customer_id,
            return_url=f"{services.settings.app_base_url.rstrip('/')}/billing",
        )
    except BillingError as e:
        return redirect("/billing", flash=str(e), category="error")
    except Exception as e:  # noqa: BLE001
        return redirect("/billing", flash=f"Stripe a renvoyé une erreur : {e}", category="error")
    return redirect(url)
