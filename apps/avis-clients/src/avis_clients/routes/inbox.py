"""Boîte de réception des avis : brouillons, publication, régénération, ignorer (HTMX)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from ..deps import get_db, get_services, is_htmx, not_found, redirect, render_template, require_account
from ..gbp import GBPError
from ..repo import get_establishment, get_review, list_establishments, list_reviews
from ..reviews import (
    create_draft,
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


@router.get("/inbox")
def inbox(request: Request, status: str = "draft", establishment: int | None = None):
    account = require_account(request)
    conn = get_db(request)
    establishments = list_establishments(conn, account.id)
    ids = [e.id for e in establishments if establishment is None or e.id == establishment]
    status_filter = None if status == "all" else status
    if status == "draft":
        reviews = list_reviews(conn, ids, status="draft") + list_reviews(conn, ids, status="approved")
        reviews.sort(key=lambda r: r.created_at, reverse=True)
    else:
        reviews = list_reviews(conn, ids, status=status_filter)
    return render_template(
        request, "app/inbox.html", reviews=reviews, establishments=establishments,
        establishments_by_id={e.id: e for e in establishments}, status=status, filters=STATUS_FILTERS,
        selected_establishment=establishment,
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
    msg = (f"Synchronisation : {summary.fetched} avis lus, {summary.new} nouveau(x), {summary.drafts} brouillon(s), "
           f"{summary.alerts} alerte(s), {summary.auto_published} auto-publié(s).")
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
    except GBPError as e:
        review = get_review(conn, review.id)
        return _respond(request, review, est, f"Publication impossible pour le moment ({e}). "
                        "La réponse est approuvée et sera republiée automatiquement.", "warn")
    return _respond(request, review, est, "Réponse publiée.")


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
