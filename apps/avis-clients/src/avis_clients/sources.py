"""Liaison des sources d'avis Facebook et Tripadvisor : format de l'identifiant, unicité entre comptes,
vérification auprès de la plateforme, chiffrement du jeton. (Google garde son flux : réglages + `avis google link`.)

Règle d'isolation, identique à celle imposée pour Google (revue QA-1, C1) : un identifiant externe ne peut
être relié qu'à un seul établissement, et un compte ne relie que ce qu'il prouve posséder (jeton de Page
Facebook vérifié par `GET /me` ; fiche Tripadvisor publique → lecture seule, aucune réponse en son nom).
"""
from __future__ import annotations

import sqlite3

from .crypto import TokenKeyError
from .db import log_event
from .facebook import PAGE_ID_RE
from .models import Establishment, ReviewSource
from .platforms import PLATFORM_LABELS, PlatformError, platform_label
from .repo import SourceConflict, delete_source, get_source_by_external, upsert_source
from .tripadvisor import LOCATION_ID_RE

LINKABLE_PLATFORMS = ("facebook", "tripadvisor")
ID_RULES = {
    "facebook": (PAGE_ID_RE, "Identifiant de Page Facebook invalide : attendu l'identifiant numérique de la Page "
                             "(Page → À propos → Transparence de la Page → Identifiant)."),
    "tripadvisor": (LOCATION_ID_RE, "Identifiant de fiche Tripadvisor invalide : attendu le nombre qui suit « d » "
                                    "dans l'URL de la fiche (…-d1234567-…)."),
}


class SourceLinkError(ValueError):
    """Liaison refusée : message en français destiné au commerçant (ou à la sortie CLI)."""


def link_source(conn: sqlite3.Connection, services, establishment: Establishment, platform: str,
                external_id: str, credentials: str | None = None) -> ReviewSource:
    """Vérifie puis enregistre la source `platform` de l'établissement (remplace la précédente)."""
    if platform not in LINKABLE_PLATFORMS:
        raise SourceLinkError("Plateforme inconnue : facebook ou tripadvisor (Google se relie depuis les réglages "
                              "ou `avis google link`).")
    external_id = (external_id or "").strip()
    pattern, message = ID_RULES[platform]
    if not pattern.match(external_id):
        raise SourceLinkError(message)
    credentials = (credentials or "").strip() or None
    other = get_source_by_external(conn, platform, external_id)
    if other and other.establishment_id != establishment.id:
        raise SourceLinkError(f"Cette {'Page Facebook' if platform == 'facebook' else 'fiche Tripadvisor'} est déjà "
                              "reliée à un autre établissement.")
    client = services.platforms.get(platform)
    if client is None:
        raise SourceLinkError(f"{platform_label(platform)} : adaptateur non configuré.")
    if platform == "facebook" and not credentials and client.name == "live":
        raise SourceLinkError("Le jeton de Page longue durée est requis pour relier une Page Facebook.")
    try:
        info = client.verify_source(external_id, credentials)
    except PlatformError as e:
        raise SourceLinkError(f"Vérification impossible auprès de {platform_label(platform)} : {e}") from e
    credentials_enc = None
    if credentials:
        try:
            credentials_enc = services.cipher.encrypt(credentials)
        except TokenKeyError as e:
            raise SourceLinkError(str(e)) from e
    try:
        source = upsert_source(conn, establishment_id=establishment.id, platform=platform, external_id=external_id,
                               display_name=(info.get("name") or None), public_url=info.get("public_url"),
                               credentials_enc=credentials_enc)
    except SourceConflict as e:
        raise SourceLinkError(str(e)) from e
    log_event(conn, "source_linked", account_id=establishment.account_id, establishment_id=establishment.id,
              platform=platform, mode=client.name)
    return source


def unlink_source(conn: sqlite3.Connection, establishment: Establishment, platform: str) -> bool:
    if platform not in LINKABLE_PLATFORMS:
        raise SourceLinkError("Plateforme inconnue : facebook ou tripadvisor.")
    removed = delete_source(conn, establishment.id, platform)
    if removed:
        log_event(conn, "source_unlinked", account_id=establishment.account_id, establishment_id=establishment.id,
                  platform=platform)
    return removed


def secondary_review_links(sources: list[ReviewSource]) -> list[dict[str, str]]:
    """Liens « laisser un avis » des plateformes reliées autres que Google, pour la page publique.
    Google reste le bouton principal ; ces liens viennent après, sans aucun filtrage par note."""
    links = []
    for source in sources:
        if source.platform == "google" or source.status == "disabled" or not source.public_url:
            continue
        links.append({"platform": source.platform, "label": f"Laisser un avis sur {PLATFORM_LABELS[source.platform]}",
                      "url": source.public_url})
    return links
