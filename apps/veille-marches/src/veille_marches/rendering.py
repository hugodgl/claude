"""Environnement Jinja2 partagé (digest et brief) avec filtres de formatage français."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .dates import fr_amount, fr_date

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _autoescape(name: str | None) -> bool:
    return bool(name) and name.endswith(".html.j2")


def get_env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=_autoescape,
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["fr_date"] = fr_date
    env.filters["fr_amount"] = fr_amount
    env.filters["score_color"] = score_color
    return env


def score_color(score: int) -> str:
    if score >= 70:
        return "#1b7f4b"
    if score >= 50:
        return "#b26a00"
    return "#6b7280"


def render(template_name: str, **context) -> str:
    return get_env().get_template(template_name).render(**context)
