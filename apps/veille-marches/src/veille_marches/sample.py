"""Exemple d'alerte de la page d'accueil, construit avec le vrai pipeline (filtrage, règles, score) sur une fixture."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .dates import days_until, utcnow
from .digest import Digest, DigestItem, render_digest
from .filtering import match_notice
from .models import LLMSummary, Notice, Subscriber
from .scoring import final_score, rules_score
from .settings import VMSettings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_notices.json"


@lru_cache(maxsize=1)
def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sample_digest(settings: VMSettings, now: datetime | None = None) -> Digest:
    now = now or utcnow()
    data = _fixture()
    sub = Subscriber(**data["subscriber"])   # sans id : aucun lien signé n'est rendu sur ces pages publiques
    digest = Digest(subscriber=sub, date=now)
    for raw in data["notices"]:
        fields = {k: v for k, v in raw.items() if k not in ("summary", "published_days_ago", "deadline_in_days",
                                                              "buyer_seen")}
        notice = Notice(published_at=now - timedelta(days=raw.get("published_days_ago", 1)),
                        deadline_at=now + timedelta(days=raw["deadline_in_days"]), **fields)
        summary = LLMSummary.model_validate(raw.get("summary") or {})
        m = match_notice(notice, sub, settings)
        rs = rules_score(notice, m, buyer_seen=bool(raw.get("buyer_seen")), now=now)
        score = final_score(rs.total, summary.verdict)
        item = DigestItem(notice, summary, m, rs, score, days_until(notice.deadline_at, now), True)
        (digest.priority if score >= settings.priority_threshold else digest.others).append(item)
    digest.priority.sort(key=lambda it: -it.score)
    digest.others.sort(key=lambda it: -it.score)
    return digest


def sample_email_html(settings: VMSettings, now: datetime | None = None) -> str:
    """L'email tel qu'un abonné le recevrait (page `/exemple`)."""
    _, html, _ = render_digest(sample_digest(settings, now), settings)
    return html
