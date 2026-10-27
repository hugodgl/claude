"""Filtrage d'un avis pour un abonné : préfixes CPV, départements, fourchette de montant."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Notice, Subscriber
from .settings import VMSettings


@dataclass
class MatchResult:
    matched: bool
    cpv_match: str            # "exact" | "prefix" | "none" | "unfiltered"
    dept_match: bool | None   # None = département inconnu
    amount_status: str        # "in_range" | "unknown" | "out_of_range" | "unfiltered"
    flags: list[str] = field(default_factory=list)   # mentions à afficher (« montant non précisé »…)


def cpv_match_level(notice_codes: list[str], prefixes: list[str]) -> str:
    if not prefixes:
        return "unfiltered"
    level = "none"
    for code in notice_codes:
        for p in prefixes:
            if code == p:
                return "exact"
            if code.startswith(p):
                level = "prefix"
    return level


def match_notice(notice: Notice, sub: Subscriber, settings: VMSettings | None = None) -> MatchResult:
    allow_unknown_dept = bool(settings and settings.match_unknown_department)
    flags: list[str] = []

    cpv = cpv_match_level(notice.cpv_codes, sub.cpv_prefixes)
    if cpv == "none":
        return MatchResult(False, cpv, None, "unfiltered")

    depts = notice.all_departments
    if not sub.departments:
        dept_match: bool | None = True
        if not depts:
            flags.append("zone non précisée")
    elif not depts:
        dept_match = None
        flags.append("zone non précisée")
        if not allow_unknown_dept:
            return MatchResult(False, cpv, None, "unfiltered", flags)
    else:
        dept_match = any(d in sub.departments for d in depts)
        if not dept_match:
            return MatchResult(False, cpv, False, "unfiltered")

    if sub.amount_min is None and sub.amount_max is None:
        amount_status = "unfiltered"
        if notice.estimated_amount is None:
            flags.append("montant non précisé")
    elif notice.estimated_amount is None:
        amount_status = "unknown"
        flags.append("montant non précisé")
    else:
        a = notice.estimated_amount
        if (sub.amount_min is not None and a < sub.amount_min) or (sub.amount_max is not None and a > sub.amount_max):
            return MatchResult(False, cpv, dept_match, "out_of_range")
        amount_status = "in_range"
    return MatchResult(True, cpv, dept_match, amount_status, flags)


def matching_subscribers(notice: Notice, subscribers: list[Subscriber],
                         settings: VMSettings | None = None) -> list[tuple[Subscriber, MatchResult]]:
    out = []
    for s in subscribers:
        m = match_notice(notice, s, settings)
        if m.matched:
            out.append((s, m))
    return out
