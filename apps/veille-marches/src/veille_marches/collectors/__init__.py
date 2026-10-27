"""Collecteurs de sources et orchestration d'une collecte."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import httpx

from .. import db
from ..dates import since_date, utcnow
from ..settings import VMSettings
from .base import CollectorError, CollectResult, build_client
from .boamp import BoampCollector
from .decp import DecpCollector
from .ted import TedCollector

SOURCES = ("boamp", "ted", "decp")
COLLECTORS = {"boamp": BoampCollector, "ted": TedCollector, "decp": DecpCollector}

__all__ = ["CollectResult", "CollectorError", "SOURCES", "active_cpv_prefixes", "run_collect"]


def active_cpv_prefixes(conn: sqlite3.Connection, settings: VMSettings) -> list[str]:
    """Union des préfixes CPV des abonnés actifs ; à défaut, les préfixes par défaut des réglages."""
    prefixes: list[str] = []
    for s in db.list_subscribers(conn, active_only=True):
        for p in s.cpv_prefixes:
            if p not in prefixes:
                prefixes.append(p)
    return prefixes or settings.default_cpv_prefix_list


def run_collect(conn: sqlite3.Connection, settings: VMSettings, *, sources: list[str] | None = None,
                since_days: int | None = None, limit: int | None = None, cpv_prefixes: list[str] | None = None,
                dry_run: bool = False, client: httpx.Client | None = None,
                now: datetime | None = None) -> list[CollectResult]:
    """Collecte chaque source, convertit, et enregistre (sauf `dry_run`). Une erreur sur une source n'arrête pas
    les autres : elle est consignée dans `CollectResult.error` et dans la table `collect_runs`."""
    now = now or utcnow()
    sources = [s for s in (sources or list(SOURCES))]
    since = since_date(since_days if since_days is not None else settings.collect_since_days, now)
    limit = limit or settings.collect_limit
    prefixes = cpv_prefixes if cpv_prefixes is not None else active_cpv_prefixes(conn, settings)
    client = client or build_client(settings)
    results: list[CollectResult] = []
    for source in sources:
        collector = COLLECTORS[source](settings, client=client)
        run_id = None if dry_run else db.start_run(conn, source, now)
        try:
            result = collector.fetch(since, prefixes, limit)
        except CollectorError as e:
            result = CollectResult(source=source, error=str(e))
        if not dry_run and not result.error:
            for n in result.notices:
                if db.upsert_notice(conn, n, now):
                    result.inserted += 1
            for a in result.awards:
                if db.upsert_award(conn, a, now):
                    result.inserted += 1
        if run_id is not None:
            db.finish_run(conn, run_id, fetched=result.fetched, inserted=result.inserted, error=result.error, now=now)
        results.append(result)
    return results
