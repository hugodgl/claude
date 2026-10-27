"""Sélection diversifiée des items d'un numéro : les mieux notés, au plus N par thème et par source."""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, timedelta


def min_published_iso(max_age_days: int, today: date | None = None) -> str | None:
    """Borne basse de date de publication (ISO) ; None si le filtre est désactivé (0)."""
    if not max_age_days or max_age_days <= 0:
        return None
    today = today or datetime.now(UTC).date()
    return (today - timedelta(days=max_age_days)).isoformat()


def select_diverse(rows: list[sqlite3.Row], *, limit: int = 8, max_per_theme: int = 2,
                   max_per_source: int = 3) -> list[sqlite3.Row]:
    """`rows` doit être trié par score décroissant. Deux passes : d'abord avec les plafonds,
    puis, s'il manque des items, on complète avec les meilleurs restants (plafond source conservé)."""
    chosen: list[sqlite3.Row] = []
    chosen_ids: set[int] = set()
    themes: Counter[str] = Counter()
    sources: Counter[int] = Counter()
    for row in rows:
        if len(chosen) >= limit:
            break
        theme = row["theme"] or "ia_generale"
        if themes[theme] >= max_per_theme or sources[row["source_id"]] >= max_per_source:
            continue
        chosen.append(row)
        chosen_ids.add(row["id"])
        themes[theme] += 1
        sources[row["source_id"]] += 1
    if len(chosen) < limit:
        for row in rows:
            if len(chosen) >= limit:
                break
            if row["id"] in chosen_ids or sources[row["source_id"]] >= max_per_source:
                continue
            chosen.append(row)
            chosen_ids.add(row["id"])
            sources[row["source_id"]] += 1
    return chosen
