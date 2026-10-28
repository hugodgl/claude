"""Envoi d'emails : console (défaut, tests), SMTP, Resend.

Contrat unique : `mailer.send(email, sender=...) -> identifiant de message`. Tout échec d'envoi
lève MailError (sous-classe de RuntimeError) avec un message qui nomme la cause.
"""
from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Protocol

import httpx

from .settings import Settings, get_settings

RESEND_API_URL = "https://api.resend.com/emails"
# Validation volontairement minimale : quelque chose @ quelque chose, forme « Nom <adresse> » acceptée.
_ADDRESS_RE = re.compile(r"[^@\s<>]+@[^@\s<>]+")


class MailError(RuntimeError):
    """Échec d'envoi : connexion, authentification, destinataire refusé ou réponse d'API en erreur."""


@dataclass
class Email:
    """Un email à envoyer. `to` accepte une adresse seule ou une liste ; les entrées sont nettoyées
    et une adresse manifestement invalide (vide, sans `@`) lève ValueError dès la construction."""

    to: list[str]
    subject: str
    html: str
    text: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        recipients = [self.to] if isinstance(self.to, str) else list(self.to or [])
        cleaned: list[str] = []
        for address in recipients:
            if not isinstance(address, str) or not _ADDRESS_RE.search(address):
                raise ValueError(f"Email : destinataire invalide {address!r}")
            cleaned.append(address.strip())
        if not cleaned:
            raise ValueError("Email : aucun destinataire")
        self.to = cleaned


class Mailer(Protocol):
    name: str

    def send(self, email: Email, *, sender: str | None = None) -> str: ...


@dataclass
class ConsoleMailer:
    """Affiche l'email et le garde en mémoire (`sent`) : utile en dry-run et dans les tests."""

    name: str = "console"
    quiet: bool = False
    sent: list[Email] = field(default_factory=list)

    def send(self, email: Email, *, sender: str | None = None) -> str:
        self.sent.append(email)
        if not self.quiet:
            print(f"[mail console] de={sender} à={', '.join(email.to)} objet={email.subject!r} "
                  f"({len(email.html)} caractères HTML)")
        return f"console-{len(self.sent)}"


def _sender_domain(sender: str) -> str | None:
    address = parseaddr(sender)[1]
    return address.rpartition("@")[2] or None


class SMTPMailer:
    """Envoi par SMTP : STARTTLS (défaut, certificat vérifié) puis authentification si `user` est renseigné.

    Le message reçoit un `Message-ID` réel (domaine de l'expéditeur) et une date ; c'est cet
    identifiant que `send` retourne. Les sujets et noms accentués sont encodés par la bibliothèque
    standard (RFC 2047). Le port 465 (TLS implicite) n'est pas géré : utiliser 587 + STARTTLS.
    """

    name = "smtp"

    def __init__(self, host: str, port: int = 587, user: str | None = None, password: str | None = None,
                 starttls: bool = True, default_sender: str = "noreply@example.com", timeout_s: float = 30.0):
        self.host, self.port, self.user, self.password, self.starttls = host, port, user, password, starttls
        self.default_sender = default_sender
        self.timeout_s = timeout_s

    def build(self, email: Email, sender: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(email.to)
        msg["Subject"] = email.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=_sender_domain(sender))
        if email.reply_to:
            msg["Reply-To"] = email.reply_to
        for k, v in email.headers.items():
            del msg[k]  # un en-tête explicite remplace celui posé ci-dessus (ex. Reply-To), sans doublon
            msg[k] = v
        # quoted-printable : message 7 bits propre (smtplib n'annonce pas 8BITMIME), texte lisible par les filtres
        msg.set_content(email.text or "Version texte indisponible.", cte="quoted-printable")
        msg.add_alternative(email.html, subtype="html", cte="quoted-printable")
        return msg

    def send(self, email: Email, *, sender: str | None = None) -> str:
        msg = self.build(email, sender or self.default_sender)
        where = f"{self.host}:{self.port}"
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.user:
                    smtp.login(self.user, self.password or "")
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            raise MailError(f"SMTP : authentification refusée pour {self.user!r} sur {where} ({e})") from e
        except smtplib.SMTPRecipientsRefused as e:
            refused = ", ".join(f"{addr} ({code})" for addr, (code, _msg) in e.recipients.items())
            raise MailError(f"SMTP : destinataires refusés par {where} : {refused}") from e
        except smtplib.SMTPNotSupportedError as e:
            raise MailError(f"SMTP : option non prise en charge par {where} ({e}) : vérifier SMTP_STARTTLS "
                            "et SMTP_USER") from e
        except smtplib.SMTPException as e:
            raise MailError(f"SMTP : envoi refusé par {where} ({e})") from e
        except OSError as e:  # connexion refusée, DNS, délai, erreur TLS
            raise MailError(f"SMTP : connexion impossible à {where} ({e})") from e
        return msg["Message-ID"]


class ResendMailer:
    """Envoi via l'API Resend (`POST /emails`). Les erreurs HTTP et réseau deviennent des MailError."""

    name = "resend"

    def __init__(self, api_key: str, default_sender: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.default_sender = default_sender
        self._client = client or httpx.Client(timeout=30)

    def send(self, email: Email, *, sender: str | None = None) -> str:
        payload: dict[str, object] = {
            "from": sender or self.default_sender,
            "to": email.to,
            "subject": email.subject,
            "html": email.html,
        }
        if email.text:
            payload["text"] = email.text
        if email.reply_to:
            payload["reply_to"] = email.reply_to
        if email.headers:
            payload["headers"] = email.headers
        try:
            r = self._client.post(RESEND_API_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            raise MailError(f"Resend injoignable ({e})") from e
        if r.status_code >= 400:
            raise MailError(f"Resend HTTP {r.status_code} : {_resend_error(r)}")
        try:
            return str(r.json().get("id") or "resend")
        except ValueError:
            return "resend"


def _resend_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = f"{body.get('name', 'erreur')} : {body.get('message', '')}".strip(" :")
    except (ValueError, AttributeError):
        detail = response.text[:200]
    if response.status_code in (401, 403):
        detail += " (vérifier RESEND_API_KEY et le domaine expéditeur validé chez Resend)"
    elif response.status_code == 429:
        detail += " (quota Resend atteint, réessayer plus tard)"
    return detail


def get_mailer(settings: Settings | None = None) -> Mailer:
    """Construit le mailer désigné par `settings.mail_provider` (réglages lus par défaut)."""
    s = settings or get_settings()
    if s.mail_provider == "console":
        return ConsoleMailer()
    if s.mail_provider == "smtp":
        return SMTPMailer(s.smtp_host, s.smtp_port, s.smtp_user, s.smtp_password, s.smtp_starttls, s.mail_from)
    if s.mail_provider == "resend":
        if not s.resend_api_key:
            raise MailError("RESEND_API_KEY manquant alors que MAIL_PROVIDER=resend")
        return ResendMailer(s.resend_api_key, s.mail_from)
    raise MailError(f"fournisseur mail inconnu : {s.mail_provider}")
