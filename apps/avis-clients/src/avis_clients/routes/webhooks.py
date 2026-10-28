"""Webhooks entrants : Stripe (signé) et SMS (STOP) de Twilio / smsmode.

Le webhook SMS modifie la liste d'opposition : il n'est accepté que s'il est authentifié, par la signature
`X-Twilio-Signature` (fournisseur Twilio) ou par le jeton partagé `SMS_WEBHOOK_TOKEN` (paramètre `token`,
indispensable avec smsmode qui ne signe pas ses callbacks). En `dry-run` sans jeton, il reste ouvert (démo).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from ..billing import BillingError, handle_stripe_event
from ..deps import get_db, get_services
from ..requests_service import handle_inbound_sms
from ..settings import AppSettings
from ..sms import verify_twilio_signature

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


@router.post("/stripe")
async def stripe_webhook(request: Request):
    services = get_services(request)
    payload = await request.body()
    try:
        event = services.stripe.construct_event(payload, request.headers.get("stripe-signature"))
    except BillingError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    result = handle_stripe_event(get_db(request), services.settings, event)
    return JSONResponse({"received": True, "result": result})


async def _inbound_params(request: Request) -> tuple[dict[str, str], dict[str, str]]:
    """(paramètres d'URL, paramètres POST) sous forme de chaînes."""
    query = {k: v for k, v in request.query_params.items()}
    form: dict[str, str] = {}
    if request.method == "POST":
        try:
            form = {k: str(v) for k, v in (await request.form()).items()}
        except Exception:  # noqa: BLE001 - corps non formulaire
            form = {}
    return query, form


def _public_url(settings: AppSettings, request: Request) -> str:
    """URL telle que le fournisseur l'a appelée : base publique configurée (pas l'URL vue derrière le proxy)."""
    url = f"{settings.app_base_url.rstrip('/')}{request.url.path}"
    return f"{url}?{request.url.query}" if request.url.query else url


def inbound_sms_authorized(settings: AppSettings, request: Request, query: dict[str, str],
                           form: dict[str, str]) -> bool:
    token = settings.sms_webhook_token
    if token:
        provided = form.get("token") or query.get("token") or ""
        if provided and hmac.compare_digest(provided, token):
            return True
    if settings.sms_provider == "twilio" and settings.twilio_auth_token:
        return verify_twilio_signature(settings.twilio_auth_token, _public_url(settings, request), form,
                                       request.headers.get("x-twilio-signature"))
    if settings.sms_provider == "dry-run" and not token:
        return True  # démo locale : aucun envoi réel, rien à protéger
    return False


@router.api_route("/sms/inbound", methods=["GET", "POST"])
async def sms_inbound(request: Request):
    services = get_services(request)
    query, form = await _inbound_params(request)
    if not inbound_sms_authorized(services.settings, request, query, form):
        log.warning("webhook SMS entrant refusé (signature ou jeton invalide), fournisseur %s",
                    services.settings.sms_provider)
        return PlainTextResponse("Webhook non authentifié", status_code=403)
    params = {**query, **form}
    sender = params.get("From") or params.get("from") or params.get("numero") or params.get("msisdn")
    body = params.get("Body") or params.get("body") or params.get("message") or params.get("text")
    handled = handle_inbound_sms(get_db(request), sender, body)
    if request.method == "POST":
        # Twilio attend du TwiML ; une réponse vide suffit (aucun SMS de confirmation envoyé)
        return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>",
                        media_type="application/xml", headers={"X-Optout": "1" if handled else "0"})
    return PlainTextResponse("OK" if handled else "IGNORED")
