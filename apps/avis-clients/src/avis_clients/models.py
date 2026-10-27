"""Modèles simples (dataclasses) construits à partir des lignes SQLite."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .db import parse_iso


@dataclass
class Account:
    id: int
    email: str
    created_at: str
    plan: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    subscription_status: str | None
    trial_ends_at: str
    last_login_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Account:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    @property
    def trial_end(self) -> datetime:
        return parse_iso(self.trial_ends_at)  # type: ignore[return-value]


@dataclass
class Establishment:
    id: int
    account_id: int
    name: str
    slug: str
    google_place_id: str | None
    google_location_name: str | None
    review_url: str
    tone_profile_json: str
    request_template: str
    notification_email: str | None
    auto_publish_positive: int
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Establishment:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    @property
    def tone(self) -> dict[str, Any]:
        try:
            data = json.loads(self.tone_profile_json or "{}")
        except json.JSONDecodeError:
            data = {}
        data.setdefault("style", "chaleureux")
        data.setdefault("signature", f"L'équipe de {self.name}")
        data.setdefault("do", [])
        data.setdefault("dont", [])
        data.setdefault("exemples", [])
        return data

    @property
    def auto_publish(self) -> bool:
        return bool(self.auto_publish_positive)


@dataclass
class Review:
    id: int
    establishment_id: int
    platform: str
    external_id: str
    external_name: str | None
    author: str | None
    rating: int
    text: str | None
    created_at: str
    updated_at: str | None
    fetched_at: str
    reply_text: str | None
    reply_status: str
    reply_draft: str | None
    reply_published_at: str | None
    alerted_at: str | None
    reply_draft_source: str | None = None  # "llm" | "llm-cleaned" | "fallback" ; None avant la migration 002

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Review:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    @property
    def draft_needs_care(self) -> bool:
        """Brouillon générique ou nettoyé mécaniquement : jamais auto-publié, à relire de près."""
        return self.reply_draft_source in ("fallback", "llm-cleaned")


@dataclass
class ReviewRequest:
    id: int
    establishment_id: int
    channel: str
    recipient: str
    first_name: str | None
    message: str
    sent_at: str | None
    status: str
    provider: str | None
    provider_message_id: str | None
    error: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ReviewRequest:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})
