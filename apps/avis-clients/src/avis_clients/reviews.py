"""Avis : polling Google, brouillons LLM, alertes, publication des réponses."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from core.mail import Email

from .billing import account_access
from .db import log_event, normalize_iso, now_iso
from .drafts import generate_reply_draft, sanitize_reply
from .gbp import GBPError, GBPReview
from .models import Account, Establishment, Review
from .repo import (
    find_review,
    get_account,
    get_establishment,
    get_review,
    insert_review,
    list_establishments,
    list_reviews,
    update_review,
)
from .templating import render

log = logging.getLogger(__name__)


@dataclass
class PollSummary:
    establishments: int = 0
    fetched: int = 0
    new: int = 0
    updated: int = 0  # avis déjà connus dont le client a modifié le texte ou la note
    drafts: int = 0
    alerts: int = 0
    auto_published: int = 0
    published_pending: int = 0
    skipped_readonly: int = 0  # établissements de comptes en lecture seule (essai terminé sans abonnement)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def review_payload(review: Review | dict) -> dict:
    if isinstance(review, dict):
        return review
    return {"rating": review.rating, "author": review.author, "text": review.text}


def send_negative_alert(services, account: Account, establishment: Establishment, review: Review,
                        draft: str) -> None:
    settings = services.settings
    to = establishment.notification_email or account.email
    inbox_url = f"{settings.app_base_url.rstrip('/')}/app/inbox"
    html = render("emails/alert_negative_review.html", establishment=establishment, review=review,
                  draft=draft, inbox_url=inbox_url, app_name=settings.app_name)
    text = (f"Nouvel avis {review.rating} étoile(s) sur {establishment.name} par {review.author or 'Anonyme'} :\n\n"
            f"{review.text or '(sans texte)'}\n\nBrouillon de réponse proposé :\n{draft}\n\n"
            f"Valider ou modifier : {inbox_url}")
    services.mailer.send(
        Email(to=[to], subject=f"[{settings.app_name}] Avis {review.rating} étoile(s) sur {establishment.name} : "
                               "réponse à valider", html=html, text=text),
        sender=settings.mail_from,
    )


def create_draft(conn: sqlite3.Connection, services, establishment: Establishment, review: Review) -> Review:
    """Génère le brouillon et mémorise sa provenance : « llm » (sortie conforme), « llm-cleaned » (liens,
    coordonnées ou longueur retirés mécaniquement) ou « fallback » (modèle indisponible ou non conforme).
    Seul un brouillon « llm » peut être auto-publié."""
    settings = services.settings
    result = generate_reply_draft(services.llm, establishment.name, establishment.tone, review_payload(review),
                                  max_words=settings.reply_max_words, alert_max_rating=settings.alert_max_rating)
    source = result.source if result.source == "fallback" or not result.issues else "llm-cleaned"
    update_review(conn, review.id, reply_status="draft", reply_draft=result.text, reply_draft_source=source)
    log_event(conn, "review_draft", account_id=establishment.account_id, establishment_id=establishment.id,
              review_id=review.id, source=source, issues=result.issues)
    return get_review(conn, review.id)  # type: ignore[return-value]


def publish_reply(conn: sqlite3.Connection, services, review: Review, text: str, *, actor: str = "user") -> Review:
    """Marque la réponse approuvée puis la publie via le client Google ; reste « approved » en cas d'échec."""
    text = sanitize_reply(text, max_words=10_000).strip()
    if not text:
        raise ValueError("réponse vide")
    establishment = get_establishment(conn, review.establishment_id)
    update_review(conn, review.id, reply_status="approved", reply_draft=text)
    try:
        services.gbp.reply(review.external_name or "", text)
    except GBPError as e:
        log_event(conn, "review_publish_failed", account_id=establishment.account_id if establishment else None,
                  establishment_id=review.establishment_id, review_id=review.id, error=str(e)[:300])
        raise
    update_review(conn, review.id, reply_status="published", reply_text=text, reply_published_at=now_iso())
    log_event(conn, "review_published", account_id=establishment.account_id if establishment else None,
              establishment_id=review.establishment_id, review_id=review.id, actor=actor)
    return get_review(conn, review.id)  # type: ignore[return-value]


def save_draft(conn: sqlite3.Connection, review: Review, text: str) -> Review:
    update_review(conn, review.id, reply_draft=text.strip(), reply_status="draft")
    return get_review(conn, review.id)  # type: ignore[return-value]


def skip_review(conn: sqlite3.Connection, review: Review) -> Review:
    update_review(conn, review.id, reply_status="skipped")
    return get_review(conn, review.id)  # type: ignore[return-value]


def reopen_review(conn: sqlite3.Connection, review: Review) -> Review:
    update_review(conn, review.id, reply_status="draft" if review.reply_draft else "none")
    return get_review(conn, review.id)  # type: ignore[return-value]


def _alert(conn: sqlite3.Connection, services, est: Establishment, account: Account, review: Review,
           summary: PollSummary) -> None:
    try:
        send_negative_alert(services, account, est, review, review.reply_draft or "")
        update_review(conn, review.id, alerted_at=now_iso())
        summary.alerts += 1
    except Exception as e:  # noqa: BLE001 - une alerte qui échoue ne bloque pas le poll
        log.warning("alerte email impossible : %s", e)
        summary.errors.append(f"alerte {est.name} : {e}")


def _auto_publish(conn: sqlite3.Connection, services, est: Establishment, review: Review,
                  summary: PollSummary) -> None:
    if review.reply_draft_source != "llm":
        # texte générique ou nettoyé mécaniquement : il attend une validation humaine
        log_event(conn, "auto_publish_skipped", account_id=est.account_id, establishment_id=est.id,
                  review_id=review.id, reason=review.reply_draft_source)
        return
    try:
        publish_reply(conn, services, review, review.reply_draft or "", actor="auto")
        summary.auto_published += 1
    except (GBPError, ValueError) as e:
        summary.errors.append(f"auto-publication {est.name} : {e}")


def _sync_existing(conn: sqlite3.Connection, services, est: Establishment, account: Account, existing: Review,
                   remote: GBPReview, summary: PollSummary) -> None:
    """Avis déjà connu : reprend une réponse publiée directement sur Google, puis répercute une modification
    du client (texte ou note) en régénérant le brouillon s'il n'a pas encore été validé."""
    settings = services.settings
    if remote.reply_text and existing.reply_status != "published":
        update_review(conn, existing.id, reply_text=remote.reply_text, reply_status="published",
                      reply_published_at=normalize_iso(remote.reply_time) or now_iso())
        return
    if remote.reply_text and existing.reply_status == "published" and remote.reply_text != existing.reply_text:
        update_review(conn, existing.id, reply_text=remote.reply_text)
    rating = min(5, max(1, remote.rating or existing.rating))
    text = remote.text or None
    if rating == existing.rating and text == existing.text:
        return
    update_review(conn, existing.id, rating=rating, text=text,
                  updated_at=normalize_iso(remote.update_time) or now_iso())
    summary.updated += 1
    log_event(conn, "review_updated", account_id=est.account_id, establishment_id=est.id, review_id=existing.id,
              rating=rating, previous_rating=existing.rating)
    if existing.reply_status in ("none", "draft"):
        review = create_draft(conn, services, est, get_review(conn, existing.id))  # type: ignore[arg-type]
        summary.drafts += 1
        if rating <= settings.alert_max_rating and not review.alerted_at:
            _alert(conn, services, est, account, review, summary)


def poll_reviews(conn: sqlite3.Connection, services, establishment_ids: list[int] | None = None) -> PollSummary:
    """Récupère les avis de chaque établissement relié à Google, crée les brouillons, alerte, auto-publie.

    `establishment_ids=[]` ne traite rien (jamais « tous les établissements » par défaut depuis l'interface) ;
    les comptes en lecture seule sont ignorés (ni coût LLM, ni alerte, ni publication pour un essai terminé)."""
    settings = services.settings
    summary = PollSummary()
    establishments = list_establishments(conn)
    if establishment_ids is not None:
        wanted = set(establishment_ids)
        establishments = [e for e in establishments if e.id in wanted]
    accounts: dict[int, Account | None] = {}
    for est in establishments:
        if not est.google_location_name:
            summary.errors.append(f"{est.name} : aucune fiche Google reliée (google_location_name vide)")
            continue
        if est.account_id not in accounts:
            accounts[est.account_id] = get_account(conn, est.account_id)
        account = accounts[est.account_id]
        if account is None or not account_access(account, settings).can_write:
            summary.skipped_readonly += 1
            continue
        summary.establishments += 1
        try:
            remote = services.gbp.list_reviews(est.google_location_name)
        except GBPError as e:
            summary.errors.append(f"{est.name} : {e}")
            log_event(conn, "poll_error", account_id=est.account_id, establishment_id=est.id, error=str(e)[:300])
            continue
        summary.fetched += len(remote)
        for r in remote:
            existing = find_review(conn, est.id, "google", r.review_id)
            if existing:
                _sync_existing(conn, services, est, account, existing, r, summary)
                continue
            rating = min(5, max(1, r.rating or 3))
            review = insert_review(
                conn, establishment_id=est.id, platform="google", external_id=r.review_id,
                external_name=r.name, author=r.author, rating=rating, text=r.text or None,
                created_at=r.create_time, updated_at=r.update_time,
                reply_text=r.reply_text, reply_status="published" if r.reply_text else "none",
                reply_published_at=r.reply_time if r.reply_text else None,
            )
            summary.new += 1
            log_event(conn, "review_new", account_id=est.account_id, establishment_id=est.id,
                      review_id=review.id, rating=rating)
            if r.reply_text:
                continue
            review = create_draft(conn, services, est, review)
            summary.drafts += 1
            if rating <= settings.alert_max_rating:
                _alert(conn, services, est, account, review, summary)
            elif est.auto_publish and rating >= settings.auto_publish_min_rating:
                _auto_publish(conn, services, est, review, summary)
        # réponses approuvées dont la publication avait échoué
        for pending in list_reviews(conn, [est.id], status="approved"):
            try:
                publish_reply(conn, services, pending, pending.reply_draft or "", actor="retry")
                summary.published_pending += 1
            except (GBPError, ValueError) as e:
                summary.errors.append(f"publication différée {est.name} : {e}")
    log_event(conn, "poll_done", **summary.as_dict())
    return summary
