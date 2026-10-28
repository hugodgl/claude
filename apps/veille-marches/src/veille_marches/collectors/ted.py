"""Collecteur TED (Tenders Electronic Daily, API v3) : `POST /v3/notices/search` avec une requête « expert ».

Documentation : https://docs.ted.europa.eu/api/latest/index.html
Exemple de requête : `classification-cpv=77310000* AND place-of-performance=FRA AND publication-date>=20261020`.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from ..dates import parse_dt
from ..mapping import TED_MAPPING, all_values, first_value, parse_amount, pick_text
from ..models import Notice, safe_http_url
from ..nuts import dept_from_nuts
from ..settings import VMSettings
from .base import CollectorError, CollectResult, build_client, cpv_matches_any

log = logging.getLogger(__name__)

PROCEDURE_LABELS = {
    "open": "Procédure ouverte",
    "restricted": "Procédure restreinte",
    "neg-w-call": "Procédure négociée avec mise en concurrence",
    "neg-wo-call": "Procédure négociée sans publication préalable",
    "comp-dial": "Dialogue compétitif",
    "innovation": "Partenariat d'innovation",
    "comp-tend": "Procédure concurrentielle avec négociation",
    "oth-single": "Autre procédure à une étape",
    "oth-mult": "Autre procédure en plusieurs étapes",
}


def build_query(cpv_prefixes: list[str], country: str, since: date, mapping: dict[str, Any] = TED_MAPPING) -> str:
    prefixes = cpv_prefixes or ["77310000"]
    cpv_clause = " OR ".join(mapping["cpv_clause_template"].format(prefix=p) for p in prefixes)
    return mapping["query_template"].format(cpv_clause=cpv_clause, country=country,
                                            date=since.strftime("%Y%m%d"))


def is_opportunity(notice: dict[str, Any], mapping: dict[str, Any] = TED_MAPPING) -> bool:
    form_type = first_value(notice, mapping["form_type"])
    if form_type:
        return str(form_type).lower() in mapping["keep_form_types"]
    notice_type = first_value(notice, mapping["notice_type"])
    if notice_type:
        nt = str(notice_type).lower()
        return not any(nt.startswith(p) for p in mapping["exclude_notice_type_prefixes"])
    return True


def map_ted_notice(notice: dict[str, Any], mapping: dict[str, Any] = TED_MAPPING) -> Notice | None:
    langs = mapping["preferred_langs"]
    source_id = pick_text(first_value(notice, mapping["source_id"]), langs)
    if not source_id:
        return None
    if not is_opportunity(notice, mapping):
        return None
    nuts_codes = [str(v).upper() for v in all_values(notice, mapping["nuts"])]
    departments = [d for d in (dept_from_nuts(c) for c in nuts_codes) if d]
    amount = None
    for p in mapping["estimated_amount"]:
        amount = parse_amount(first_value(notice, [p]))
        if amount is not None:
            break
    currency = first_value(notice, mapping["amount_currency"])
    if currency and str(pick_text(currency, langs)).upper() not in {"EUR", "NONE"}:
        amount = None
    deadlines = [d for d in (parse_dt(v) for v in all_values(notice, mapping["deadline_at"])) if d]
    procedure = first_value(notice, mapping["procedure_type"])
    procedure_label = PROCEDURE_LABELS.get(str(procedure).lower(), str(procedure)) if procedure else None
    url = None
    for p in mapping["url_paths"]:
        url = safe_http_url(pick_text(first_value(notice, [p]), langs))
        if url:
            break
    url = url or mapping["url_template"].format(source_id=source_id)
    n = Notice(
        source="ted",
        source_id=source_id,
        title=(pick_text(first_value(notice, mapping["title"]), langs) or "(titre non renseigné)")[:500],
        buyer_name=pick_text(first_value(notice, mapping["buyer_name"]), langs),
        departments=departments,
        cpv_codes=[str(c) for c in all_values(notice, mapping["cpv_codes"])],
        description=pick_text(first_value(notice, mapping["description"]), langs),
        estimated_amount=amount,
        published_at=parse_dt(first_value(notice, mapping["published_at"])),
        deadline_at=min(deadlines) if deadlines else None,
        procedure_type=procedure_label,
        url=url,
        raw=notice,
    )
    n.buyer_dept = n.departments[0] if n.departments else None
    return n


class TedCollector:
    source = "ted"

    def __init__(self, settings: VMSettings, client: httpx.Client | None = None,
                 mapping: dict[str, Any] | None = None):
        self.settings = settings
        self.client = client or build_client(settings)
        self.mapping = mapping or TED_MAPPING

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.ted_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ted_api_key}"
        return headers

    def fetch(self, since: date, cpv_prefixes: list[str], limit: int) -> CollectResult:
        result = CollectResult(source=self.source)
        url = f"{self.settings.ted_base_url.rstrip('/')}/notices/search"
        query = build_query(cpv_prefixes, self.settings.ted_country, since, self.mapping)
        page_size = max(1, min(self.settings.ted_page_size, limit, 250))
        page = 1
        while result.fetched < limit:
            payload = {
                "query": query,
                "fields": self.mapping["search_fields"],
                "page": page,
                "limit": page_size,
                "scope": self.mapping["scope"],
                "paginationMode": "PAGE_NUMBER",
            }
            try:
                resp = self.client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                raise CollectorError(f"TED : HTTP {e.response.status_code} — {e.response.text[:300]}") from e
            except httpx.HTTPError as e:
                raise CollectorError(f"TED : erreur réseau — {e}") from e
            except ValueError as e:
                raise CollectorError("TED : réponse non JSON") from e
            result.requests += 1
            notices = data.get("notices") or []
            if not notices:
                break
            for raw in notices:
                result.fetched += 1
                try:
                    notice = map_ted_notice(raw, self.mapping)
                except Exception as e:  # noqa: BLE001 - un avis inattendu est écarté, la source continue
                    log.warning("TED : avis inexploitable écarté (%s : %s)", e.__class__.__name__, e)
                    notice = None
                if notice is None or (notice.cpv_codes and not cpv_matches_any(notice.cpv_codes, cpv_prefixes)):
                    result.excluded += 1
                    continue
                result.notices.append(notice)
                result.kept += 1
                if result.fetched >= limit:
                    break
            total = data.get("totalNoticeCount")
            if len(notices) < page_size or (isinstance(total, int) and page * page_size >= total):
                break
            page += 1
        return result
