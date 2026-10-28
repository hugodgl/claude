"""Environnement Jinja2 partagé par les pages web et les emails."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import local_tz, parse_iso
from .platforms import PLATFORM_LABELS, platform_label
from .tripadvisor import management_url

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def stars(rating: int | None) -> str:
    r = int(rating or 0)
    return "★" * r + "☆" * (5 - r)


def _local(value: str | None):
    """Horodatage ISO (UTC en base) → datetime dans le fuseau métier, ou None s'il est illisible."""
    dt = parse_iso(value)
    return dt.astimezone(local_tz()) if dt else None


def fmt_date(value: str | None) -> str:
    if not value:
        return ""
    dt = _local(value)
    return dt.strftime("%d/%m/%Y") if dt else "/".join(reversed(value[:10].split("-")))


def fmt_datetime(value: str | None) -> str:
    if not value:
        return ""
    dt = _local(value)
    return dt.strftime("%d/%m/%Y %H:%M") if dt else f"{fmt_date(value)} {value[11:16]}".strip()


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
    env.filters["platform"] = platform_label
    env.filters["tripadvisor_url"] = management_url
    env.globals["platform_labels"] = PLATFORM_LABELS
    return env


_env: Environment | None = None


def get_env() -> Environment:
    global _env
    if _env is None:
        _env = build_env()
    return _env


def render(template_name: str, **context: Any) -> str:
    return get_env().get_template(template_name).render(**context)
