"""Collecteur BOAMP via le portail Opendatasoft de la DILA (jeu `boamp`, API Explore v2.1).

Documentation : https://boamp-datadila.opendatasoft.com/api/explore/v2.1/console
Paramètres utilisés : `where` (ODSQL), `order_by`, `limit`, `offset`, `refine`.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from ..dates import parse_dt
from ..mapping import (
    BOAMP_MAPPING,
    all_values,
    decode_json_strings,
    first_value,
    parse_amount,
    scan_cpv_codes,
)
from ..models import Notice, safe_http_url
from ..settings import VMSettings
from .base import CollectResult, build_client, cpv_matches_any, ods_iter_records, ods_sql_date

log = logging.getLogger(__name__)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if v not in (None, "")]
        return ", ".join(parts) or None
    if isinstance(value, dict):
        return None
    text = str(value).strip()
    return text or None


def is_excluded_nature(record: dict[str, Any], mapping: dict[str, Any] = BOAMP_MAPPING) -> bool:
    nature = " ".join(str(v) for v in all_values(record, mapping["nature"])).lower()
    return any(k in nature for k in mapping["exclude_nature_keywords"])


def map_boamp_record(record: dict[str, Any], mapping: dict[str, Any] = BOAMP_MAPPING) -> Notice | None:
    """Convertit un enregistrement Opendatasoft en `Notice`. None si ce n'est pas une opportunité."""
    rec = decode_json_strings(record, mapping["json_string_fields"])
    source_id = _text(first_value(rec, mapping["source_id"]))
    if not source_id:
        return None
    if is_excluded_nature(rec, mapping):
        return None
    cpv = all_values(rec, mapping["cpv_codes"])
    for f in mapping.get("cpv_scan_fields", []):
        if f in rec:
            cpv += scan_cpv_codes(rec[f])
    departments = all_values(rec, mapping["departments"])
    title = _text(first_value(rec, mapping["title"])) or "(objet non renseigné)"
    deadline = min((d for d in (parse_dt(v) for v in all_values(rec, mapping["deadline_at"])) if d), default=None)
    url = safe_http_url(_text(first_value(rec, mapping["url"]))) or mapping["url_template"].format(source_id=source_id)
    notice = Notice(
        source="boamp",
        source_id=source_id,
        title=title[:500],
        buyer_name=_text(first_value(rec, mapping["buyer_name"])),
        departments=departments,
        cpv_codes=cpv,
        description=_text(first_value(rec, mapping["description"])),
        estimated_amount=parse_amount(first_value(rec, mapping["estimated_amount"])),
        published_at=parse_dt(first_value(rec, mapping["published_at"])),
        deadline_at=deadline,
        procedure_type=_text(first_value(rec, mapping["procedure_type"])),
        url=url,
        raw=record,
    )
    notice.buyer_dept = notice.departments[0] if notice.departments else None
    return notice


def build_where(since: date, cpv_prefixes: list[str], mapping: dict[str, Any], server_side_cpv: bool) -> str:
    where = f"{mapping['date_field']} >= {ods_sql_date(since)}"
    if server_side_cpv and cpv_prefixes:
        clauses = [mapping["cpv_where_template"].format(cpv=p) for p in cpv_prefixes]
        where += " AND (" + " OR ".join(clauses) + ")"
    return where


class BoampCollector:
    source = "boamp"

    def __init__(self, settings: VMSettings, client: httpx.Client | None = None,
                 mapping: dict[str, Any] | None = None):
        self.settings = settings
        self.client = client or build_client(settings)
        self.mapping = mapping or BOAMP_MAPPING

    def fetch(self, since: date, cpv_prefixes: list[str], limit: int) -> CollectResult:
        result = CollectResult(source=self.source)
        where = build_where(since, cpv_prefixes, self.mapping, self.settings.boamp_server_side_cpv)
        for record in ods_iter_records(
            self.client, self.settings.boamp_base_url, self.settings.boamp_dataset, where=where,
            order_by=self.mapping["order_by"], limit=limit, page_size=self.mapping["page_size"],
            api_key=self.settings.boamp_api_key, result=result,
        ):
            result.fetched += 1
            try:
                notice = map_boamp_record(record, self.mapping)
            except Exception as e:  # noqa: BLE001 - un enregistrement inattendu est écarté, la source continue
                log.warning("BOAMP : enregistrement inexploitable écarté (%s : %s)", e.__class__.__name__, e)
                notice = None
            # on garde les avis sans CPV détecté : `vm stats` les compte, c'est le signal d'un mapping à corriger
            if notice is None or (notice.cpv_codes and not cpv_matches_any(notice.cpv_codes, cpv_prefixes)):
                result.excluded += 1
                continue
            result.notices.append(notice)
            result.kept += 1
        return result
