"""Outils communs aux collecteurs : client HTTP, pagination Opendatasoft, résultat de collecte."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from ..models import Award, Notice
from ..settings import VMSettings

ODS_MAX_PAGE = 100          # limite imposée par l'API Explore v2.1
ODS_MAX_OFFSET = 10_000     # offset + limit doit rester sous 10 000


def build_client(settings: VMSettings, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    headers = {"User-Agent": settings.http_user_agent, "Accept": "application/json"}
    return httpx.Client(timeout=settings.http_timeout_s, headers=headers, transport=transport,
                        follow_redirects=True)


class CollectorError(RuntimeError):
    """Erreur réseau ou réponse inexploitable d'une source."""


@dataclass
class CollectResult:
    source: str
    fetched: int = 0                         # enregistrements reçus de l'API
    kept: int = 0                            # enregistrements convertis et retenus (après exclusions et filtre CPV)
    inserted: int = 0                        # nouveaux en base
    excluded: int = 0                        # attributions, annulations, hors CPV…
    error: str | None = None
    notices: list[Notice] = field(default_factory=list)
    awards: list[Award] = field(default_factory=list)
    requests: int = 0


def ods_sql_date(d: date) -> str:
    return f"date'{d.isoformat()}'"


def ods_iter_records(client: httpx.Client, base_url: str, dataset: str, *, where: str | None = None,
                     order_by: str | None = None, limit: int = 500, page_size: int = ODS_MAX_PAGE,
                     refine: list[str] | None = None, select: str | None = None,
                     api_key: str | None = None, result: CollectResult | None = None) -> Iterator[dict[str, Any]]:
    """Parcourt `/catalog/datasets/{dataset}/records` par pages (`limit`/`offset`) jusqu'à `limit` enregistrements."""
    url = f"{base_url.rstrip('/')}/catalog/datasets/{dataset}/records"
    page_size = max(1, min(page_size, ODS_MAX_PAGE, limit))
    offset = 0
    yielded = 0
    while yielded < limit and offset + page_size <= ODS_MAX_OFFSET:
        params: list[tuple[str, str]] = [("limit", str(page_size)), ("offset", str(offset))]
        if where:
            params.append(("where", where))
        if order_by:
            params.append(("order_by", order_by))
        if select:
            params.append(("select", select))
        for r in refine or []:
            params.append(("refine", r))
        headers = {"Authorization": f"Apikey {api_key}"} if api_key else None
        try:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise CollectorError(f"{dataset} : HTTP {e.response.status_code} — {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise CollectorError(f"{dataset} : erreur réseau — {e}") from e
        except ValueError as e:
            raise CollectorError(f"{dataset} : réponse non JSON") from e
        if result is not None:
            result.requests += 1
        rows = data.get("results") or data.get("records") or []
        if not rows:
            break
        for row in rows:
            # compatibilité v2.0 : {"record": {"fields": {...}}}
            if isinstance(row, dict) and "record" in row and isinstance(row["record"], dict):
                row = row["record"].get("fields", row["record"])
            yield row
            yielded += 1
            if yielded >= limit:
                return
        if len(rows) < page_size:
            break
        offset += page_size


def cpv_matches_any(codes: list[str], prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    return any(code.startswith(p) for code in codes for p in prefixes)
