"""Connexion par lien magique, session, déconnexion."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from ..auth import (
    SESSION_COOKIE,
    consume_magic_link,
    create_magic_link,
    create_session,
    delete_session,
    send_magic_link_email,
)
from ..db import log_event
from ..deps import get_db, get_services, redirect, render_template
from ..repo import get_or_create_account, is_valid_email

router = APIRouter()


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/app"


@router.get("/login")
def login_form(request: Request, next: str | None = None):
    if getattr(request.state, "account", None):
        return redirect(_safe_next(next))
    return render_template(request, "login.html", next=_safe_next(next))


@router.post("/login")
def login_submit(request: Request, email: str = Form(""), next: str = Form("/app")):
    services = get_services(request)
    conn = get_db(request)
    email = email.strip().lower()
    if not is_valid_email(email):
        return render_template(request, "login.html", status_code=400, next=_safe_next(next),
                               error="Adresse email invalide.", email=email)
    token = create_magic_link(conn, email, services.settings.magic_link_ttl_s)
    url = send_magic_link_email(services.mailer, services.settings, email, token)
    if services.mailer.name == "console":
        # en développement, le lien doit être lisible dans la sortie du serveur
        print(f"[avis] lien de connexion pour {email} : {url}", flush=True)
    log_event(conn, "magic_link_sent", email=email)
    return render_template(request, "login_sent.html", email=email)


@router.get("/auth/{token}")
def auth_token(request: Request, token: str, next: str | None = None):
    services = get_services(request)
    conn = get_db(request)
    email = consume_magic_link(conn, token)
    if not email:
        return render_template(request, "login.html", status_code=400, next="/app",
                               error="Ce lien de connexion est invalide ou a expiré. Demandez-en un nouveau.")
    account, created = get_or_create_account(conn, email, services.settings.trial_days)
    session_id = create_session(conn, account.id, services.settings.session_max_age_s,
                                request.headers.get("user-agent"))
    log_event(conn, "login", account_id=account.id, created=created)
    target = "/app/establishments/new" if created else _safe_next(next)
    response = redirect(target, flash="Bienvenue ! Commencez par ajouter votre établissement." if created else None)
    response.set_cookie(
        SESSION_COOKIE, services.signer.sign(session_id), max_age=services.settings.session_max_age_s,
        httponly=True, samesite="lax", secure=services.settings.cookie_secure, path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request):
    services = get_services(request)
    session_id = services.signer.unsign(request.cookies.get(SESSION_COOKIE))
    if session_id:
        delete_session(get_db(request), session_id)
    response = redirect("/", flash="Vous êtes déconnecté.")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
