"""Boîte de réception des avis : brouillons, publication, régénération, ignorer (HTMX), toutes plateformes."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from ..deps import get_db, get_services, is_htmx, not_found, redirect, render_template, require_account
from ..platforms import PLATFORM_LABELS, PLATFORMS, PlatformError
from ..repo import get_establishment, get_review, list_establishments, list_reviews, list_sources_for_establishments
from ..reviews import (
    ReplyNotSupported,
    create_draft,
    mark_published_manually,
    poll_reviews,
    publish_reply,
    reopen_review,
    save_draft,
    skip_review,
)

router = APIRouter(prefix="/app")

STATUS_FILTERS = {
    "draft": "À valider",
    "published": "Publiées",
    "skipped": "Ignorées",
    "all": "Tous les avis",
}
PLATFORM_FILTERS = {"all": "Toutes les plateformes", **PLATFORM_LABELS}


@router.get("/inbox")
def inbox(request: Request, status: str = "draft", establishment: int | None = None, platform: str = "all"):
    account = require_account(request)
    conn = get_db(request)
    establishments = list_establishments(conn, account.id)
    ids = [e.id for e in establishments if establishment is None or e.id == establishment]
    platform = platform if platform in PLATFORM_LABELS else "all"
    platform_filter = None if platform == "all" else platform
    status_filter = None if status == "all" else status
    if status == "draft":
        reviews = (list_reviews(conn, ids, status="draft", platform=platform_filter)
                   + list_reviews(conn, ids, status="approved", platform=platform_filter))
        reviews.sort(key=lambda r: r.created_at, reverse=True)
    elif status == "published":
        reviews = (list_reviews(conn, ids, status="published", platform=platform_filter)
                   + list_reviews(conn, ids, status="published_manually", platform=platform_filter))
        reviews.sort(key=lambda r: r.created_at, reverse=True)
    else:
        reviews = list_reviews(conn, ids, status=status_filter, platform=platform_filter)
    linked = {s.platform for s in list_sources_for_establishments(conn, [e.id for e in establishments])}
    return render_template(
        request, "app/inbox.html", reviews=reviews, establishments=establishments,
        establishments_by_id={e.id: e for e in establishments}, status=status, filters=STATUS_FILTERS,
        selected_establishment=establishment, platform=platform, platform_filters=PLATFORM_FILTERS,
        linked_platforms=[p for p in PLATFORMS if p in linked],
    )


@router.post("/inbox/sync")
def inbox_sync(request: Request):
    account = require_account(request)
    conn = get_db(request)
    ids = [e.id for e in list_establishments(conn, account.id)]
    if not ids:
        # sans établissement, ne jamais retomber sur « tous les établissements » (ceux des autres comptes)
        return redirect("/app/inbox", flash="Ajoutez d'abord un établissement.", category="warn")
    summary = poll_reviews(conn, get_services(request), establishment_ids=ids)
    msg = f"Synchronisation : {summary.fetched} avis lus"
    if len(summary.by_platform) > 1:
        msg += f" ({summary.platform_line()})"
    msg += (f", {summary.new} nouveau(x), {summary.drafts} brouillon(s), {summary.alerts} alerte(s), "
            f"{summary.auto_published} auto-publié(s).")
    if summary.skipped_recent:
        msg += f" {summary.skipped_recent} source(s) Tripadvisor relue(s) plus tard (quota de l'API)."
    if summary.errors:
        msg += " Erreurs : " + " ; ".join(summary.errors[:3])
    return redirect("/app/inbox", flash=msg, category="warn" if summary.errors else "info")


def _owned_review(request: Request, review_id: int):
    account = require_account(request)
    conn = get_db(request)
    review = get_review(conn, review_id)
    if not review:
        raise not_found("Avis introuvable.")
    est = get_establishment(conn, review.establishment_id, account.id)
    if not est:
        raise not_found("Avis introuvable.")
    return account, review, est


def _respond(request: Request, review, est, flash: str | None = None, category: str = "info"):
    if is_htmx(request):
        return render_template(request, "partials/review_card.html", review=review, establishment=est,
                               notice=flash, notice_category=category)
    return redirect("/app/inbox", flash=flash, category=category)


@router.post("/reviews/{review_id}/publish")
def review_publish(request: Request, review_id: int, text: str = Form("")):
    _, review, est = _owned_review(request, review_id)
    conn = get_db(request)
    body = text.strip() or (review.reply_draft or "")
    try:
        review = publish_reply(conn, get_services(request), review, body)
    except ValueError:
        return _respond(request, review, est, "La réponse est vide.", "error")
    except ReplyNotSupported as e:
        return _respond(request, review, est, str(e), "warn")
    except PlatformError as e:
        review = get_review(conn, review.id)
        return _respond(request, review, est, f"Publication impossible pour le moment ({e}). "
                        "La réponse est approuvée et sera republiée automatiquement.", "warn")
    return _respond(request, review, est, "Réponse publiée.")


@router.post("/reviews/{review_id}/published-manually")
def review_published_manually(request: Request, review_id: int, text: str = Form("")):
    """Flux « réponse à copier » (Tripadvisor) : le commerçant confirme avoir publié la réponse lui-même."""
    _, review, est = _owned_review(request, review_id)
    body = text.strip() or (review.reply_draft or "")
    try:
        review = mark_published_manually(get_db(request), get_services(request), review, body)
    except ValueError as e:
        message = str(e) if "API" in str(e) else "La réponse est vide."
        return _respond(request, review, est, message, "error")
    return _respond(request, review, est, f"Réponse enregistrée comme publiée sur {PLATFORM_LABELS[review.platform]}.")


@router.post("/reviews/{review_id}/draft")
def review_save_draft(request: Request, review_id: int, text: str = Form("")):
    _, review, est = _owned_review(request, review_id)
    review = save_draft(get_db(request), review, text)
    return _respond(request, review, est, "Brouillon enregistré.")


@router.post("/reviews/{review_id}/regenerate")
def review_regenerate(request: Request, review_id: int):
    _, review, est = _owned_review(request, review_id)
    review = create_draft(get_db(request), get_services(request), est, review)
    return _respond(request, review, est, "Nouveau brouillon généré.")


@router.post("/reviews/{review_id}/skip")
def review_skip(request: Request, review_id: int):
    _, review, est = _owned_review(request, review_id)
    review = skip_review(get_db(request), review)
    return _respond(request, review, est, "Avis ignoré.")


@router.post("/reviews/{review_id}/reopen")
def review_reopen(request: Request, review_id: int):
    _, review, est = _owned_review(request, review_id)
    review = reopen_review(get_db(request), review)
    return _respond(request, review, est, "Avis remis dans la file.")
