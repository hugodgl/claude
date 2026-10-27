"""Rendu du numéro : markdown (source de vérité, relu par Hugo) → HTML email propre + version texte."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "htm", "xml"]),
    trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
)

_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"]


def date_fr(d: date) -> str:
    return f"{_DAYS[d.weekday()]} {d.day}{'er' if d.day == 1 else ''} {_MONTHS[d.month - 1]} {d.year}"


def issue_basename(number: int, issue_date: date) -> str:
    return f"{number:03d}-{issue_date.isoformat()}"


def render_markdown(context: dict[str, Any]) -> str:
    return _env.get_template("issue.md.j2").render(**context)


def markdown_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["extra", "sane_lists"], output_format="html")


def first_heading(md_text: str) -> str | None:
    m = re.search(r"^#\s+(.+?)\s*$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else None


def render_email_html(md_text: str, meta: dict[str, Any]) -> str:
    context = {**meta, "body_html": markdown_to_html(md_text)}
    context.setdefault("title", first_heading(md_text) or meta.get("newsletter_name", ""))
    return _env.get_template("email.html.j2").render(**context)


_RE_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_RE_EMPH = re.compile(r"(?<![\w*_])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*_])")


def markdown_to_text(md_text: str) -> str:
    """Version texte brut lisible : titres en capitales, liens « texte (url) », sans balisage."""
    text = _RE_FENCE.sub(lambda m: "\n" + m.group(1).rstrip() + "\n", md_text)
    text = _RE_IMG.sub("", text)
    text = _RE_LINK.sub(lambda m: m.group(1) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})", text)
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", stripped):
            lines.append("-" * 40)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            title = re.sub(r"\*\*|__", "", title)
            lines.append("")
            lines.append(title.upper() if level <= 2 else title)
            if level == 1:
                lines.append("=" * min(len(title), 60))
            elif level == 2:
                lines.append("-" * min(len(title), 60))
            continue
        stripped = re.sub(r"^\s*>\s?", "", stripped)
        stripped = stripped.replace("**", "").replace("__", "")
        stripped = _RE_EMPH.sub(r"\2", stripped)
        stripped = re.sub(r"`([^`]*)`", r"\1", stripped)
        lines.append(stripped)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def write_issue_files(issues_dir: Path, number: int, issue_date: date, md_text: str,
                      meta: dict[str, Any]) -> dict[str, Path]:
    issues_dir = Path(issues_dir)
    issues_dir.mkdir(parents=True, exist_ok=True)
    base = issues_dir / issue_basename(number, issue_date)
    paths = {"md": base.with_suffix(".md"), "html": base.with_suffix(".html"), "txt": base.with_suffix(".txt")}
    paths["md"].write_text(md_text, encoding="utf-8")
    paths["html"].write_text(render_email_html(md_text, meta), encoding="utf-8")
    paths["txt"].write_text(markdown_to_text(md_text), encoding="utf-8")
    return paths


def rerender_from_markdown(md_path: Path, meta: dict[str, Any]) -> dict[str, Path]:
    """Régénère HTML et texte depuis le markdown (après relecture et corrections à la main)."""
    md_text = md_path.read_text(encoding="utf-8")
    paths = {"md": md_path, "html": md_path.with_suffix(".html"), "txt": md_path.with_suffix(".txt")}
    paths["html"].write_text(render_email_html(md_text, meta), encoding="utf-8")
    paths["txt"].write_text(markdown_to_text(md_text), encoding="utf-8")
    return paths
