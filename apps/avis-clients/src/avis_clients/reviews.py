"""Avis : poll multi-plateformes (Google, Facebook, Tripadvisor), brouillons LLM, alertes, publication des réponses."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta

from core.mail import Email

from .billing import account_access
from .crypto import TokenKeyError
from .db import log_event, normalize_iso, now_iso, parse_iso, utcnow
from .drafts import generate_reply_draft, sanitize_reply
from .models import Account, Establishment, Review, ReviewSource
from .platforms import PLATFORMS, PlatformAuthError, PlatformError, RemoteReview, platform_label
from .repo import (
    find_review,
    get_account,
    get_establishment,
    get_review,
    get_source,
    insert_review,
    list_establishments,
    list_reviews,
    list_sources_for_establishments,
    mark_source_error,
    mark_source_synced,
    update_review,
)
from .templating import render

log = logging.getLogger(__name__)

PLATFORM_COUNTERS = ("sources", "fetched", "new", "updated", "drafts", "errors")


class ReplyNotSupported(PlatformError):
    """La plateforme n'a pas d'API de réponse (Tripadvisor) : flux « réponse à copier »."""


@dataclass
class PollSummary:
    establishments: int = 0
    sources: int = 0  # sources interrogées avec succès
    fetched: int = 0
    new: int = 0
    updated: int = 0  # avis déjà connus dont le client a modifié le texte ou la note
    drafts: int = 0
    alerts: int = 0
    auto_published: int = 0
    published_pending: int = 0
    skipped_readonly: int = 0  # établissements de comptes en lecture seule (essai terminé sans abonnement)
    skipped_recent: int = 0  # sources Tripadvisor interrogées il y a moins de TRIPADVISOR_POLL_INTERVAL_MIN
    errors: list[str] = field(default_factory=list)
    by_platform: dict[str, dict[str, int]] = field(default_factory=dict)

    def count(self, platform: str, key: str, n: int = 1) -> None:
        self.by_platform.setdefault(platform, {k: 0 for k in PLATFORM_COUNTERS})[key] += n

    def as_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "by_platform"}
        data["by_platform"] = {p: dict(c) for p, c in self.by_platform.items()}
        return data

    def platform_line(self, key: str = "fetched") -> str:
        """« Google 5, Facebook 4 » pour les messages de l'interface."""
        parts = [f"{platform_label(p)} {c.get(key, 0)}" for p in PLATFORMS if p in self.by_platform
                 for c in [self.by_platform[p]]]
        return ", ".join(parts)


def review_payload(review: Review | dict) -> dict:
    if isinstance(review, dict):
        return review
    return {"rating": review.rating, "author": review.author, "text": review.text}


def send_negative_alert(services, account: Account, establishment: Establishment, review: Review,
                        draft: str) -> None:
    settings = services.settings
    to = establishment.notification_email or account.email
    inbox_url = f"{settings.app_base_url.rstrip('/')}/app/inbox"
    label = platform_label(review.platform)
    html = render("emails/alert_negative_review.html", establishment=establishment, review=review,
                  draft=draft, inbox_url=inbox_url, app_name=settings.app_name, platform_label=label)
    text = (f"Nouvel avis {review.rating} étoile(s) sur {establishment.name} ({label}) par "
            f"{review.author or 'Anonyme'} :\n\n{review.text or '(sans texte)'}\n\n"
            + (f"{review.rating_note}\n\n" if review.rating_note else "")
            + f"Brouillon de réponse proposé :\n{draft}\n\nValider ou modifier : {inbox_url}")
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
              review_id=review.id, source=source, issues=result.issues, platform=review.platform)
    return get_review(conn, review.id)  # type: ignore[return-value]


def _credentials(services, source: ReviewSource) -> str | None:
    """Jeton déchiffré de la source (Facebook) ; clé absente ou changée → erreur d'authentification lisible."""
    if not source.credentials_enc:
        return None
    try:
        return services.cipher.decrypt(source.credentials_enc)
    except TokenKeyError as e:
        raise PlatformAuthError(str(e)) from e


def publish_reply(conn: sqlite3.Connection, services, review: Review, text: str, *, actor: str = "user") -> Review:
    """Marque la réponse approuvée puis la publie via l'adaptateur de la plateforme ; reste « approved » en
    cas d'échec (republication au poll suivant). Plateforme sans API de réponse → `ReplyNotSupported`
    avant toute approbation (flux « réponse à copier »)."""
    text = sanitize_reply(text, max_words=10_000).strip()
    if not text:
        raise ValueError("réponse vide")
    client = services.platforms.get(review.platform)
    if client is None or not client.can_reply:
        raise ReplyNotSupported(f"{platform_label(review.platform)} : pas de publication par API ; copiez la "
                                "réponse, publiez-la sur la plateforme puis confirmez.")
    establishment = get_establishment(conn, review.establishment_id)
    source = get_source(conn, review.establishment_id, review.platform)
    if source is None:
        raise PlatformError(f"{platform_label(review.platform)} : aucune source reliée à cet établissement")
    update_review(conn, review.id, reply_status="approved", reply_draft=text)
    try:
        client.publish_reply(source, _credentials(services, source), review.external_name or "", text)
    except PlatformError as e:
        log_event(conn, "review_publish_failed", account_id=establishment.account_id if establishment else None,
                  establishment_id=review.establishment_id, review_id=review.id, platform=review.platform,
                  error=str(e)[:300])
        raise
    update_review(conn, review.id, reply_status="published", reply_text=text, reply_published_at=now_iso())
    log_event(conn, "review_published", account_id=establishment.account_id if establishment else None,
              establishment_id=review.establishment_id, review_id=review.id, actor=actor, platform=review.platform)
    return get_review(conn, review.id)  # type: ignore[return-value]


def mark_published_manually(conn: sqlite3.Connection, services, review: Review, text: str) -> Review:
    """Flux « réponse à copier » (Tripadvisor) : le commerçant a publié la réponse lui-même sur la plateforme."""
    text = sanitize_reply(text, max_words=10_000).strip()
    if not text:
        raise ValueError("réponse vide")
    client = services.platforms.get(review.platform)
    if client is not None and client.can_reply:
        raise ValueError(f"{platform_label(review.platform)} publie par API : utilisez « Publier ».")
    establishment = get_establishment(conn, review.establishment_id)
    update_review(conn, review.id, reply_status="published_manually", reply_text=text, reply_draft=text,
                  reply_published_at=now_iso())
    log_event(conn, "review_published", account_id=establishment.account_id if establishment else None,
              establishment_id=review.establishment_id, review_id=review.id, actor="manual",
              platform=review.platform)
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
    client = services.platforms.get(review.platform)
    if client is None or not client.can_reply:
        # Tripadvisor : aucune API de réponse, le brouillon attend le flux « réponse à copier »
        log_event(conn, "auto_publish_skipped", account_id=est.account_id, establishment_id=est.id,
                  review_id=review.id, reason="platform_no_reply_api", platform=review.platform)
        return
    if review.reply_draft_source != "llm":
        # texte générique ou nettoyé mécaniquement : il attend une validation humaine
        log_event(conn, "auto_publish_skipped", account_id=est.account_id, establishment_id=est.id,
                  review_id=review.id, reason=review.reply_draft_source, platform=review.platform)
        return
    try:
        publish_reply(conn, services, review, review.reply_draft or "", actor="auto")
        summary.auto_published += 1
    except (PlatformError, ValueError) as e:
        summary.errors.append(f"auto-publication {est.name} : {e}")


def _sync_existing(conn: sqlite3.Connection, services, est: Establishment, account: Account, existing: Review,
                   remote: RemoteReview, summary: PollSummary) -> None:
    """Avis déjà connu : reprend une réponse publiée directement sur la plateforme, puis répercute une
    modification du client (texte ou note) en régénérant le brouillon s'il n'a pas encore été validé."""
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
    update_review(conn, existing.id, rating=rating, text=text, rating_note=remote.rating_note,
                  updated_at=normalize_iso(remote.update_time) or now_iso())
    summary.updated += 1
    summary.count(existing.platform, "updated")
    log_event(conn, "review_updated", account_id=est.account_id, establishment_id=est.id, review_id=existing.id,
              rating=rating, previous_rating=existing.rating, platform=existing.platform)
    if existing.reply_status in ("none", "draft"):
        review = create_draft(conn, services, est, get_review(conn, existing.id))  # type: ignore[arg-type]
        summary.drafts += 1
        summary.count(existing.platform, "drafts")
        if rating <= settings.alert_max_rating and not review.alerted_at:
            _alert(conn, services, est, account, review, summary)


def _recently_synced(source: ReviewSource, settings) -> bool:
    """Tripadvisor : la clé Content API a un quota mensuel ; une fiche n'est relue qu'après
    `TRIPADVISOR_POLL_INTERVAL_MIN` (après une erreur, même délai avant un nouvel essai)."""
    if source.platform != "tripadvisor" or settings.tripadvisor_poll_interval_min <= 0:
        return False
    reference = parse_iso(source.last_synced_at)
    if source.status == "error":
        reference = max(filter(None, (reference, parse_iso(source.updated_at))), default=None)
    return bool(reference) and utcnow() - reference < timedelta(minutes=settings.tripadvisor_poll_interval_min)


def _poll_source(conn: sqlite3.Connection, services, est: Establishment, account: Account, source: ReviewSource,
                 summary: PollSummary, force: bool) -> None:
    settings = services.settings
    label = platform_label(source.platform)
    client = services.platforms.get(source.platform)
    if client is None:
        summary.errors.append(f"{est.name} ({label}) : adaptateur non configuré")
        summary.count(source.platform, "errors")
        return
    if not force and _recently_synced(source, settings):
        summary.skipped_recent += 1
        return
    try:
        remote = client.fetch_reviews(source, _credentials(services, source))
    except PlatformError as e:
        # erreur isolée : la source est notée en erreur, les autres sources et établissements continuent
        mark_source_error(conn, source.id, str(e))
        summary.errors.append(f"{est.name} ({label}) : {e}")
        summary.count(source.platform, "errors")
        log_event(conn, "poll_error", account_id=est.account_id, establishment_id=est.id, platform=source.platform,
                  error=str(e)[:300], auth=isinstance(e, PlatformAuthError))
        return
    summary.sources += 1
    summary.count(source.platform, "sources")
    summary.fetched += len(remote)
    summary.count(source.platform, "fetched", len(remote))
    for r in remote:
        existing = find_review(conn, est.id, source.platform, r.review_id)
        if existing:
            _sync_existing(conn, services, est, account, existing, r, summary)
            continue
        rating = min(5, max(1, r.rating or 3))
        review = insert_review(
            conn, establishment_id=est.id, platform=source.platform, external_id=r.review_id,
            external_name=r.name or None, author=r.author, rating=rating, text=r.text or None,
            created_at=r.create_time, updated_at=r.update_time,
            reply_text=r.reply_text, reply_status="published" if r.reply_text else "none",
            reply_published_at=r.reply_time if r.reply_text else None, rating_note=r.rating_note,
        )
        summary.new += 1
        summary.count(source.platform, "new")
        log_event(conn, "review_new", account_id=est.account_id, establishment_id=est.id,
                  review_id=review.id, rating=rating, platform=source.platform)
        if r.reply_text:
            continue
        review = create_draft(conn, services, est, review)
        summary.drafts += 1
        summary.count(source.platform, "drafts")
        if rating <= settings.alert_max_rating:
            _alert(conn, services, est, account, review, summary)
        elif est.auto_publish and rating >= settings.auto_publish_min_rating:
            _auto_publish(conn, services, est, review, summary)
    mark_source_synced(conn, source.id)


def _publish_pending(conn: sqlite3.Connection, services, est: Establishment, summary: PollSummary) -> None:
    """Réponses approuvées dont la publication avait échoué (quota, réseau, jeton) : nouvel essai."""
    for pending in list_reviews(conn, [est.id], status="approved"):
        try:
            publish_reply(conn, services, pending, pending.reply_draft or "", actor="retry")
            summary.published_pending += 1
        except (PlatformError, ValueError) as e:
            summary.errors.append(f"publication différée {est.name} : {e}")


def poll_reviews(conn: sqlite3.Connection, services, establishment_ids: list[int] | None = None,
                 platforms: list[str] | None = None, force: bool = False) -> PollSummary:
    """Parcourt toutes les sources reliées (Google, Facebook, Tripadvisor) de chaque établissement, crée les
    brouillons, alerte, auto-publie. Erreurs isolées par source et par établissement, compteurs par plateforme.

    `establishment_ids=[]` ne traite rien (jamais « tous les établissements » par défaut depuis l'interface) ;
    `platforms` limite aux plateformes données ; `force` ignore l'intervalle minimal Tripadvisor ;
    les comptes en lecture seule sont ignorés (ni coût LLM, ni alerte, ni publication pour un essai terminé)."""
    settings = services.settings
    summary = PollSummary()
    wanted_platforms = None
    if platforms:
        unknown = sorted(set(platforms) - set(PLATFORMS))
        if unknown:
            raise ValueError(f"plateforme inconnue : {', '.join(unknown)} (attendu : {', '.join(PLATFORMS)})")
        wanted_platforms = set(platforms)
    establishments = list_establishments(conn)
    if establishment_ids is not None:
        wanted = set(establishment_ids)
        establishments = [e for e in establishments if e.id in wanted]
    sources_by_est: dict[int, list[ReviewSource]] = {}
    for source in list_sources_for_establishments(conn, [e.id for e in establishments]):
        sources_by_est.setdefault(source.establishment_id, []).append(source)
    accounts: dict[int, Account | None] = {}
    for est in establishments:
        sources = [s for s in sources_by_est.get(est.id, []) if s.status != "disabled"
                   and (wanted_platforms is None or s.platform in wanted_platforms)]
        if not sources:
            if wanted_platforms is None:
                summary.errors.append(f"{est.name} : aucune fiche Google, Page Facebook ni fiche Tripadvisor reliée")
            continue
        if est.account_id not in accounts:
            accounts[est.account_id] = get_account(conn, est.account_id)
        account = accounts[est.account_id]
        if account is None or not account_access(account, settings).can_write:
            summary.skipped_readonly += 1
            continue
        summary.establishments += 1
        for source in sources:
            _poll_source(conn, services, est, account, source, summary, force)
        _publish_pending(conn, services, est, summary)
    log_event(conn, "poll_done", **summary.as_dict())
    return summary
