"""Liaison et retrait des sources d'avis Facebook et Tripadvisor depuis les réglages d'un établissement."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from ..deps import get_db, get_services, not_found, redirect, require_account
from ..platforms import platform_label
from ..repo import get_establishment
from ..sources import LINKABLE_PLATFORMS, SourceLinkError, link_source, unlink_source

router = APIRouter(prefix="/app")


def _owned(request: Request, establishment_id: int, platform: str):
    account = require_account(request)
    if platform not in LINKABLE_PLATFORMS:
        raise not_found("Plateforme inconnue.")
    est = get_establishment(get_db(request), establishment_id, account.id)
    if not est:
        raise not_found("Établissement introuvable.")
    return account, est


@router.post("/establishments/{establishment_id}/sources/{platform}")
def source_link(request: Request, establishment_id: int, platform: str, external_id: str = Form(""),
                credentials: str = Form("")):
    _, est = _owned(request, establishment_id, platform)
    back = f"/app/establishments/{est.id}"
    try:
        source = link_source(get_db(request), get_services(request), est, platform, external_id, credentials or None)
    except SourceLinkError as e:
        return redirect(back, flash=str(e), category="error")
    return redirect(back, flash=f"{platform_label(platform)} relié : {source.display_name or source.external_id}. "
                                "Les avis arriveront dans la boîte de réception à la prochaine synchronisation.")


@router.post("/establishments/{establishment_id}/sources/{platform}/unlink")
def source_unlink(request: Request, establishment_id: int, platform: str):
    _, est = _owned(request, establishment_id, platform)
    removed = unlink_source(get_db(request), est, platform)
    return redirect(f"/app/establishments/{est.id}",
                    flash=f"{platform_label(platform)} délié." if removed else "Aucune source à délier.",
                    category="info" if removed else "warn")
