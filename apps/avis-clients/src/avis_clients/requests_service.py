"""Demandes d'avis : envoi SMS / WhatsApp / email avec quota mensuel et liste STOP, import CSV."""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
import unicodedata
from dataclasses import dataclass

from core.mail import Email

from .billing import account_access, sms_quota
from .db import log_event, now_iso, utcnow
from .models import Account, Establishment, ReviewRequest
from .repo import (
    add_optout,
    count_messages_in_month,
    insert_review_request,
    is_opted_out,
    is_valid_email,
    last_request_account_for_phone,
)
from .sms import SMSError, looks_like_stop, normalize_phone, render_message
from .templating import render

log = logging.getLogger(__name__)

PHONE_HEADERS = {"telephone", "tel", "phone", "mobile", "numero", "portable", "gsm"}
NAME_HEADERS = {"prenom", "firstname", "first_name", "nom", "name", "client"}


@dataclass
class SendOutcome:
    request: ReviewRequest | None
    ok: bool
    reason: str


def current_month() -> str:
    return utcnow().strftime("%Y-%m")


def quota_status(conn: sqlite3.Connection, account: Account, settings) -> dict[str, int]:
    access = account_access(account, settings)
    quota = sms_quota(access, settings)
    used = count_messages_in_month(conn, account.id, current_month())
    return {"quota": quota, "used": used, "remaining": max(0, quota - used)}


def public_link(settings, establishment: Establishment) -> str:
    return f"{settings.app_base_url.rstrip('/')}/r/{establishment.slug}"


def send_review_request(
    conn: sqlite3.Connection,
    services,
    account: Account,
    establishment: Establishment,
    *,
    channel: str,
    recipient: str,
    first_name: str | None = None,
) -> SendOutcome:
    settings = services.settings
    link = public_link(settings, establishment)
    message = render_message(establishment.request_template, prenom=first_name,
                             etablissement=establishment.name, lien=link)

    if channel in ("sms", "whatsapp"):
        phone = normalize_phone(recipient)
        if not phone:
            return SendOutcome(None, False, "numéro invalide")
        if is_opted_out(conn, phone, account.id):
            req = insert_review_request(conn, establishment_id=establishment.id, channel=channel,
                                        recipient=phone, first_name=first_name, message=message,
                                        status="blocked_optout")
            return SendOutcome(req, False, "numéro en liste STOP")
        q = quota_status(conn, account, settings)
        if q["remaining"] <= 0:
            req = insert_review_request(conn, establishment_id=establishment.id, channel=channel,
                                        recipient=phone, first_name=first_name, message=message,
                                        status="blocked_quota")
            return SendOutcome(req, False, f"quota mensuel atteint ({q['used']}/{q['quota']})")
        try:
            result = services.sms.send(phone, message, channel=channel)
        except SMSError as e:
            req = insert_review_request(conn, establishment_id=establishment.id, channel=channel,
                                        recipient=phone, first_name=first_name, message=message,
                                        status="failed", provider=services.sms.name, error=str(e)[:300])
            log_event(conn, "review_request_failed", account_id=account.id, establishment_id=establishment.id,
                      channel=channel, error=str(e)[:300])
            return SendOutcome(req, False, f"échec d'envoi : {e}")
        req = insert_review_request(conn, establishment_id=establishment.id, channel=channel, recipient=phone,
                                    first_name=first_name, message=message, status=result.status,
                                    provider=result.provider, provider_message_id=result.message_id,
                                    sent_at=now_iso())
        log_event(conn, "review_request_sent", account_id=account.id, establishment_id=establishment.id,
                  channel=channel, status=result.status, provider=result.provider)
        return SendOutcome(req, True, "envoyé" if result.status == "sent" else "simulé (dry-run)")

    if channel == "email":
        email = (recipient or "").strip().lower()
        if not is_valid_email(email):
            return SendOutcome(None, False, "email invalide")
        html = render("emails/review_request.html", establishment=establishment, prenom=first_name or "",
                      lien=link, app_name=settings.app_name)
        try:
            mid = services.mailer.send(
                Email(to=[email], subject=f"Votre avis sur {establishment.name}", html=html, text=message,
                      reply_to=establishment.notification_email or account.email),
                sender=settings.mail_from,
            )
        except Exception as e:  # noqa: BLE001 - on journalise toute erreur d'envoi
            req = insert_review_request(conn, establishment_id=establishment.id, channel=channel,
                                        recipient=email, first_name=first_name, message=message,
                                        status="failed", provider=services.mailer.name, error=str(e)[:300])
            return SendOutcome(req, False, f"échec d'envoi : {e}")
        req = insert_review_request(conn, establishment_id=establishment.id, channel=channel, recipient=email,
                                    first_name=first_name, message=message, status="sent",
                                    provider=services.mailer.name, provider_message_id=str(mid),
                                    sent_at=now_iso())
        log_event(conn, "review_request_sent", account_id=account.id, establishment_id=establishment.id,
                  channel=channel, status="sent", provider=services.mailer.name)
        return SendOutcome(req, True, "envoyé")

    return SendOutcome(None, False, f"canal inconnu : {channel}")


def _norm_header(value: str) -> str:
    v = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().strip().lower()
    return v.replace(" ", "_")


def parse_contacts_csv(content: str) -> list[tuple[str, str]]:
    """Lit un CSV (séparateur , ou ;) avec colonnes téléphone / prénom. Retourne [(téléphone, prénom)]."""
    content = content.lstrip("﻿")
    sample = content[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(content), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [_norm_header(c) for c in rows[0]]
    phone_idx, name_idx, has_header = 0, 1, False
    for i, h in enumerate(header):
        if h in PHONE_HEADERS:
            phone_idx, has_header = i, True
        elif h in NAME_HEADERS:
            name_idx, has_header = i, True
    data = rows[1:] if has_header else rows
    out: list[tuple[str, str]] = []
    for r in data:
        phone = r[phone_idx].strip() if len(r) > phone_idx else ""
        name = r[name_idx].strip() if len(r) > name_idx and name_idx != phone_idx else ""
        if phone:
            out.append((phone, name))
    return out


def handle_inbound_sms(conn: sqlite3.Connection, from_phone: str | None, body: str | None) -> bool:
    """Traite un SMS entrant : un STOP inscrit le numéro en liste d'opposition (compte du dernier envoi,
    sinon globale). Retourne True si un opt-out a été enregistré."""
    phone = normalize_phone(from_phone)
    if not phone or not looks_like_stop(body):
        return False
    account_id = last_request_account_for_phone(conn, phone)
    added = add_optout(conn, phone, account_id, source="sms-stop")
    log_event(conn, "optout", account_id=account_id, phone=phone, source="sms-stop", new=added)
    return True
