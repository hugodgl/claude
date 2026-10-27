"""Envoi d'emails : console (défaut, tests), SMTP, Resend."""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import httpx

from .settings import Settings, get_settings


@dataclass
class Email:
    to: list[str]
    subject: str
    html: str
    text: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


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


class SMTPMailer:
    name = "smtp"

    def __init__(self, host: str, port: int = 587, user: str | None = None, password: str | None = None,
                 starttls: bool = True, default_sender: str = "noreply@example.com"):
        self.host, self.port, self.user, self.password, self.starttls = host, port, user, password, starttls
        self.default_sender = default_sender

    def build(self, email: Email, sender: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(email.to)
        msg["Subject"] = email.subject
        if email.reply_to:
            msg["Reply-To"] = email.reply_to
        for k, v in email.headers.items():
            msg[k] = v
        msg.set_content(email.text or "Version texte indisponible.")
        msg.add_alternative(email.html, subtype="html")
        return msg

    def send(self, email: Email, *, sender: str | None = None) -> str:
        msg = self.build(email, sender or self.default_sender)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password or "")
            smtp.send_message(msg)
        return msg["Message-ID"] or "smtp"


class ResendMailer:
    name = "resend"

    def __init__(self, api_key: str, default_sender: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.default_sender = default_sender
        self._client = client or httpx.Client(timeout=30)

    def send(self, email: Email, *, sender: str | None = None) -> str:
        payload = {
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
        r = self._client.post("https://api.resend.com/emails", json=payload,
                              headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return r.json().get("id", "resend")


def get_mailer(settings: Settings | None = None) -> Mailer:
    s = settings or get_settings()
    if s.mail_provider == "console":
        return ConsoleMailer()
    if s.mail_provider == "smtp":
        return SMTPMailer(s.smtp_host, s.smtp_port, s.smtp_user, s.smtp_password, s.smtp_starttls, s.mail_from)
    if s.mail_provider == "resend":
        if not s.resend_api_key:
            raise RuntimeError("RESEND_API_KEY manquant")
        return ResendMailer(s.resend_api_key, s.mail_from)
    raise RuntimeError(f"fournisseur mail inconnu : {s.mail_provider}")
