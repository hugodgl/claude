"""Calendrier éditorial (cadences du plan 4), routine du matin, publication des créneaux échus."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.llm import LLM

from .db import utc_now_iso
from .products import PRODUCTS, product_rotation
from .publish import PLATFORM_FORMATS, PublishError, publish_draft
from .render import RenderError, render_draft
from .review import export_review
from .scripts import FORMATS, generate_scripts, list_drafts
from .settings import Settings
from .topics import count_topics, generate_ideas, pick_topics
from .tts.base import TTSError

# clé → (plateforme, format, heures locales, jours de semaine autorisés ou None = tous)
CADENCE: dict[str, tuple[str, str, list[str], set[int] | None]] = {
    "short": ("youtube", "short", ["12:00"], None),  # 1 short / jour
    "tiktok": ("tiktok", "short", ["18:00"], None),  # 1 TikTok / jour
    "pins": ("pinterest", "pin", ["09:00", "11:00", "13:00", "15:00", "17:00"], None),  # 5 / jour
    "linkedin": ("linkedin", "linkedin", ["08:30"], {0, 2, 4}),  # lun, mer, ven
    "long": ("youtube", "long", ["17:00"], {3}),  # jeudi
}
VIDEO_PLATFORMS = ("youtube", "tiktok", "pinterest")


@dataclass
class Slot:
    day: str
    slot_at: str
    platform: str
    format: str
    product: str


def local_now(settings: Settings) -> datetime:
    return datetime.now(ZoneInfo(settings.timezone)).replace(second=0, microsecond=0)


def as_local(now: datetime | None, settings: Settings) -> datetime:
    """`now` exprimé dans le fuseau des créneaux (TIMEZONE) ; un datetime naïf est supposé local."""
    tz = ZoneInfo(settings.timezone)
    if now is None:
        return local_now(settings)
    return now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)


def slot_age(now: datetime, slot_at: str) -> timedelta:
    """Temps réellement écoulé depuis le créneau (calcul en UTC : insensible au changement
    d'heure, contrairement à une soustraction d'heures locales)."""
    slot = datetime.strptime(slot_at, "%Y-%m-%dT%H:%M").replace(tzinfo=now.tzinfo)
    return now.astimezone(UTC) - slot.astimezone(UTC)


def build_plan(start: date, days: int) -> list[Slot]:
    slots: list[Slot] = []
    counters = dict.fromkeys(CADENCE, 0)
    for i in range(days):
        d = start + timedelta(days=i)
        for key, (platform, fmt, times, weekdays) in CADENCE.items():
            if weekdays is not None and d.weekday() not in weekdays:
                continue
            rotation = product_rotation(platform)
            for t in times:
                product = rotation[counters[key] % len(rotation)]
                counters[key] += 1
                slots.append(Slot(d.isoformat(), f"{d.isoformat()}T{t}", platform, fmt, product))
    return slots


def save_plan(conn: sqlite3.Connection, slots: list[Slot]) -> int:
    added = 0
    with conn:
        for s in slots:
            cur = conn.execute(
                "INSERT OR IGNORE INTO schedule (day, slot_at, platform, format, product, status, "
                "created_at) VALUES (?, ?, ?, ?, ?, 'planned', ?)",
                (s.day, s.slot_at, s.platform, s.format, s.product, utc_now_iso()),
            )
            added += cur.rowcount
    return added


def list_schedule(
    conn: sqlite3.Connection,
    from_day: str | None = None,
    to_day: str | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    sql, params = "SELECT * FROM schedule WHERE 1=1", []
    if from_day:
        sql += " AND day >= ?"
        params.append(from_day)
    if to_day:
        sql += " AND day <= ?"
        params.append(to_day)
    if status:
        sql += " AND status = ?"
        params.append(status)
    return conn.execute(sql + " ORDER BY slot_at, platform", params).fetchall()


def due_slots(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM schedule WHERE status = 'planned' AND slot_at <= ? ORDER BY slot_at",
        (now.strftime("%Y-%m-%dT%H:%M"),),
    ).fetchall()


def candidate_draft(
    conn: sqlite3.Connection, slot: sqlite3.Row | Slot, live: bool = False
) -> sqlite3.Row | None:
    """Brouillon prêt pour un créneau : bon format, rendu (ou approuvé pour LinkedIn), produit du
    créneau de préférence, et jamais envoyé sur cette plateforme. En dry-run, une simulation
    précédente compte comme un envoi (calendrier réaliste) ; en `--live`, seules les publications
    réelles comptent : un brouillon simulé la veille est bien publié pour de bon."""
    platform, fmt = slot["platform"], slot["format"]
    product = slot["product"]
    statuses = (
        "('rendered', 'published')"
        if platform in VIDEO_PLATFORMS
        else "('approved', 'rendered', 'published')"
    )
    sent = "AND p.dry_run = 0" if live else ""
    base = (
        "SELECT d.*, t.product FROM drafts d JOIN topics t ON t.id = d.topic_id "
        f"WHERE d.format = ? AND d.status IN {statuses} "
        "AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.draft_id = d.id "
        f"AND p.platform = ? {sent})"
    )
    row = conn.execute(
        base + " AND t.product = ? ORDER BY d.id LIMIT 1", (fmt, platform, product)
    ).fetchone()
    if row is None:
        row = conn.execute(base + " ORDER BY d.id LIMIT 1", (fmt, platform)).fetchone()
    return row


def render_pending(conn: sqlite3.Connection, settings: Settings, tts=None) -> list[dict]:
    """Rend tous les brouillons approuvés (toutes plateformes) ; les erreurs sont rapportées."""
    results = []
    for row in list_drafts(conn, status="approved"):
        try:
            res = render_draft(conn, row["id"], settings, tts=tts)
            results.append(
                {"draft_id": row["id"], "ok": True, "video": res.video, "cover": res.cover}
            )
        except (RenderError, TTSError, ValueError) as e:
            results.append({"draft_id": row["id"], "ok": False, "error": str(e)})
    return results


def run_publish(
    conn: sqlite3.Connection,
    settings: Settings,
    now: datetime | None = None,
    *,
    live: bool = False,
    client=None,
    render_missing: bool = True,
    tts=None,
) -> dict:
    """Publie (dry-run par défaut) les créneaux échus pour lesquels un brouillon est prêt."""
    now = as_local(now, settings)
    report: dict = {"rendered": [], "published": [], "waiting": [], "skipped": []}
    if render_missing:
        report["rendered"] = render_pending(conn, settings, tts=tts)
    for slot in due_slots(conn, now):
        draft = candidate_draft(conn, slot, live=live)
        stale = slot_age(now, slot["slot_at"]) > SLOT_GRACE
        if draft is None:
            if stale:
                _skip_slot(conn, slot["id"], "aucun brouillon prêt dans les 24 h")
                report["skipped"].append(
                    {**dict(slot), "note": "aucun brouillon prêt dans les 24 h"}
                )
            else:
                report["waiting"].append(dict(slot))
            continue
        try:
            rep = publish_draft(
                conn, draft["id"], slot["platform"], settings, live=live, client=client
            )
        except PublishError as e:
            if stale:  # un créneau en échec depuis plus de 24 h n'est plus retenté
                _skip_slot(conn, slot["id"], f"échec de publication : {e}"[:300])
            report["skipped"].append({**dict(slot), "error": str(e)})
            continue
        note = (
            rep.outcome.url
            if (rep.outcome and rep.outcome.url)
            else (rep.outcome.remote_id if rep.outcome else f"dry-run : {rep.request_file}")
        )
        with conn:
            conn.execute(
                "UPDATE schedule SET status = 'published', draft_id = ?, note = ? WHERE id = ?",
                (draft["id"], note, slot["id"]),
            )
        report["published"].append(
            {
                "slot_id": slot["id"],
                "slot_at": slot["slot_at"],
                "platform": slot["platform"],
                "draft_id": draft["id"],
                "dry_run": rep.dry_run,
                "note": note,
            }
        )
    return report


SLOT_GRACE = timedelta(hours=24)  # un créneau échu attend un brouillon pendant 24 h


def _skip_slot(conn: sqlite3.Connection, slot_id: int, note: str) -> None:
    with conn:
        conn.execute(
            "UPDATE schedule SET status = 'skipped', note = ? WHERE id = ?", (note, slot_id)
        )


def format_deficits(conn: sqlite3.Connection, today: date, horizon_days: int = 7) -> dict[str, int]:
    """Créneaux planifiés à venir par format, moins les brouillons déjà disponibles."""
    to_day = (today + timedelta(days=horizon_days)).isoformat()
    planned = {f: 0 for f in FORMATS}
    for row in conn.execute(
        "SELECT format, COUNT(*) AS n FROM schedule WHERE status = 'planned' AND day >= ? "
        "AND day <= ? GROUP BY format",
        (today.isoformat(), to_day),
    ):
        planned[row["format"]] = row["n"]
    available = {f: 0 for f in FORMATS}
    # un brouillon déjà envoyé (même en dry-run) est consommé : il ne couvre plus de créneau
    for row in conn.execute(
        "SELECT format, COUNT(*) AS n FROM drafts d "
        "WHERE status IN ('draft', 'approved', 'rendered') "
        "AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.draft_id = d.id) "
        "GROUP BY format"
    ):
        available[row["format"]] = row["n"]
    # un sujet donne 3 variantes mais on ne publie en général qu'une : on compte par sujet
    return {f: planned[f] - available[f] // 3 for f in FORMATS}


FORMAT_CAPS = {"pin": 2, "linkedin": 1, "long": 1}  # par routine ; le reste en short


def choose_formats(deficits: dict[str, int], n: int) -> list[str]:
    """Formats des `n` sujets du jour : deux shorts au moins, puis les plus gros déficits."""
    chosen = ["short"] * min(2, n)
    used = {"short": len(chosen)}
    while len(chosen) < n:
        candidates = [f for f in FORMATS if used.get(f, 0) < FORMAT_CAPS.get(f, n)]
        best = max(candidates, key=lambda f: deficits.get(f, 0) - used.get(f, 0))
        fmt = best if deficits.get(best, 0) - used.get(best, 0) > 0 else "short"
        chosen.append(fmt)
        used[fmt] = used.get(fmt, 0) + 1
    return chosen


def run_daily(
    conn: sqlite3.Connection,
    settings: Settings,
    llm: LLM,
    today: date | None = None,
    *,
    min_bank: int = 20,
    scripts_per_day: int = 5,
    ideas_batch: int = 10,
) -> dict:
    """Routine du matin : idées si la banque est basse → scripts pour 5 sujets → relecture."""
    today = today or date.today()
    report: dict = {"ideas": {}, "scripts": [], "errors": []}
    for product in PRODUCTS:
        n = count_topics(conn, product, "new")
        if n < min_bank:
            try:
                inserted = generate_ideas(
                    conn, llm, product, min(ideas_batch, max(5, min_bank - n))
                )
                report["ideas"][product] = len(inserted)
            except Exception as e:  # le LLM local peut échouer : on continue la routine
                report["errors"].append(f"idées {product} : {e}")
    topics = pick_topics(conn, scripts_per_day)
    formats = choose_formats(format_deficits(conn, today), len(topics))
    for topic, fmt in pair_topics_with_formats(topics, formats):
        try:
            ids = generate_scripts(conn, llm, topic["id"], fmt)
            report["scripts"].append({"topic_id": topic["id"], "format": fmt, "draft_ids": ids})
        except Exception as e:
            report["errors"].append(f"script sujet #{topic['id']} ({fmt}) : {e}")
    report["review_file"] = str(export_review(conn, settings.out_dir, today))
    return report


def platform_for_format(fmt: str) -> str:
    for platform, formats in PLATFORM_FORMATS.items():
        if fmt in formats:
            return platform
    return "youtube"


def pair_topics_with_formats(
    topics: list[sqlite3.Row], formats: list[str]
) -> list[tuple[sqlite3.Row, str]]:
    """Donne chaque format à un sujet dont le produit est servi sur la plateforme visée (pas de
    post LinkedIn pour « avis », qui n'a pas de créneau LinkedIn) ; sinon le premier restant."""
    remaining = list(topics)
    pairs: list[tuple[sqlite3.Row, str]] = []
    for fmt in formats:
        platform = platform_for_format(fmt)
        idx = next(
            (i for i, t in enumerate(remaining) if platform in PRODUCTS[t["product"]].platforms),
            0,
        )
        pairs.append((remaining.pop(idx), fmt))
    return pairs
