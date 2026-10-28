"""Pages publiques : landing, pages légales, page d'avis `/r/{slug}`."""
from __future__ import annotations

from core.mail import Email
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from ..db import log_event
from ..deps import get_db, get_services, not_found, render_template
from ..repo import get_account, get_establishment_by_slug, insert_private_message, list_sources
from ..sources import secondary_review_links
from ..templating import render

router = APIRouter()

FAQ = [
    ("Est-ce que vous filtrez les avis négatifs ?",
     "Non. La page d'avis renvoie tous vos clients vers le formulaire Google, sans question préalable ni tri "
     "par note : c'est interdit par Google et par le code de la consommation, et nous ne le ferons jamais."),
    ("Dois-je donner accès à ma fiche Google ?",
     "Pour collecter des avis (QR code, SMS), non : le lien d'avis Google est public. Pour recevoir les avis "
     "et publier vos réponses depuis l'outil, vous nous ajoutez comme gestionnaire de votre fiche."),
    ("Les réponses sont-elles publiées automatiquement ?",
     "Par défaut, non : chaque brouillon attend votre validation en un clic. Vous pouvez activer "
     "l'auto-publication pour les avis à 4 et 5 étoiles uniquement."),
    ("Les SMS sont-ils conformes ?",
     "Le message ne contient aucune publicité, identifie votre établissement, et chaque destinataire peut "
     "répondre STOP. Vous restez responsable du consentement de vos clients à être contactés."),
    ("Puis-je arrêter quand je veux ?",
     "Oui, l'abonnement est mensuel et sans engagement ; la résiliation se fait depuis le portail client."),
]


@router.get("/")
def landing(request: Request):
    return render_template(request, "landing.html", faq=FAQ)


@router.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


@router.get("/legal/mentions")
def legal_mentions(request: Request):
    return render_template(request, "legal/mentions.html")


@router.get("/legal/cgv")
def legal_cgv(request: Request):
    return render_template(request, "legal/cgv.html")


@router.get("/legal/confidentialite")
def legal_privacy(request: Request):
    return render_template(request, "legal/confidentialite.html")


@router.get("/r/{slug}")
def public_review_page(request: Request, slug: str):
    conn = get_db(request)
    est = get_establishment_by_slug(conn, slug)
    if not est:
        raise not_found("Cette page d'avis n'existe pas.")
    log_event(conn, "public_page_view", account_id=est.account_id, establishment_id=est.id)
    # Google d'abord, toujours ; les autres plateformes reliées viennent ensuite, sans filtrage par note
    return render_template(request, "public/review_page.html", establishment=est,
                           secondary_links=secondary_review_links(list_sources(conn, est.id)))


@router.post("/r/{slug}/message")
def public_private_message(
    request: Request,
    slug: str,
    message: str = Form(""),
    name: str = Form(""),
    contact: str = Form(""),
    website: str = Form(""),  # pot de miel anti-robots : doit rester vide
):
    conn = get_db(request)
    services = get_services(request)
    est = get_establishment_by_slug(conn, slug)
    if not est:
        raise not_found("Cette page d'avis n'existe pas.")
    message = message.strip()[:2000]
    if website.strip() or not message:
        return render_template(request, "public/message_sent.html", establishment=est)
    insert_private_message(conn, est.id, name.strip()[:100] or None, contact.strip()[:200] or None, message)
    account = get_account(conn, est.account_id)
    to = est.notification_email or (account.email if account else None)
    if to:
        html = render("emails/private_message.html", establishment=est, name=name, contact=contact,
                      message=message, app_name=services.settings.app_name)
        services.mailer.send(
            Email(to=[to], subject=f"[{services.settings.app_name}] Message privé d'un client : {est.name}",
                  html=html, text=f"De : {name or 'anonyme'} ({contact or 'sans contact'})\n\n{message}"),
            sender=services.settings.mail_from,
        )
    log_event(conn, "private_message", account_id=est.account_id, establishment_id=est.id)
    return render_template(request, "public/message_sent.html", establishment=est)
