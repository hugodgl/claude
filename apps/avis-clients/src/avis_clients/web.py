"""Application FastAPI : `uvicorn avis_clients.web:app`."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import SESSION_COOKIE, get_session_account
from .billing import account_access
from .deps import FLASH_COOKIE, LoginRequired, is_htmx, parse_flash, redirect, render_template
from .routes import app as app_routes
from .routes import auth as auth_routes
from .routes import billing as billing_routes
from .routes import inbox as inbox_routes
from .routes import public as public_routes
from .routes import requests as requests_routes
from .routes import webhooks as webhooks_routes
from .services import Services, build_services
from .settings import AppSettings
from .templating import STATIC_DIR

log = logging.getLogger(__name__)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _same_origin(request: Request, base_url: str) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True
    host = urlparse(origin).netloc
    allowed = {request.headers.get("host", ""), urlparse(base_url).netloc}
    return host in allowed


def create_app(settings: AppSettings | None = None, services: Services | None = None) -> FastAPI:
    services = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        applied = services.db.migrate()
        if applied:
            log.info("migrations appliquées : %s", ", ".join(applied))
        yield

    app = FastAPI(title=services.settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.services = services
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        conn = services.db.connect()
        request.state.db = conn
        request.state.account = None
        request.state.access = None
        request.state.flash = parse_flash(request.cookies.get(FLASH_COOKIE))
        try:
            session_id = services.signer.unsign(request.cookies.get(SESSION_COOKIE))
            if session_id:
                account = get_session_account(conn, session_id)
                request.state.account = account
                if account:
                    request.state.access = account_access(account, services.settings)
            path = request.url.path
            if request.method in WRITE_METHODS and not path.startswith("/webhooks/"):
                if not _same_origin(request, services.settings.app_base_url):
                    return PlainTextResponse("Origine de la requête non autorisée", status_code=403)
            if path.startswith("/app"):
                if request.state.account is None:
                    if is_htmx(request):
                        return Response(status_code=401, headers={"HX-Redirect": "/login"})
                    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
                if request.method in WRITE_METHODS and not request.state.access.can_write:
                    message = ("Votre période d'essai est terminée : choisissez une formule pour continuer "
                               "à modifier vos données (la consultation reste possible).")
                    if is_htmx(request):
                        return HTMLResponse(f'<div class="flash warn">{message} '
                                            f'<a href="/billing">Voir les formules</a></div>', status_code=402)
                    return redirect("/billing", flash=message, category="warn")
            return await call_next(request)
        finally:
            conn.close()

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        wants_html = "text/html" in request.headers.get("accept", "") and not is_htmx(request)
        if wants_html and exc.status_code in (403, 404):
            return render_template(request, "error.html", status_code=exc.status_code,
                                   code=exc.status_code, detail=exc.detail)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    app.include_router(public_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(app_routes.router)
    app.include_router(requests_routes.router)
    app.include_router(inbox_routes.router)
    app.include_router(billing_routes.router)
    app.include_router(webhooks_routes.router)
    return app


app = create_app()
