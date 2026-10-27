"""Collecteur DECP (données essentielles de la commande publique : attributions) via data.economie.gouv.fr.

Jeux possibles (réglage `DECP_DATASET`) : `decp-v3`, `decp-v3-marches-valides`, `decp_augmente`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from ..dates import parse_dt
from ..mapping import DECP_MAPPING, decode_json_strings, first_value, parse_amount
from ..models import Award, department_from_postal_or_insee, normalize_department
from ..settings import VMSettings
from .base import CollectResult, build_client, ods_iter_records, ods_sql_date


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def department_from_place(code: str | None, type_code: str | None) -> str | None:
    """Déduit le département du lieu d'exécution DECP selon son type (code postal, commune, département…)."""
    if not code:
        return None
    code = str(code).strip().upper()
    t = (type_code or "").lower()
    if "département" in t or "departement" in t:
        return normalize_department(code)
    if "postal" in t or "commune" in t or "arrondissement" in t:
        return department_from_postal_or_insee(code) if len(code) == 5 else normalize_department(code)
    if "canton" in t and len(code) >= 4:
        return normalize_department(code[:2] if not code.startswith("97") else code[:3])
    if "région" in t or "region" in t or "pays" in t:
        return None
    # type inconnu : on tente les formats évidents
    if len(code) == 5:
        return department_from_postal_or_insee(code)
    return normalize_department(code)


def map_decp_record(record: dict[str, Any], mapping: dict[str, Any] = DECP_MAPPING) -> Award | None:
    rec = decode_json_strings(record, mapping["json_string_fields"])
    source_id = _text(first_value(rec, mapping["source_id"]))
    if not source_id:
        return None
    place_code = _text(first_value(rec, mapping["place_code"]))
    place_type = _text(first_value(rec, mapping["place_type"]))
    dept = normalize_department(first_value(rec, mapping["dept"])) or department_from_place(place_code, place_type)
    duration = first_value(rec, mapping["duration_months"])
    try:
        duration_months = int(float(duration)) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_months = None
    holder_id = _text(first_value(rec, mapping["holder_id"]))
    return Award(
        source="decp",
        source_id=source_id,
        title=(_text(first_value(rec, mapping["title"])) or "(objet non renseigné)")[:500],
        buyer_name=_text(first_value(rec, mapping["buyer_name"])),
        buyer_id=_text(first_value(rec, mapping["buyer_id"])),
        holder_name=_text(first_value(rec, mapping["holder_name"])),
        holder_id=holder_id,
        amount=parse_amount(first_value(rec, mapping["amount"])),
        cpv_code=first_value(rec, mapping["cpv_code"]),
        dept=dept,
        place_code=place_code,
        place_type=place_type,
        procedure_type=_text(first_value(rec, mapping["procedure_type"])),
        notified_at=parse_dt(first_value(rec, mapping["notified_at"])),
        data_published_at=parse_dt(first_value(rec, mapping["data_published_at"])),
        duration_months=duration_months,
        raw=record,
    )


def build_where(since: date, cpv_prefixes: list[str], mapping: dict[str, Any] = DECP_MAPPING) -> str:
    where = f"{mapping['date_field']} >= {ods_sql_date(since)}"
    if cpv_prefixes:
        clauses = [f'startswith({mapping["cpv_field"]}, "{p}")' for p in cpv_prefixes]
        where += " AND (" + " OR ".join(clauses) + ")"
    return where


class DecpCollector:
    source = "decp"

    def __init__(self, settings: VMSettings, client: httpx.Client | None = None,
                 mapping: dict[str, Any] | None = None):
        self.settings = settings
        self.client = client or build_client(settings)
        self.mapping = mapping or DECP_MAPPING

    def fetch(self, since: date, cpv_prefixes: list[str], limit: int) -> CollectResult:
        result = CollectResult(source=self.source)
        where = build_where(since, cpv_prefixes, self.mapping)
        for record in ods_iter_records(
            self.client, self.settings.decp_base_url, self.settings.decp_dataset, where=where,
            order_by=self.mapping["order_by"], limit=limit, page_size=self.mapping["page_size"], result=result,
        ):
            result.fetched += 1
            award = map_decp_record(record, self.mapping)
            if award is None:
                result.excluded += 1
                continue
            if cpv_prefixes and award.cpv_code and not any(award.cpv_code.startswith(p) for p in cpv_prefixes):
                result.excluded += 1
                continue
            result.awards.append(award)
            result.kept += 1
        return result
