"""Dépendances FastAPI, rendu des gabarits, messages flash, redirections."""
from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import quote, unquote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .billing import Access
from .models import Account
from .services import Services
from .settings import PLAN_LABELS, PLAN_PRICES_EUR, PLAN_SMS_QUOTA
from .templating import get_env

FLASH_COOKIE = "avis_flash"

templates = Jinja2Templates(env=get_env())


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/app"):
        self.next_url = next_url


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_db(request: Request) -> sqlite3.Connection:
    return request.state.db


def current_account(request: Request) -> Account | None:
    return getattr(request.state, "account", None)


def current_access(request: Request) -> Access | None:
    return getattr(request.state, "access", None)


def require_account(request: Request) -> Account:
    account = current_account(request)
    if account is None:
        raise LoginRequired(request.url.path)
    return account


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def parse_flash(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        data = json.loads(unquote(raw))
        return {"message": str(data.get("message", "")), "category": str(data.get("category", "info"))}
    except (ValueError, AttributeError):
        return None


def render_template(request: Request, name: str, status_code: int = 200, **context: Any):
    services = get_services(request)
    flash = getattr(request.state, "flash", None)
    ctx = {
        "settings": services.settings,
        "app_name": services.settings.app_name,
        "account": current_account(request),
        "access": current_access(request),
        "flash": flash,
        "plan_labels": PLAN_LABELS,
        "plan_prices": PLAN_PRICES_EUR,
        "plan_sms_quota": PLAN_SMS_QUOTA,
        "gbp_mode": services.settings.gbp_mode,
        "sms_provider": services.sms.name,
        "mail_provider": services.mailer.name,
    }
    ctx.update(context)
    response = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    if flash:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def redirect(url: str, *, flash: str | None = None, category: str = "info", status_code: int = 303) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status_code)
    if flash:
        payload = quote(json.dumps({"message": flash, "category": category}, ensure_ascii=False))
        response.set_cookie(FLASH_COOKIE, payload, max_age=60, path="/", httponly=True, samesite="lax")
    return response


def not_found(detail: str = "Page introuvable") -> HTTPException:
    return HTTPException(status_code=404, detail=detail)
