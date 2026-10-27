"""Lecture et validation des formulaires du site (inscription, espace abonné), sans dépendance à FastAPI."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .catalog import DEPARTMENTS, PLANS, TRADES, Plan, plan_or_default, trade_or_default
from .models import normalize_department

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MAX_TEXT = 120


def _getlist(form: Mapping[str, Any], key: str) -> list[str]:
    getter = getattr(form, "getlist", None)
    values = getter(key) if callable(getter) else form.get(key)
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return [str(v) for v in values]


def _text(form: Mapping[str, Any], key: str) -> str:
    value = form.get(key)
    return " ".join(str(value).split())[:MAX_TEXT] if value is not None else ""


def parse_amount(raw: str | None) -> tuple[float | None, str | None]:
    """`500 000`, `500000`, `500k`, `1,2M` → euros ; (None, None) si vide ; (None, message) si illisible."""
    text = (raw or "").strip().lower().replace("€", "").replace("ht", "")
    text = text.replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None, None
    factor = 1.0
    if text.endswith("m"):
        factor, text = 1_000_000.0, text[:-1]
    elif text.endswith("k"):
        factor, text = 1_000.0, text[:-1]
    try:
        value = float(text) * factor
    except ValueError:
        return None, "montant illisible (ex. 500000 ou 500k)"
    if value < 0:
        return None, "le montant doit être positif"
    return round(value, 2), None


def parse_cpv_prefixes(raw: str) -> tuple[list[str], str | None]:
    """Préfixes CPV séparés par virgules, espaces ou points-virgules : 2 à 8 chiffres chacun."""
    out: list[str] = []
    for part in re.split(r"[\s,;]+", raw or ""):
        part = part.strip().split("-")[0]
        if not part:
            continue
        if not part.isdigit() or not 2 <= len(part) <= 8:
            return [], f"préfixe CPV invalide : « {part} » (2 à 8 chiffres)"
        if part not in out:
            out.append(part)
    return out, None


def parse_departments(values: list[str], plan: Plan) -> tuple[list[str], str | None]:
    out: list[str] = []
    for v in values:
        for part in str(v).split(","):
            d = normalize_department(part)
            if d and d in DEPARTMENTS and d not in out:
                out.append(d)
    if not out:
        return [], "choisissez au moins un département"
    if len(out) > plan.max_departments:
        return out, (f"la formule {plan.name} comprend {plan.max_departments} département"
                     f"{'s' if plan.max_departments > 1 else ''} au maximum ({len(out)} choisis)"
                     + (" : passez en Pro pour aller jusqu'à 6" if plan.code == "essentiel" else ""))
    return out, None


@dataclass
class SignupForm:
    email: str = ""
    company: str = ""
    trade: str = "espaces_verts"
    cpv_extra: str = ""
    departments: list[str] = field(default_factory=list)
    amount_min_raw: str = ""
    amount_max_raw: str = ""
    plan: str = "essentiel"
    billing_period: str = "monthly"
    accept_terms: bool = False
    honeypot: str = ""
    # valeurs calculées
    cpv_prefixes: list[str] = field(default_factory=list)
    amount_min: float | None = None
    amount_max: float | None = None
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def is_bot(self) -> bool:
        return bool(self.honeypot)


def parse_signup(form: Mapping[str, Any]) -> SignupForm:
    f = SignupForm(
        email=_text(form, "email").lower(), company=_text(form, "company"),
        trade=_text(form, "trade") or "espaces_verts", cpv_extra=_text(form, "cpv_extra"),
        departments=_getlist(form, "departments"), amount_min_raw=_text(form, "amount_min"),
        amount_max_raw=_text(form, "amount_max"), plan=_text(form, "plan").lower() or "essentiel",
        billing_period=_text(form, "billing_period").lower() or "monthly",
        accept_terms=bool(form.get("accept_terms")), honeypot=_text(form, "website"),
    )
    if not _EMAIL.match(f.email):
        f.errors["email"] = "indiquez une adresse email valide"
    if not f.company:
        f.errors["company"] = "indiquez le nom de votre entreprise"
    if f.plan not in PLANS:
        f.errors["plan"] = "formule inconnue"
        f.plan = "essentiel"
    if f.billing_period not in ("monthly", "yearly"):
        f.errors["billing_period"] = "périodicité inconnue"
        f.billing_period = "monthly"
    if f.trade not in TRADES:
        f.errors["trade"] = "métier inconnu"
        f.trade = "autre"
    _validate_criteria(f, plan_or_default(f.plan))
    if not f.accept_terms:
        f.errors["accept_terms"] = "merci d'accepter les conditions générales de vente"
    return f


def _validate_criteria(f, plan: Plan) -> None:
    """Partie commune inscription / espace abonné : CPV, départements, montants."""
    extra, err = parse_cpv_prefixes(f.cpv_extra)
    prefixes = list(trade_or_default(f.trade).cpv_prefixes)
    for p in extra:
        if p not in prefixes:
            prefixes.append(p)
    if err:
        f.errors["cpv_extra"] = err
    elif not prefixes:
        f.errors["cpv_extra"] = "indiquez au moins un préfixe CPV (ex. 773 pour les espaces verts)"
    f.cpv_prefixes = prefixes
    f.departments, err = parse_departments(f.departments, plan)
    if err:
        f.errors["departments"] = err
    f.amount_min, err = parse_amount(f.amount_min_raw)
    if err:
        f.errors["amount_min"] = err
    f.amount_max, err = parse_amount(f.amount_max_raw)
    if err:
        f.errors["amount_max"] = err
    if f.amount_min is not None and f.amount_max is not None and f.amount_min > f.amount_max:
        f.errors["amount_max"] = "le montant maximal doit être supérieur au minimal"


@dataclass
class AccountForm:
    trade: str = "autre"
    cpv_extra: str = ""
    departments: list[str] = field(default_factory=list)
    amount_min_raw: str = ""
    amount_max_raw: str = ""
    cpv_prefixes: list[str] = field(default_factory=list)
    amount_min: float | None = None
    amount_max: float | None = None
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors


def parse_account(form: Mapping[str, Any], plan: Plan) -> AccountForm:
    f = AccountForm(trade=_text(form, "trade") or "autre", cpv_extra=_text(form, "cpv_extra"),
                    departments=_getlist(form, "departments"), amount_min_raw=_text(form, "amount_min"),
                    amount_max_raw=_text(form, "amount_max"))
    if f.trade not in TRADES:
        f.trade = "autre"
    _validate_criteria(f, plan)
    return f
