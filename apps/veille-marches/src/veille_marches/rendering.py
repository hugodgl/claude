"""Environnement Jinja2 partagé (digest et brief) avec filtres de formatage français."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .dates import fr_amount, fr_date, fr_long_date

TEMPLATES_DIR = Path(__file__).parent / "templates"
_ENV: Environment | None = None


def _autoescape(name: str | None) -> bool:
    return bool(name) and name.endswith(".html.j2")


def get_env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=_autoescape,
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["fr_date"] = fr_date
    env.filters["fr_long_date"] = fr_long_date
    env.filters["fr_amount"] = fr_amount
    env.filters["fr_price"] = fr_price
    env.filters["score_color"] = score_color
    return env


def fr_price(amount: float | int | None) -> str:
    """`29` → `29 €`, `1250.5` → `1 250,50 €` (prix affichés HT sur le site)."""
    if amount is None:
        return "—"
    if float(amount).is_integer():
        return f"{int(amount):,}".replace(",", "\u202f") + " €"
    whole, cents = f"{float(amount):,.2f}".split(".")
    return f"{whole.replace(',', chr(0x202F))},{cents} €"


def score_color(score: int) -> str:
    if score >= 70:
        return "#1b7f4b"
    if score >= 50:
        return "#b26a00"
    return "#6b7280"


def render(template_name: str, **context) -> str:
    global _ENV
    if _ENV is None:
        _ENV = get_env()
    return _ENV.get_template(template_name).render(**context)
