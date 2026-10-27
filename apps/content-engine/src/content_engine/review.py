"""File de validation humaine : liste, approbation, rejet, export markdown du matin."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from rich.table import Table

from .scripts import draft_payload, get_draft, list_drafts, set_draft_status


def pending_drafts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list_drafts(conn, status="draft")


def approve(conn: sqlite3.Connection, draft_id: int) -> sqlite3.Row:
    row = get_draft(conn, draft_id)
    if row["status"] not in ("draft", "rejected"):
        raise ValueError(f"brouillon #{draft_id} déjà en statut {row['status']}")
    set_draft_status(conn, draft_id, "approved")
    return get_draft(conn, draft_id)


def reject(conn: sqlite3.Connection, draft_id: int, reason: str) -> sqlite3.Row:
    row = get_draft(conn, draft_id)
    if row["status"] == "published":
        raise ValueError(f"brouillon #{draft_id} déjà publié")
    set_draft_status(conn, draft_id, "rejected", reason=reason or "sans motif")
    return get_draft(conn, draft_id)


def _short(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def review_table(rows: list[sqlite3.Row], title: str = "Brouillons en attente") -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Produit")
    table.add_column("Format")
    table.add_column("V", justify="right")
    table.add_column("Titre / accroche")
    table.add_column("Durée", justify="right")
    table.add_column("Alertes")
    for row in rows:
        p = draft_payload(row)
        checks = p.get("checks", {})
        table.add_row(
            str(row["id"]), row["product"], row["format"], str(row["variant"]),
            _short(p["title"], 48) + "\n[dim]" + _short(p["hook"], 48) + "[/dim]",
            f"{checks.get('estimated_duration_s', p.get('duration_s', 0)):.0f} s",
            "\n".join(checks.get("warnings", [])) or "[green]ok[/green]",
        )
    return table


def draft_markdown(row: sqlite3.Row) -> str:
    p = draft_payload(row)
    checks = p.get("checks", {})
    lines = [
        f"## #{row['id']} — {row['product']} / {row['format']} / variante {row['variant']}",
        "",
        f"**Sujet :** {row['question']}  ",
        f"**Angle :** {row['angle'] or 'libre'} · **Approche :** {p.get('approach', '')}  ",
        f"**Titre :** {p['title']}  ",
        f"**Durée estimée :** {checks.get('estimated_duration_s', p.get('duration_s', 0))} s "
        f"({checks.get('word_count', '?')} mots)",
        "",
        f"> **Accroche :** {p['hook']}",
        "",
    ]
    lines += [f"- {part}" for part in p["body"]]
    lines += ["", f"> **CTA :** {p['cta']}", "", f"**Description :** {p['description']}  ",
              f"**Hashtags :** {' '.join('#' + h for h in p.get('hashtags', []))}", ""]
    warnings = checks.get("warnings", [])
    if warnings:
        lines += ["**Alertes :**"] + [f"- ⚠ {w}" for w in warnings] + [""]
    lines += [f"`ce approve {row['id']}` · `ce reject {row['id']} --reason \"…\"`", "", "---", ""]
    return "\n".join(lines)


def export_review(conn: sqlite3.Connection, out_dir: str | Path, day: date | None = None) -> Path:
    """Écrit out/review-AAAA-MM-JJ.md avec tous les brouillons en attente."""
    day = day or date.today()
    rows = pending_drafts(conn)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"review-{day.isoformat()}.md"
    ids = " ".join(str(r["id"]) for r in rows)
    header = [
        f"# Relecture du {day.strftime('%d/%m/%Y')} — {len(rows)} brouillon(s) en attente",
        "",
        "Lire, choisir, corriger si besoin (15 minutes). Puis :",
        "",
        f"- tout approuver : `ce approve {ids}`" if ids else "- rien à approuver",
        "- rejeter : `ce reject ID --reason \"motif\"` (le motif nourrit les prochains scripts)",
        "- ensuite : `ce render --approved` puis `ce run-publish` (dry-run par défaut)",
        "",
        "---",
        "",
    ]
    body = [draft_markdown(r) for r in rows] or ["_Aucun brouillon en attente._", ""]
    path.write_text("\n".join(header + body), encoding="utf-8")
    return path
