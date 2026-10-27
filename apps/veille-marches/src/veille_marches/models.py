"""Modèles normalisés : avis (`Notice`), attribution (`Award`), abonné, résumé."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Source = Literal["boamp", "ted", "decp"]
Plan = Literal["essentiel", "pro"]
Verdict = Literal["oui", "peut-etre", "non"]

_CPV = re.compile(r"^\d{8}(?:-\d)?$")


def normalize_cpv(code: Any) -> str | None:
    """`77310000-6` → `77310000`. Retourne None si ce n'est pas un code CPV."""
    if code is None:
        return None
    text = str(code).strip()
    if not _CPV.match(text):
        return None
    return text[:8]


class Notice(BaseModel):
    source: Source
    source_id: str
    title: str
    buyer_name: str | None = None
    buyer_dept: str | None = None
    departments: list[str] = Field(default_factory=list)
    cpv_codes: list[str] = Field(default_factory=list)
    description: str | None = None
    estimated_amount: float | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    procedure_type: str | None = None
    url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    id: int | None = None  # identifiant en base, rempli après insertion

    @field_validator("cpv_codes", mode="before")
    @classmethod
    def _clean_cpv(cls, value):
        out: list[str] = []
        for v in value or []:
            code = normalize_cpv(v)
            if code and code not in out:
                out.append(code)
        return out

    @field_validator("departments", mode="before")
    @classmethod
    def _clean_depts(cls, value):
        out: list[str] = []
        for v in value or []:
            d = normalize_department(v)
            if d and d not in out:
                out.append(d)
        return out

    @property
    def all_departments(self) -> list[str]:
        if self.departments:
            return self.departments
        return [self.buyer_dept] if self.buyer_dept else []

    def raw_json(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False, default=str)


class Award(BaseModel):
    source: str = "decp"
    source_id: str
    title: str | None = None
    buyer_name: str | None = None
    buyer_id: str | None = None
    holder_name: str | None = None
    holder_id: str | None = None
    amount: float | None = None
    cpv_code: str | None = None
    dept: str | None = None
    place_code: str | None = None
    place_type: str | None = None
    procedure_type: str | None = None
    notified_at: datetime | None = None
    data_published_at: datetime | None = None
    duration_months: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    id: int | None = None

    @field_validator("cpv_code", mode="before")
    @classmethod
    def _clean_cpv(cls, value):
        return normalize_cpv(value)

    @property
    def holder_label(self) -> str:
        return self.holder_name or (f"SIRET {self.holder_id}" if self.holder_id else "titulaire non précisé")

    def raw_json(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False, default=str)


class Subscriber(BaseModel):
    id: int | None = None
    email: str
    label: str | None = None
    cpv_prefixes: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    amount_min: float | None = None
    amount_max: float | None = None
    plan: Plan = "essentiel"
    active: bool = True
    created_at: datetime | None = None

    @field_validator("cpv_prefixes", mode="before")
    @classmethod
    def _clean_prefixes(cls, value):
        out: list[str] = []
        for v in value or []:
            text = str(v).strip().split("-")[0]
            if text.isdigit() and 2 <= len(text) <= 8 and text not in out:
                out.append(text)
        return out

    @field_validator("departments", mode="before")
    @classmethod
    def _clean_depts(cls, value):
        out: list[str] = []
        for v in value or []:
            d = normalize_department(v)
            if d and d not in out:
                out.append(d)
        return out

    @property
    def display_name(self) -> str:
        return self.label or self.email


class LLMSummary(BaseModel):
    """Sortie structurée du LLM, validée et bornée (le texte vient d'une source externe)."""

    resume: str = "Résumé indisponible."
    lieu: str = "non précisé"
    montant_estime: str = "non précisé"
    date_limite: str = "non précisée"
    pieces_a_fournir: list[str] = Field(default_factory=list)
    criteres: str = "non précisés"
    verdict: Verdict = "peut-etre"
    raison: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _norm_verdict(cls, value):
        text = str(value or "").strip().lower()
        text = text.replace("ê", "e").replace("é", "e").replace("_", "-").replace(" ", "-")
        if text in {"oui", "yes", "o"}:
            return "oui"
        if text in {"non", "no", "n"}:
            return "non"
        return "peut-etre"

    @field_validator("resume", "lieu", "montant_estime", "date_limite", "criteres", "raison", mode="before")
    @classmethod
    def _norm_text(cls, value):
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        return " ".join(str(value).split())[:600]

    @field_validator("pieces_a_fournir", mode="before")
    @classmethod
    def _norm_pieces(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [p for p in re.split(r"[;\n•]+", value) if p.strip()]
        if isinstance(value, dict):
            value = list(value.values())
        return [" ".join(str(p).split())[:160] for p in list(value)[:10] if str(p).strip()]


def normalize_department(value: Any) -> str | None:
    """Normalise un code département : `1` → `01`, `2a` → `2A`, `971` reste `971`, `69M` → `69`."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in {"2A", "2B"}:
        return text
    if text.isdigit():
        if len(text) == 1:
            return "0" + text
        if len(text) == 2:
            return text
        if len(text) == 3 and text.startswith("97"):
            return text
        if len(text) == 5:  # code commune ou code postal
            return department_from_postal_or_insee(text)
        return None
    if len(text) == 3 and text[:2].isdigit() and text[2].isalpha():  # 69M (métropole de Lyon)
        return text[:2]
    if len(text) == 5 and text[:2] in {"2A", "2B"}:
        return text[:2]
    return None


def department_from_postal_or_insee(code: str) -> str | None:
    """Déduit le département d'un code postal ou d'un code commune INSEE (5 caractères)."""
    code = str(code).strip().upper()
    if len(code) != 5:
        return None
    if code.startswith("2A") or code.startswith("2B"):
        return code[:2]
    if code.startswith("97") or code.startswith("98"):
        return code[:3]
    if code.startswith("20"):  # code postal corse : 200xx/201xx → 2A, 202xx/206xx → 2B
        return "2A" if code[2] in "01" else "2B"
    return code[:2] if code[:2].isdigit() else None
