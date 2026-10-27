"""Site public et espace abonné : `uvicorn veille_marches.web:app` (ou `vm web`).

Pages : `/` (offre), `/inscription` → Stripe Checkout, `/merci`, `/compte?token=…` (réglages, portail client),
`/legal/*`, `/webhooks/stripe`. Sans `STRIPE_SECRET_KEY`, le paiement est simulé sur `/demo/checkout/<id>`.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from core.db import connect
from core.mail import Mailer, get_mailer
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, db
from .accounts import (
    TokenError,
    account_url,
    make_account_token,
    read_account_token,
    recap_for,
    send_account_link_email,
)
from .billing import BillingError, StripeLike, activate_subscriber, get_gateway, handle_stripe_event
from .catalog import DEPARTMENTS, PERIODS, PLANS, TRADES, plan_or_default, trade_for_prefixes
from .dates import utcnow
from .forms import parse_account, parse_signup
from .models import Subscriber
from .rendering import render
from .sample import sample_digest, sample_email_html
from .settings import VMSettings, get_settings

log = logging.getLogger(__name__)
LEGAL_PAGES = {"mentions": "Mentions légales", "cgv": "Conditions générales de vente",
               "confidentialite": "Politique de confidentialité"}


def _db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(_db)]


def create_app(settings: VMSettings | None = None, *, gateway: StripeLike | None = None,
               mailer: Mailer | None = None, now: Callable[[], datetime] | None = None) -> FastAPI:
    settings = settings or get_settings()
    gateway = gateway or get_gateway(settings)
    clock = now or utcnow

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.open_db(settings.db_path).close()   # applique les migrations une fois
        if settings.stripe_mode == "mock":
            log.warning("Stripe non configuré : paiements simulés (mode démonstration)")
        yield

    app = FastAPI(title=settings.product_name, version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.settings = settings
    app.state.gateway = gateway
    app.state.mailer = mailer

    def get_mailer_instance() -> Mailer:
        return app.state.mailer or get_mailer(settings)

    def page(template: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        base = {"settings": settings, "stripe_mode": gateway.mode, "plans": PLANS, "periods": PERIODS,
                "trades": TRADES, "departments": DEPARTMENTS, "year": clock().year, "contact": settings.contact_email}
        base.update(ctx)
        return HTMLResponse(render(f"site/{template}", **base), status_code=status_code)

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def subscriber_from_token(conn: sqlite3.Connection, token: str | None) -> Subscriber:
        try:
            sid = read_account_token(settings, token, now=clock())
        except TokenError as e:
            raise HTTPException(status_code=403, detail="expired" if e.expired else "invalid") from e
        sub = db.find_subscriber(conn, sid)
        if sub is None:
            raise HTTPException(status_code=404, detail="Abonné introuvable")
        return sub

    def account_context(sub: Subscriber, token: str, form=None, **extra: Any) -> dict[str, Any]:
        trade = trade_for_prefixes(sub.cpv_prefixes)
        if form is None:
            extra_prefixes = [p for p in sub.cpv_prefixes if not trade or p not in trade.cpv_prefixes]
            values = {"trade": trade.code if trade else "autre", "cpv_extra": ", ".join(extra_prefixes),
                      "departments": sub.departments,
                      "amount_min": f"{sub.amount_min:.0f}" if sub.amount_min is not None else "",
                      "amount_max": f"{sub.amount_max:.0f}" if sub.amount_max is not None else ""}
            errors: dict[str, str] = {}
        else:
            values = {"trade": form.trade, "cpv_extra": form.cpv_extra, "departments": form.departments,
                      "amount_min": form.amount_min_raw, "amount_max": form.amount_max_raw}
            errors = form.errors
        return {"sub": sub, "token": token, "plan": plan_or_default(sub.plan), "values": values, "errors": errors,
                "recap": recap_for(sub, clock()), **extra}

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith(("/webhooks", "/health")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        if exc.status_code == 403 and exc.detail in ("expired", "invalid"):
            return page("account_link.html.j2", status_code=403, expired=exc.detail == "expired", sent=False)
        return page("error.html.j2", status_code=exc.status_code, code=exc.status_code, detail=exc.detail)

    # ---------------------------------------------------------------- pages publiques
    @app.get("/", response_class=HTMLResponse)
    def landing():
        return page("landing.html.j2", digest=sample_digest(settings, clock()))

    @app.get("/exemple", response_class=HTMLResponse)
    def example_email():
        return HTMLResponse(sample_email_html(settings, clock()))

    @app.get("/health")
    def health():
        return {"ok": True, "stripe": gateway.mode, "version": __version__}

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nDisallow: /compte\nDisallow: /merci\nDisallow: /demo/\n"

    @app.get("/legal/{name}", response_class=HTMLResponse)
    def legal(name: str):
        if name not in LEGAL_PAGES:
            raise HTTPException(status_code=404, detail="Page introuvable")
        return page(f"legal_{name}.html.j2", title=LEGAL_PAGES[name])

    # ---------------------------------------------------------------- inscription
    @app.get("/inscription", response_class=HTMLResponse)
    def signup_form(request: Request):
        plan = request.query_params.get("plan", "essentiel")
        period = request.query_params.get("period", "monthly")
        values = {"plan": plan if plan in PLANS else "essentiel", "billing_period": period if period in PERIODS
                  else "monthly", "trade": "espaces_verts", "departments": []}
        return page("signup.html.j2", values=values, errors={})

    @app.post("/inscription", response_class=HTMLResponse)
    async def signup_submit(request: Request, conn: Conn):
        form = parse_signup(await request.form())
        if form.is_bot:
            return redirect("/merci")
        values = {"email": form.email, "company": form.company, "trade": form.trade, "cpv_extra": form.cpv_extra,
                  "departments": form.departments, "amount_min": form.amount_min_raw,
                  "amount_max": form.amount_max_raw, "plan": form.plan, "billing_period": form.billing_period,
                  "accept_terms": form.accept_terms}
        if not form.valid:
            return page("signup.html.j2", status_code=400, values=values, errors=form.errors)
        existing = db.get_subscriber_by_email(conn, form.email)
        if existing and existing.active:
            errors = {"email": "cette adresse est déjà abonnée : demandez votre lien d'accès ci-dessous"}
            return page("signup.html.j2", status_code=400, values=values, errors=errors, already=True)
        fields = dict(company=form.company, cpv_prefixes=form.cpv_prefixes, departments=form.departments,
                      amount_min=form.amount_min, amount_max=form.amount_max, plan=form.plan,
                      billing_period=form.billing_period, active=False, status="pending_payment")
        now = clock()
        if existing:   # inscription abandonnée ou abonnement résilié : on réutilise la fiche (et le client Stripe)
            sub = db.update_subscriber(conn, existing.id, now=now, **fields)
        else:
            sub = db.add_subscriber(conn, Subscriber(email=form.email, **fields), now=now)
        try:
            session = gateway.create_checkout_session(
                sub, success_url=f"{settings.base_url}/merci?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.base_url}/inscription")
        except BillingError as e:
            log.error("création de session Checkout impossible pour %s : %s", sub.email, e)
            errors = {"form": "Le paiement est momentanément indisponible. Réessayez dans quelques minutes ou "
                              f"écrivez-nous : {settings.contact_email}"}
            return page("signup.html.j2", status_code=503, values=values, errors=errors)
        db.update_subscriber(conn, sub.id, now=now, checkout_session_id=session.id)
        return redirect(session.url)

    @app.get("/merci", response_class=HTMLResponse)
    def thanks(request: Request, conn: Conn):
        session_id = request.query_params.get("session_id", "")
        sub = db.get_subscriber_by_checkout_session(conn, session_id) if session_id else None
        state = "unknown" if sub is None else ("active" if sub.active else "pending")
        ctx: dict[str, Any] = {"state": state, "sub": sub}
        if sub is not None:
            ctx["recap"] = recap_for(sub, clock())
        if state == "active":
            ctx["account_url"] = account_url(settings, sub.id, now=clock())
        return page("thanks.html.j2", **ctx)

    # ---------------------------------------------------------------- espace abonné
    @app.get("/compte", response_class=HTMLResponse)
    def account(request: Request, conn: Conn):
        token = request.query_params.get("token")
        if not token:
            return page("account_link.html.j2", expired=False, sent=False, missing=True)
        sub = subscriber_from_token(conn, token)
        return page("account.html.j2", **account_context(sub, token, saved=request.query_params.get("saved") == "1"))

    @app.post("/compte", response_class=HTMLResponse)
    async def account_update(request: Request, conn: Conn):
        form_data = await request.form()
        token = str(form_data.get("token") or "")
        sub = subscriber_from_token(conn, token)
        form = parse_account(form_data, plan_or_default(sub.plan))
        if not form.valid:
            return page("account.html.j2", status_code=400, **account_context(sub, token, form=form))
        db.update_subscriber(conn, sub.id, now=clock(), cpv_prefixes=form.cpv_prefixes, departments=form.departments,
                             amount_min=form.amount_min, amount_max=form.amount_max)
        return redirect(f"/compte?token={token}&saved=1")

    @app.post("/compte/portail", response_class=HTMLResponse)
    async def account_portal(request: Request, conn: Conn):
        form_data = await request.form()
        token = str(form_data.get("token") or "")
        sub = subscriber_from_token(conn, token)
        if gateway.mode == "live" and not sub.stripe_customer_id:
            message = (f"Votre abonnement est géré manuellement : écrivez à {settings.contact_email} pour le "
                       "modifier ou le résilier.")
            return page("account.html.j2", **account_context(sub, token, portal_error=message))
        try:
            url = gateway.create_portal_session(sub, return_url=f"{settings.base_url}/compte?token={token}")
        except BillingError as e:
            log.error("portail client indisponible pour %s : %s", sub.email, e)
            message = ("Le portail de facturation est momentanément indisponible ; écrivez à "
                       f"{settings.contact_email}.")
            return page("account.html.j2", status_code=503, **account_context(sub, token, portal_error=message))
        if gateway.mode == "mock":
            url += f"?token={token}"
        return redirect(url)

    @app.get("/compte/lien", response_class=HTMLResponse)
    def account_link_form():
        return page("account_link.html.j2", expired=False, sent=False)

    @app.post("/compte/lien", response_class=HTMLResponse)
    async def account_link_send(request: Request, conn: Conn):
        form_data = await request.form()
        email = str(form_data.get("email") or "").strip().lower()
        sub = db.get_subscriber_by_email(conn, email) if email else None
        if sub is not None:
            try:
                send_account_link_email(settings, get_mailer_instance(), sub, now=clock())
            except Exception:  # noqa: BLE001 - même réponse quoi qu'il arrive (pas d'énumération d'adresses)
                log.exception("envoi du lien d'accès impossible à %s", email)
        return page("account_link.html.j2", expired=False, sent=True, email=email)

    # ---------------------------------------------------------------- Stripe
    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request, conn: Conn):
        payload = await request.body()
        try:
            event = gateway.construct_event(payload, request.headers.get("stripe-signature"))
        except BillingError as e:
            log.warning("webhook Stripe refusé : %s", e)
            return JSONResponse({"error": str(e)}, status_code=400)
        result = handle_stripe_event(conn, settings, event, mailer=get_mailer_instance(), now=clock())
        return JSONResponse({"received": True, "result": result})

    # ---------------------------------------------------------------- mode démonstration (sans Stripe)
    def demo_only(conn: sqlite3.Connection, subscriber_id: int) -> Subscriber:
        if gateway.mode != "mock":
            raise HTTPException(status_code=404, detail="Page introuvable")
        sub = db.find_subscriber(conn, subscriber_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="Abonné introuvable")
        return sub

    @app.get("/demo/checkout/{subscriber_id}", response_class=HTMLResponse)
    def demo_checkout(subscriber_id: int, conn: Conn):
        sub = demo_only(conn, subscriber_id)
        return page("demo_checkout.html.j2", sub=sub, recap=recap_for(sub, clock()), plan=plan_or_default(sub.plan))

    @app.post("/demo/checkout/{subscriber_id}")
    def demo_checkout_pay(subscriber_id: int, conn: Conn):
        sub = demo_only(conn, subscriber_id)
        activate_subscriber(conn, settings, sub, customer_id=f"cus_demo_{sub.id}", subscription_id=f"sub_demo_{sub.id}",
                            mailer=get_mailer_instance(), now=clock())
        return redirect(f"/merci?session_id=cs_demo_{sub.id}")

    @app.get("/demo/portal/{subscriber_id}", response_class=HTMLResponse)
    def demo_portal(subscriber_id: int, request: Request, conn: Conn):
        sub = demo_only(conn, subscriber_id)
        return page("demo_portal.html.j2", sub=sub, token=request.query_params.get("token", ""),
                    recap=recap_for(sub, clock()))

    @app.post("/demo/portal/{subscriber_id}")
    async def demo_portal_action(subscriber_id: int, request: Request, conn: Conn):
        sub = demo_only(conn, subscriber_id)
        form_data = await request.form()
        token = str(form_data.get("token") or make_account_token(settings, sub.id, now=clock()))
        if form_data.get("action") == "cancel":
            db.update_subscriber(conn, sub.id, now=clock(), status="canceled", active=False)
        return redirect(f"/compte?token={token}")

    return app


app = create_app()
