"""Environnement Jinja2 partagé par les pages web et les emails."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def stars(rating: int | None) -> str:
    r = int(rating or 0)
    return "★" * r + "☆" * (5 - r)


def fmt_date(value: str | None) -> str:
    if not value:
        return ""
    return "/".join(reversed(value[:10].split("-")))


def fmt_datetime(value: str | None) -> str:
    if not value:
        return ""
    return f"{fmt_date(value)} {value[11:16]}".strip()


def build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["stars"] = stars
    env.filters["date"] = fmt_date
    env.filters["datetime"] = fmt_datetime
    return env


_env: Environment | None = None


def get_env() -> Environment:
    global _env
    if _env is None:
        _env = build_env()
    return _env


def render(name: str, **context: Any) -> str:
    return get_env().get_template(name).render(**context)
