"""Demandes d'avis : envoi unitaire, import CSV, modèle de message, liste STOP."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from ..db import log_event
from ..deps import get_db, get_services, redirect, render_template, require_account
from ..repo import (
    add_optout,
    get_establishment,
    list_establishments,
    list_optouts,
    list_review_requests,
    remove_optout,
    update_establishment,
)
from ..requests_service import parse_contacts_csv, quota_status, send_review_request
from ..sms import DEFAULT_REQUEST_TEMPLATE, normalize_phone, render_message

router = APIRouter(prefix="/app/requests")


@router.get("")
def requests_page(request: Request, establishment: int | None = None):
    account = require_account(request)
    conn = get_db(request)
    services = get_services(request)
    establishments = list_establishments(conn, account.id)
    selected = next((e for e in establishments if e.id == establishment), establishments[0] if establishments else None)
    preview = None
    if selected:
        preview = render_message(selected.request_template, prenom="Camille", etablissement=selected.name,
                                 lien=f"{services.settings.app_base_url.rstrip('/')}/r/{selected.slug}")
    return render_template(
        request, "app/requests.html", establishments=establishments, selected=selected, preview=preview,
        quota=quota_status(conn, account, services.settings),
        history=list_review_requests(conn, [e.id for e in establishments], limit=50),
        optouts=list_optouts(conn, account.id), default_template=DEFAULT_REQUEST_TEMPLATE,
        whatsapp_available=services.sms.name in ("dry-run", "twilio"),
    )


def _owned(request: Request, establishment_id: int):
    account = require_account(request)
    est = get_establishment(get_db(request), establishment_id, account.id)
    return account, est


@router.post("/send")
def requests_send(
    request: Request,
    establishment_id: int = Form(...),
    channel: str = Form("sms"),
    recipient: str = Form(""),
    first_name: str = Form(""),
):
    account, est = _owned(request, establishment_id)
    if not est:
        return redirect("/app/requests", flash="Établissement introuvable.", category="error")
    outcome = send_review_request(get_db(request), get_services(request), account, est, channel=channel,
                                  recipient=recipient, first_name=first_name.strip()[:60] or None)
    category = "info" if outcome.ok else "error"
    label = {"sms": "SMS", "whatsapp": "message WhatsApp", "email": "email"}.get(channel, channel)
    return redirect(f"/app/requests?establishment={est.id}",
                    flash=f"Demande par {label} : {outcome.reason}.", category=category)


@router.post("/import")
async def requests_import(
    request: Request,
    establishment_id: int = Form(...),
    channel: str = Form("sms"),
    file: UploadFile = File(...),
):
    account, est = _owned(request, establishment_id)
    if not est:
        return redirect("/app/requests", flash="Établissement introuvable.", category="error")
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    contacts = parse_contacts_csv(content)
    if not contacts:
        return redirect(f"/app/requests?establishment={est.id}",
                        flash="Fichier vide ou illisible (colonnes attendues : téléphone, prénom).",
                        category="error")
    conn, services = get_db(request), get_services(request)
    sent = blocked = failed = 0
    for phone, first_name in contacts[:500]:
        outcome = send_review_request(conn, services, account, est, channel=channel, recipient=phone,
                                      first_name=first_name[:60] or None)
        if outcome.ok:
            sent += 1
        elif outcome.request and outcome.request.status.startswith("blocked"):
            blocked += 1
        else:
            failed += 1
    log_event(conn, "csv_import", account_id=account.id, establishment_id=est.id, sent=sent, blocked=blocked,
              failed=failed)
    return redirect(f"/app/requests?establishment={est.id}",
                    flash=f"Import terminé : {sent} envoyé(s), {blocked} bloqué(s) (STOP ou quota), "
                          f"{failed} invalide(s) ou en échec.", category="info" if sent else "warn")


@router.post("/template")
def requests_template(request: Request, establishment_id: int = Form(...), request_template: str = Form("")):
    account, est = _owned(request, establishment_id)
    if not est:
        return redirect("/app/requests", flash="Établissement introuvable.", category="error")
    tpl = request_template.strip()
    if "{lien}" not in tpl:
        return redirect(f"/app/requests?establishment={est.id}",
                        flash="Le modèle doit contenir {lien}.", category="error")
    if "stop" not in tpl.lower():
        return redirect(f"/app/requests?establishment={est.id}",
                        flash="Le modèle doit indiquer comment se désinscrire (mention STOP).", category="error")
    update_establishment(get_db(request), est.id, request_template=tpl[:320])
    return redirect(f"/app/requests?establishment={est.id}", flash="Modèle de message enregistré.")


@router.post("/optouts")
def optouts_add(request: Request, phone: str = Form("")):
    account = require_account(request)
    normalized = normalize_phone(phone)
    if not normalized:
        return redirect("/app/requests", flash="Numéro invalide.", category="error")
    add_optout(get_db(request), normalized, account.id, source="manual")
    log_event(get_db(request), "optout", account_id=account.id, phone=normalized, source="manual")
    return redirect("/app/requests", flash=f"{normalized} ajouté à la liste STOP.")


@router.post("/optouts/remove")
def optouts_remove(request: Request, phone: str = Form("")):
    account = require_account(request)
    normalized = normalize_phone(phone)
    if normalized:
        remove_optout(get_db(request), normalized, account.id)
    return redirect("/app/requests", flash="Numéro retiré de la liste STOP.")
