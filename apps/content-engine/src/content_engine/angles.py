"""Sélection automatique des angles (P4-4) : score robuste par angle et par produit.

1. Chaque contenu mesuré (dernier relevé, voir `metrics.LATEST_METRIC_SQL`) est ramené à des vues
   « projetées » : les vues s'accumulent vite puis saturent, on divise par 1 − exp(−âge / τ)
   (τ = 7 jours : 63 % des vues à 7 jours, 95 % à 21 jours). Un relevé de moins de 2 jours est
   trop précoce et n'entre pas dans le score (il est seulement signalé).
2. Normalisation par plateforme : x = log2(projetées + 1) − médiane de la plateforme (tous
   produits confondus). 5 000 impressions Pinterest et 300 vues YouTube valent toutes deux 0 si
   c'est la médiane de leur plateforme ; +1 = deux fois la médiane, −1 = la moitié.
3. Lissage bayésien par (produit, angle) : score = (n · moyenne + k · a priori) / (n + k), avec
   a priori = moyenne des x du produit et k = ANGLE_PRIOR_WEIGHT (5 pseudo-observations) : un
   angle vu 2 fois reste près de l'a priori, un angle vu 20 fois parle pour lui-même.
4. Décision par produit : les angles au-dessus de la médiane des scores sont privilégiés
   (exploitation, voir `topics.select_topics`) ; un angle mesuré sur ≥ ANGLE_PAUSE_MIN_CONTENTS
   contenus et à plus de log2(1 / ANGLE_PAUSE_RATIO) sous la médiane est mis en pause (table
   `angle_status`), réactivé automatiquement s'il remonte à mi-chemin, ou à la main avec
   `ce angles --reactivate`.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .db import utc_now_iso
from .metrics import LATEST_METRIC_SQL, parse_datetime

TAU_DAYS = 7.0  # vitesse de saturation des vues
MIN_AGE_DAYS = 2.0  # en dessous, le relevé est trop précoce
DEFAULT_PRIOR_WEIGHT = 5.0
DEFAULT_PAUSE_MIN_CONTENTS = 6
DEFAULT_PAUSE_RATIO = 0.5
STATUSES = ("active", "paused")


def age_factor(age_days: float | None) -> float:
    """Part des vues « à vie » attendue à cet âge ; âge inconnu = contenu mûr (facteur 1)."""
    if age_days is None:
        return 1.0
    return 1.0 - math.exp(-max(age_days, MIN_AGE_DAYS) / TAU_DAYS)


def shrink(n: int, mean: float, prior: float, weight: float) -> float:
    """Moyenne lissée vers l'a priori avec `weight` pseudo-observations."""
    return (n * mean + weight * prior) / (n + weight) if n + weight > 0 else prior


def pause_margin(pause_ratio: float) -> float:
    """Écart (log2) sous la médiane à partir duquel un angle est mis en pause ; 0 = jamais."""
    if pause_ratio <= 0:
        return math.inf
    return -math.log2(min(pause_ratio, 1.0))


@dataclass
class ContentScore:
    draft_id: int
    product: str
    angle: str
    platform: str
    views: int
    age_days: float | None
    projected: float
    x: float = 0.0  # écart log2 à la médiane de la plateforme
    too_recent: bool = False


@dataclass
class AngleScore:
    product: str
    angle: str
    n: int = 0
    raw_mean: float = 0.0
    prior: float = 0.0
    score: float = 0.0
    views_avg: float = 0.0
    platforms: dict[str, int] = field(default_factory=dict)
    too_recent: int = 0
    median: float = 0.0  # médiane des scores du produit
    above_median: bool = False
    status: str = "active"
    decided_by: str = "auto"
    reason: str | None = None
    status_since: str | None = None

    @property
    def ratio(self) -> float:
        """Vues lissées par rapport au contenu médian de la plateforme (×1 = médiane)."""
        return 2.0**self.score


def latest_contents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT m.id, m.platform, m.draft_id, m.views, "
        "COALESCE(m.measured_at, m.imported_at) AS measured_at, "
        "m.published_at AS csv_published_at, t.product, COALESCE(t.angle, 'libre') AS angle, "
        "(SELECT p.published_at FROM publications p WHERE p.draft_id = m.draft_id "
        "AND p.platform = m.platform AND p.dry_run = 0 ORDER BY p.id DESC LIMIT 1) "
        "AS live_published_at "
        "FROM metrics m JOIN drafts d ON d.id = m.draft_id JOIN topics t ON t.id = d.topic_id "
        f"WHERE {LATEST_METRIC_SQL} ORDER BY m.id"
    ).fetchall()


def content_scores(conn: sqlite3.Connection) -> list[ContentScore]:
    """Un score par contenu mesuré : vues projetées selon l'âge, puis écart à la médiane de sa
    plateforme (0 si la plateforme n'a qu'un contenu : un seul point ne dit rien)."""
    contents: list[ContentScore] = []
    for r in latest_contents(conn):
        measured = parse_datetime(r["measured_at"])
        published = parse_datetime(r["live_published_at"]) or parse_datetime(r["csv_published_at"])
        age = None
        if measured and published:
            age = max((measured - published).total_seconds() / 86400, 0.0)
        views = int(r["views"] or 0)
        contents.append(
            ContentScore(
                draft_id=int(r["draft_id"]),
                product=r["product"],
                angle=r["angle"],
                platform=r["platform"],
                views=views,
                age_days=age,
                projected=views / age_factor(age),
                too_recent=age is not None and age < MIN_AGE_DAYS,
            )
        )
    by_platform: dict[str, list[ContentScore]] = defaultdict(list)
    for c in contents:
        if not c.too_recent:
            by_platform[c.platform].append(c)
    for group in by_platform.values():
        if len(group) < 2:
            continue
        med = statistics.median(math.log2(c.projected + 1) for c in group)
        for c in group:
            c.x = math.log2(c.projected + 1) - med
    return contents


def angle_scores(
    conn: sqlite3.Connection,
    product: str | None = None,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
) -> list[AngleScore]:
    """Scores lissés par (produit, angle), avec médiane du produit et statut courant ; les angles
    en pause sans contenu mesuré sont listés aussi (n = 0)."""
    contents = [c for c in content_scores(conn) if product is None or c.product == product]
    scores: dict[tuple[str, str], AngleScore] = {}
    xs: dict[str, list[float]] = defaultdict(list)
    for c in contents:
        a = scores.setdefault((c.product, c.angle), AngleScore(c.product, c.angle))
        if c.too_recent:
            a.too_recent += 1
            continue
        xs[c.product].append(c.x)
        a.n += 1
        a.raw_mean += c.x
        a.views_avg += c.views
        a.platforms[c.platform] = a.platforms.get(c.platform, 0) + 1
    for a in scores.values():
        if a.n:
            a.raw_mean /= a.n
            a.views_avg /= a.n
        a.prior = statistics.fmean(xs[a.product]) if xs[a.product] else 0.0
        a.score = shrink(a.n, a.raw_mean, a.prior, prior_weight) if a.n else a.prior
    for prod in {a.product for a in scores.values()}:
        measured = [a for a in scores.values() if a.product == prod and a.n]
        if measured:
            med = statistics.median(a.score for a in measured)
            for a in measured:
                a.median, a.above_median = med, a.score >= med
    rows = {(r["product"], r["angle"]): r for r in conn.execute("SELECT * FROM angle_status")}
    for (prod, angle), row in rows.items():
        if product is not None and prod != product:
            continue
        a = scores.setdefault((prod, angle), AngleScore(prod, angle))
        a.status, a.decided_by = row["status"], row["decided_by"]
        a.reason, a.status_since = row["reason"], row["updated_at"]
    return sorted(scores.values(), key=lambda a: (a.product, -a.score, a.angle))


def set_angle_status(
    conn: sqlite3.Connection,
    product: str,
    angle: str,
    status: str,
    reason: str | None,
    decided_by: str = "manual",
    score: float | None = None,
    n: int = 0,
    now: str | None = None,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"statut inconnu : {status}")
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO angle_status (product, angle, status, decided_by, reason, "
            "score, n_contents, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (product, angle, status, decided_by, reason, score, n, now or utc_now_iso()),
        )


def paused_angles(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    return {
        (r["product"], r["angle"])
        for r in conn.execute("SELECT product, angle FROM angle_status WHERE status = 'paused'")
    }


def update_angle_status(
    conn: sqlite3.Connection,
    scores: list[AngleScore],
    *,
    min_contents: int = DEFAULT_PAUSE_MIN_CONTENTS,
    pause_ratio: float = DEFAULT_PAUSE_RATIO,
    now: str | None = None,
) -> list[dict]:
    """Met en pause les angles nettement sous la médiane depuis assez de contenus, réactive ceux
    (mis en pause automatiquement) qui remontent à mi-chemin. Un angle réactivé à la main n'est
    remis en pause qu'après `min_contents` nouveaux contenus mesurés. Retourne les décisions."""
    now_iso = now or utc_now_iso()
    margin = pause_margin(pause_ratio)
    rows = {(r["product"], r["angle"]): r for r in conn.execute("SELECT * FROM angle_status")}
    decisions: list[dict] = []
    for a in scores:
        if not a.n:
            continue
        row = rows.get((a.product, a.angle))
        gap = a.score - a.median
        if row is None or row["status"] == "active":
            grace = (
                row is not None
                and row["decided_by"] == "manual"
                and a.n < int(row["n_contents"] or 0) + min_contents
            )
            if a.n >= min_contents and gap < -margin and not grace:
                reason = (
                    f"score {a.score:+.2f} à {-gap:.2f} sous la médiane {a.median:+.2f} du "
                    f"produit (seuil {margin:.2f} : vues lissées sous {pause_ratio:.0%} de "
                    f"l'angle médian) après {a.n} contenus mesurés"
                )
                status = "paused"
            else:
                continue
        elif row["decided_by"] == "auto" and gap > -margin / 2:
            reason = (
                f"score {a.score:+.2f} revenu à moins de {margin / 2:.2f} sous la médiane "
                f"{a.median:+.2f}"
            )
            status = "active"
        else:
            continue
        set_angle_status(conn, a.product, a.angle, status, reason, "auto", a.score, a.n, now_iso)
        a.status, a.decided_by, a.reason, a.status_since = status, "auto", reason, now_iso
        decisions.append(
            {"product": a.product, "angle": a.angle, "status": status, "reason": reason}
        )
    return decisions


def strong_angles(scores: list[AngleScore]) -> dict[str, set[str]]:
    """Par produit mesuré, les angles actifs au-dessus de la médiane (exploitation)."""
    strong: dict[str, set[str]] = {}
    for a in scores:
        if a.n:
            strong.setdefault(a.product, set())
            if a.above_median and a.status == "active":
                strong[a.product].add(a.angle)
    return strong


def status_label(a: AngleScore) -> str:
    if a.status == "paused":
        return "en pause (auto)" if a.decided_by == "auto" else "en pause (manuel)"
    if not a.n:
        return "trop récent" if a.too_recent else "sans données"
    return "privilégié" if a.above_median else "à explorer"


def explain(
    a: AngleScore,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    min_contents: int = DEFAULT_PAUSE_MIN_CONTENTS,
    pause_ratio: float = DEFAULT_PAUSE_RATIO,
) -> list[str]:
    """Pourquoi cet angle est privilégié, à explorer ou en pause (`ce angles --explain`)."""
    margin = pause_margin(pause_ratio)
    lines: list[str] = []
    platforms = ", ".join(f"{p} {n}" for p, n in sorted(a.platforms.items()))
    recent = f" (+ {a.too_recent} trop récent(s), relevé avant {MIN_AGE_DAYS:.0f} jours)"
    lines.append(
        f"contenus mesurés : {a.n}"
        + (f" ({platforms})" if platforms else "")
        + (recent if a.too_recent else "")
    )
    if a.n:
        lines.append(
            f"vues moyennes brutes {a.views_avg:,.0f} ; écart moyen à la médiane de la "
            f"plateforme (vues projetées selon l'âge, τ = {TAU_DAYS:.0f} j) : "
            f"{a.raw_mean:+.2f} (×{2**a.raw_mean:.2f})".replace(",", " ")
        )
        lines.append(
            f"score lissé (k = {prior_weight:g} pseudo-contenus vers l'a priori du produit "
            f"{a.prior:+.2f}) : {a.score:+.2f} (×{a.ratio:.2f}) ; médiane des angles du "
            f"produit {a.median:+.2f} → "
            + ("au-dessus : privilégié" if a.above_median else "en dessous : exploration")
        )
        gap = a.score - a.median
        if a.status != "paused":
            if math.isinf(margin):
                lines.append("pause automatique désactivée (ANGLE_PAUSE_RATIO=0)")
            else:
                lines.append(
                    f"pause si ≥ {min_contents} contenus et score < médiane − {margin:.2f} "
                    f"(vues lissées < {pause_ratio:.0%} de l'angle médian) : "
                    f"écart actuel {gap:+.2f}, {a.n} contenu(s) → "
                    + ("non" if gap >= -margin or a.n < min_contents else "oui")
                )
    if a.status == "paused":
        since = (a.status_since or "")[:10]
        how = "automatique" if a.decided_by == "auto" else "manuel"
        lines.append(
            f"en pause depuis {since or '?'} ({how})"
            + (f" : {a.reason}" if a.reason else "")
            + f" · réactiver : `ce angles --reactivate {a.angle} -p {a.product}`"
        )
    elif a.decided_by == "manual" and a.status_since:
        lines.append(
            f"réactivé à la main le {a.status_since[:10]}" + (f" : {a.reason}" if a.reason else "")
        )
    return lines
