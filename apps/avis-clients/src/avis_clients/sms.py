"""Envoi de SMS / WhatsApp : adaptateurs dry-run (défaut), smsmode et Twilio ; numéros et modèles."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

import httpx

from .settings import AppSettings

log = logging.getLogger(__name__)

DEFAULT_REQUEST_TEMPLATE = (
    "Bonjour {prenom}, merci pour votre visite chez {etablissement}. Un avis en 30 s nous aide "
    "beaucoup : {lien}. Répondre STOP pour ne plus recevoir de message."
)
STOP_WORDS = {"stop", "stop sms", "stop mms", "arret", "arrêt", "desabonnement", "désabonnement"}


class SMSError(RuntimeError):
    """Échec d'envoi (configuration, réseau, refus du fournisseur)."""


@dataclass
class SMSResult:
    provider: str
    status: str  # "sent" | "dry-run"
    message_id: str | None
    raw: Any = None


class SMSSender(Protocol):
    name: str

    def send(self, to: str, text: str, *, channel: str = "sms") -> SMSResult: ...


def normalize_phone(raw: str | None, default_country: str = "33") -> str | None:
    """Normalise au format E.164 (+33612345678). Retourne None si le numéro est inexploitable."""
    if not raw:
        return None
    s = re.sub(r"[\s.\-()]", "", raw.strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
        if digits.isdigit() and 8 <= len(digits) <= 15:
            return "+" + digits
        return None
    if not s.isdigit():
        return None
    if len(s) == 10 and s[0] == "0":
        return f"+{default_country}{s[1:]}"
    if len(s) == 9 and s[0] in "1234567896":
        return f"+{default_country}{s}"
    return None


def looks_like_stop(body: str | None) -> bool:
    if not body:
        return False
    text = unicodedata.normalize("NFKD", body).encode("ascii", "ignore").decode().strip().lower()
    text = re.sub(r"[^a-z ]", "", text).strip()
    return text in STOP_WORDS or text.startswith("stop")


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_message(template: str, *, prenom: str | None, etablissement: str, lien: str) -> str:
    msg = template.format_map(_SafeDict(prenom=(prenom or "").strip(), etablissement=etablissement, lien=lien))
    msg = re.sub(r"Bonjour\s+,", "Bonjour,", msg)
    return re.sub(r"[ \t]{2,}", " ", msg).strip()


# ------------------------------------------------------------------------------------------
# Adaptateurs
# ------------------------------------------------------------------------------------------
@dataclass
class DryRunSMS:
    """N'envoie rien : journalise et garde les messages en mémoire (tests, démo, sandbox)."""

    name: str = "dry-run"
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(self, to: str, text: str, *, channel: str = "sms") -> SMSResult:
        message_id = f"dry-run-{uuid4().hex[:12]}"
        self.sent.append({"to": to, "text": text, "channel": channel, "id": message_id})
        log.info("[sms dry-run] %s → %s : %s", channel, to, text)
        return SMSResult(provider=self.name, status="dry-run", message_id=message_id)


class SmsmodeSMS:
    """smsmode (fournisseur français). Deux API : REST v1 (défaut) ou HTTP 1.6 historique.

    REST : POST https://rest.smsmode.com/sms/v1/messages, en-tête X-Api-Key, corps JSON
           {"recipient": {"to": "33612345678"}, "body": {"text": "..."}, "from": "EMETTEUR"}.
    HTTP 1.6 : POST https://api.smsmode.com/http/1.6/sendSMS.do (accessToken, message, numero, emetteur),
           réponse texte « code | libellé | smsID » (code 0 = accepté).
    Les deux formats sont écrits d'après la documentation publique : à vérifier au premier envoi réel.
    """

    name = "smsmode"
    REST_URL = "https://rest.smsmode.com/sms/v1/messages"
    HTTP16_URL = "https://api.smsmode.com/http/1.6/sendSMS.do"

    def __init__(self, api_key: str, sender: str, api: str = "rest", client: httpx.Client | None = None):
        self.api_key = api_key
        self.sender = sender[:11]
        self.api = api
        self._client = client or httpx.Client(timeout=20)

    def send(self, to: str, text: str, *, channel: str = "sms") -> SMSResult:
        if channel != "sms":
            raise SMSError("smsmode : seul le canal SMS est pris en charge")
        number = to.lstrip("+")
        try:
            if self.api == "http16":
                r = self._client.post(self.HTTP16_URL, data={
                    "accessToken": self.api_key, "message": text, "numero": number, "emetteur": self.sender,
                })
                parts = [p.strip() for p in r.text.split("|")]
                if r.status_code >= 400 or not parts or parts[0] != "0":
                    raise SMSError(f"smsmode : {r.text[:200]}")
                return SMSResult(self.name, "sent", parts[2] if len(parts) > 2 else None, r.text)
            r = self._client.post(
                self.REST_URL,
                json={"recipient": {"to": number}, "body": {"text": text}, "from": self.sender},
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
            )
            if r.status_code >= 400:
                raise SMSError(f"smsmode HTTP {r.status_code} : {r.text[:200]}")
            data = r.json() if r.content else {}
            return SMSResult(self.name, "sent", data.get("messageId") or data.get("id"), data)
        except httpx.HTTPError as e:
            raise SMSError(f"smsmode injoignable : {e}") from e


class TwilioSMS:
    """Twilio Messages API (SMS et WhatsApp via le préfixe « whatsapp: »)."""

    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 whatsapp_from: str | None = None, client: httpx.Client | None = None):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.whatsapp_from = whatsapp_from
        self._client = client or httpx.Client(timeout=20)

    def send(self, to: str, text: str, *, channel: str = "sms") -> SMSResult:
        if channel == "whatsapp":
            if not self.whatsapp_from:
                raise SMSError("TWILIO_WHATSAPP_FROM manquant pour le canal WhatsApp")
            sender = self.whatsapp_from
            if not sender.startswith("whatsapp:"):
                sender = f"whatsapp:{sender}"
            recipient = f"whatsapp:{to}"
        else:
            sender, recipient = self.from_number, to
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        try:
            r = self._client.post(url, data={"To": recipient, "From": sender, "Body": text},
                                  auth=(self.account_sid, self.auth_token))
        except httpx.HTTPError as e:
            raise SMSError(f"Twilio injoignable : {e}") from e
        if r.status_code >= 400:
            raise SMSError(f"Twilio HTTP {r.status_code} : {r.text[:200]}")
        data = r.json()
        return SMSResult(self.name, "sent", data.get("sid"), data)


def build_sms_sender(settings: AppSettings, client: httpx.Client | None = None) -> SMSSender:
    if settings.sms_provider == "dry-run":
        return DryRunSMS()
    if settings.sms_provider == "smsmode":
        if not settings.smsmode_api_key:
            raise SMSError("SMSMODE_API_KEY manquant")
        return SmsmodeSMS(settings.smsmode_api_key, settings.sms_sender, settings.smsmode_api, client)
    if settings.sms_provider == "twilio":
        if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from):
            raise SMSError("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN et TWILIO_FROM sont requis")
        return TwilioSMS(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from,
                         settings.twilio_whatsapp_from, client)
    raise SMSError(f"fournisseur SMS inconnu : {settings.sms_provider}")
