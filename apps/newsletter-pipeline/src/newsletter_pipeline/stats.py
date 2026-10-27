"""Statistiques : items par source, taux de sélection, numéros produits."""
from __future__ import annotations

import sqlite3
from typing import Any


def collect_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = conn.execute(
        """SELECT s.name, s.category, s.kind, s.active, s.last_fetched_at, s.last_error,
                  COUNT(i.id) AS items,
                  SUM(CASE WHEN i.status = 'used' THEN 1 ELSE 0 END) AS used,
                  SUM(CASE WHEN i.score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
                  ROUND(AVG(i.score), 2) AS avg_score
           FROM sources s LEFT JOIN items i ON i.source_id = s.id
           GROUP BY s.id ORDER BY items DESC, s.name"""
    ).fetchall()
    totals = conn.execute(
        """SELECT COUNT(*) AS items,
                  SUM(CASE WHEN status = 'used' THEN 1 ELSE 0 END) AS used,
                  SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS new,
                  SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                  SUM(CASE WHEN score IS NOT NULL THEN 1 ELSE 0 END) AS scored
           FROM items"""
    ).fetchone()
    themes = conn.execute(
        "SELECT theme, COUNT(*) AS n FROM items WHERE theme IS NOT NULL GROUP BY theme ORDER BY n DESC"
    ).fetchall()
    issues = conn.execute(
        "SELECT number, issue_date, title, status, case_slug, item_ids FROM issues ORDER BY number"
    ).fetchall()
    items = int(totals["items"] or 0)
    used = int(totals["used"] or 0)
    return {
        "sources": [dict(r) for r in sources],
        "totals": {"items": items, "used": used, "new": int(totals["new"] or 0),
                   "rejected": int(totals["rejected"] or 0), "scored": int(totals["scored"] or 0),
                   "selection_rate": round(used / items, 3) if items else 0.0},
        "themes": [dict(r) for r in themes],
        "issues": [dict(r) for r in issues],
    }


def format_stats(stats: dict[str, Any]) -> str:
    t = stats["totals"]
    lines = [
        "Items : "
        f"{t['items']} collectés, {t['scored']} classés, {t['used']} utilisés dans un numéro "
        f"(taux de sélection {t['selection_rate'] * 100:.1f} %), {t['new']} en attente, {t['rejected']} rejetés.",
        "",
        f"{'Source':<38} {'Cat.':<14} {'Items':>5} {'Util.':>5} {'Score':>5}  Dernière collecte / erreur",
    ]
    for s in stats["sources"]:
        state = "" if s["active"] else "(inactive) "
        when = (s["last_fetched_at"] or "jamais")[:16]
        err = f" ERREUR : {s['last_error'][:60]}" if s["last_error"] else ""
        lines.append(
            f"{s['name'][:38]:<38} {s['category'][:14]:<14} {s['items'] or 0:>5} {s['used'] or 0:>5} "
            f"{(s['avg_score'] if s['avg_score'] is not None else '-')!s:>5}  {state}{when}{err}"
        )
    if stats["themes"]:
        lines += ["", "Thèmes : " + ", ".join(f"{r['theme']} {r['n']}" for r in stats["themes"])]
    lines += ["", f"Numéros produits : {len(stats['issues'])}"]
    for i in stats["issues"]:
        lines.append(f"  n° {i['number']:03d}  {i['issue_date']}  [{i['status']}]  {i['title']}  "
                     f"(cas : {i['case_slug']})")
    return "\n".join(lines)
