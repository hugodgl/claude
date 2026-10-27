"""Webhooks entrants : Stripe (signé) et SMS (STOP) de Twilio / smsmode."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from ..billing import BillingError, handle_stripe_event
from ..deps import get_db, get_services
from ..requests_service import handle_inbound_sms

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


async def _inbound_params(request: Request) -> tuple[str | None, str | None]:
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update({k: str(v) for k, v in form.items()})
        except Exception:  # noqa: BLE001 - corps non formulaire
            pass
    sender = params.get("From") or params.get("from") or params.get("numero") or params.get("msisdn")
    body = params.get("Body") or params.get("body") or params.get("message") or params.get("text")
    return sender, body


@router.api_route("/sms/inbound", methods=["GET", "POST"])
async def sms_inbound(request: Request):
    sender, body = await _inbound_params(request)
    handled = handle_inbound_sms(get_db(request), sender, body)
    if request.method == "POST":
        # Twilio attend du TwiML ; une réponse vide suffit (aucun SMS de confirmation envoyé)
        return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>",
                        media_type="application/xml", headers={"X-Optout": "1" if handled else "0"})
    return PlainTextResponse("OK" if handled else "IGNORED")
