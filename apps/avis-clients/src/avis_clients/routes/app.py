"""Espace connecté : tableau de bord, établissements (onboarding, ton, QR, impression, réglages)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ..billing import account_access, max_establishments
from ..db import log_event
from ..deps import get_db, get_services, not_found, redirect, render_template, require_account
from ..qr import qr_png, qr_svg
from ..repo import (
    count_reviews_by_status,
    create_establishment,
    delete_establishment,
    get_establishment,
    is_valid_email,
    list_establishments,
    list_events,
    list_private_messages,
    list_review_requests,
    list_reviews,
    review_url_for_place,
    update_establishment,
)
from ..reports import build_monthly_report, default_report_month, month_label
from ..requests_service import public_link, quota_status
from ..sms import DEFAULT_REQUEST_TEMPLATE
from ..tone import PRESETS, default_profile, generate_examples

router = APIRouter(prefix="/app")

PLACE_ID_HELP = (
    "Ouvrez https://developers.google.com/maps/documentation/places/web-service/place-id, "
    "tapez le nom de votre commerce dans l'outil « Place ID Finder » et copiez l'identifiant (il commence "
    "souvent par « ChIJ »)."
)


def _owned_establishment(request: Request, establishment_id: int):
    account = require_account(request)
    est = get_establishment(get_db(request), establishment_id, account.id)
    if not est:
        raise not_found("Établissement introuvable.")
    return account, est


@router.get("")
def dashboard(request: Request):
    account = require_account(request)
    conn = get_db(request)
    services = get_services(request)
    establishments = list_establishments(conn, account.id)
    ids = [e.id for e in establishments]
    counts = count_reviews_by_status(conn, ids)
    return render_template(
        request, "app/dashboard.html", establishments=establishments, counts=counts,
        pending=counts.get("draft", 0), events=list_events(conn, account.id, limit=10),
        quota=quota_status(conn, account, services.settings),
        max_establishments=max_establishments(account_access(account, services.settings)),
        public_links={e.id: public_link(services.settings, e) for e in establishments},
    )


@router.get("/establishments/new")
def establishment_new(request: Request):
    account = require_account(request)
    conn = get_db(request)
    services = get_services(request)
    access = account_access(account, services.settings)
    existing = list_establishments(conn, account.id)
    limit_reached = len(existing) >= max_establishments(access)
    return render_template(request, "app/establishment_new.html", presets=PRESETS, place_id_help=PLACE_ID_HELP,
                           limit_reached=limit_reached, max_establishments=max_establishments(access))


@router.post("/establishments")
def establishment_create(
    request: Request,
    name: str = Form(""),
    google_place_id: str = Form(""),
    style: str = Form("chaleureux"),
    signature: str = Form(""),
    notification_email: str = Form(""),
):
    account = require_account(request)
    conn = get_db(request)
    services = get_services(request)
    settings = services.settings
    name, place_id = name.strip(), google_place_id.strip()
    errors = []
    if len(name) < 2:
        errors.append("Le nom de l'établissement est requis.")
    if len(place_id) < 10 or any(c.isspace() for c in place_id):
        errors.append("Le Place ID Google semble invalide (identifiant sans espace, ex. ChIJ…).")
    if notification_email.strip() and not is_valid_email(notification_email.strip()):
        errors.append("L'email de notification est invalide.")
    access = account_access(account, settings)
    if len(list_establishments(conn, account.id)) >= max_establishments(access):
        errors.append("Votre formule ne permet pas d'ajouter un établissement supplémentaire.")
    if errors:
        return render_template(request, "app/establishment_new.html", status_code=400, presets=PRESETS,
                               place_id_help=PLACE_ID_HELP, errors=errors, form=dict(
                                   name=name, google_place_id=place_id, style=style, signature=signature,
                                   notification_email=notification_email),
                               limit_reached=False, max_establishments=max_establishments(access))
    profile = default_profile(style, name, signature)
    examples, from_llm = generate_examples(services.llm, name, profile)
    profile["exemples"] = examples
    location_name = None
    est = create_establishment(
        conn, account_id=account.id, name=name, google_place_id=place_id,
        review_url=review_url_for_place(place_id), tone_profile=profile,
        request_template=DEFAULT_REQUEST_TEMPLATE, notification_email=notification_email.strip() or None,
    )
    if settings.gbp_mode == "mock":
        # en mode démo, chaque établissement est relié à une fiche fictive servie par les fixtures
        location_name = f"accounts/mock/locations/{est.slug}"
        update_establishment(conn, est.id, google_location_name=location_name)
    log_event(conn, "establishment_created", account_id=account.id, establishment_id=est.id,
              examples_from_llm=from_llm)
    flash = ("Établissement créé. Relisez et ajustez les trois exemples de réponses : ils guideront chaque brouillon."
             if from_llm else
             "Établissement créé. Le modèle de langage n'a pas répondu : des exemples par défaut ont été "
             "proposés, adaptez-les à votre ton.")
    return redirect(f"/app/establishments/{est.id}/tone", flash=flash, category="info" if from_llm else "warn")


@router.get("/establishments/{establishment_id}/tone")
def establishment_tone(request: Request, establishment_id: int):
    _, est = _owned_establishment(request, establishment_id)
    return render_template(request, "app/establishment_tone.html", establishment=est, tone=est.tone,
                           presets=PRESETS)


@router.post("/establishments/{establishment_id}/tone")
def establishment_tone_save(
    request: Request,
    establishment_id: int,
    style: str = Form("chaleureux"),
    signature: str = Form(""),
    do: str = Form(""),
    dont: str = Form(""),
    exemple_1: str = Form(""),
    exemple_2: str = Form(""),
    exemple_3: str = Form(""),
    action: str = Form("save"),
):
    account, est = _owned_establishment(request, establishment_id)
    conn = get_db(request)
    services = get_services(request)
    profile = default_profile(style, est.name, signature)
    profile["do"] = [line.strip() for line in do.splitlines() if line.strip()] or profile["do"]
    profile["dont"] = [line.strip() for line in dont.splitlines() if line.strip()] or profile["dont"]
    if action == "regenerate":
        examples, from_llm = generate_examples(services.llm, est.name, profile)
        profile["exemples"] = examples
        update_establishment(conn, est.id, tone_profile=profile)
        return redirect(f"/app/establishments/{est.id}/tone",
                        flash="Nouveaux exemples générés." if from_llm else
                        "Modèle indisponible : exemples par défaut proposés.",
                        category="info" if from_llm else "warn")
    profile["exemples"] = [e.strip() for e in (exemple_1, exemple_2, exemple_3) if e.strip()]
    update_establishment(conn, est.id, tone_profile=profile)
    log_event(conn, "tone_updated", account_id=account.id, establishment_id=est.id, style=profile["style"])
    return redirect(f"/app/establishments/{est.id}", flash="Ton enregistré. Voici votre QR code.")


@router.get("/establishments/{establishment_id}")
def establishment_detail(request: Request, establishment_id: int):
    account, est = _owned_establishment(request, establishment_id)
    conn = get_db(request)
    services = get_services(request)
    return render_template(
        request, "app/establishment_detail.html", establishment=est, tone=est.tone,
        public_url=public_link(services.settings, est),
        reviews=list_reviews(conn, [est.id], limit=5),
        requests=list_review_requests(conn, [est.id], limit=5),
        messages=list_private_messages(conn, est.id),
        report_month=default_report_month(),
    )


@router.post("/establishments/{establishment_id}/settings")
def establishment_settings(
    request: Request,
    establishment_id: int,
    name: str = Form(""),
    google_place_id: str = Form(""),
    google_location_name: str = Form(""),
    notification_email: str = Form(""),
    request_template: str = Form(""),
    auto_publish_positive: str = Form(""),
):
    account, est = _owned_establishment(request, establishment_id)
    conn = get_db(request)
    fields: dict = {}
    if name.strip() and len(name.strip()) >= 2:
        fields["name"] = name.strip()
    if google_place_id.strip() and google_place_id.strip() != est.google_place_id:
        fields["google_place_id"] = google_place_id.strip()
        fields["review_url"] = review_url_for_place(google_place_id.strip())
    fields["google_location_name"] = google_location_name.strip() or est.google_location_name
    if notification_email.strip() and not is_valid_email(notification_email.strip()):
        return redirect(f"/app/establishments/{est.id}", flash="Email de notification invalide.", category="error")
    fields["notification_email"] = notification_email.strip() or None
    if "{lien}" not in request_template:
        return redirect(f"/app/establishments/{est.id}",
                        flash="Le modèle de message doit contenir {lien}.", category="error")
    fields["request_template"] = request_template.strip()[:320]
    fields["auto_publish_positive"] = 1 if auto_publish_positive in ("1", "on", "true") else 0
    update_establishment(conn, est.id, **fields)
    log_event(conn, "establishment_updated", account_id=account.id, establishment_id=est.id,
              auto_publish=fields["auto_publish_positive"])
    return redirect(f"/app/establishments/{est.id}", flash="Réglages enregistrés.")


@router.post("/establishments/{establishment_id}/delete")
def establishment_delete(request: Request, establishment_id: int):
    account, est = _owned_establishment(request, establishment_id)
    delete_establishment(get_db(request), est.id)
    log_event(get_db(request), "establishment_deleted", account_id=account.id, name=est.name)
    return redirect("/app", flash=f"Établissement « {est.name} » supprimé.")


@router.get("/establishments/{establishment_id}/qr.png")
def establishment_qr_png(request: Request, establishment_id: int, download: int = 0):
    _, est = _owned_establishment(request, establishment_id)
    data = qr_png(public_link(get_services(request).settings, est))
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="qr-{est.slug}.png"'}
    return Response(content=data, media_type="image/png", headers=headers)


@router.get("/establishments/{establishment_id}/qr.svg")
def establishment_qr_svg(request: Request, establishment_id: int, download: int = 0):
    _, est = _owned_establishment(request, establishment_id)
    data = qr_svg(public_link(get_services(request).settings, est))
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="qr-{est.slug}.svg"'}
    return Response(content=data, media_type="image/svg+xml", headers=headers)


@router.get("/establishments/{establishment_id}/print")
def establishment_print(request: Request, establishment_id: int):
    _, est = _owned_establishment(request, establishment_id)
    return render_template(request, "app/establishment_print.html", establishment=est,
                           public_url=public_link(get_services(request).settings, est))


@router.get("/establishments/{establishment_id}/report")
def establishment_report(request: Request, establishment_id: int, month: str | None = None):
    _, est = _owned_establishment(request, establishment_id)
    services = get_services(request)
    month = month if month and len(month) == 7 else default_report_month()
    stats = build_monthly_report(get_db(request), services, est, month)
    return render_template(request, "app/report.html", establishment=est, stats=stats, month=month,
                           month_label=month_label(month))
