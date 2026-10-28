"""Métriques : import des exports CSV (YouTube Studio, TikTok Studio), classement des angles.

La table `metrics` est un historique : chaque ligne est un relevé daté (`measured_at`) d'un contenu
sur une plateforme, venant d'un CSV (`source = 'csv'`) ou des API (`source = 'api'`, voir
`pull/`). Les classements ne regardent que le dernier relevé de chaque contenu
(`LATEST_METRIC_SQL`).
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .db import utc_now_iso
from .scripts import draft_payload, list_drafts
from .texts import youtube_title
from .topics import normalize_question

PLATFORMS = ("youtube", "tiktok", "pinterest", "linkedin")
DELIMITERS = (",", ";", "\t")
MIN_CONTENTS_PER_ANGLE = 3  # en dessous, le classement des angles n'est pas interprétable

# Dernier relevé d'un contenu (plateforme + brouillon), toutes sources confondues ; à utiliser
# avec l'alias `m` sur la table metrics.
LATEST_METRIC_SQL = (
    "m.id = (SELECT m2.id FROM metrics m2 WHERE m2.platform = m.platform "
    "AND m2.draft_id = m.draft_id "
    "ORDER BY COALESCE(m2.measured_at, m2.imported_at) DESC, m2.id DESC LIMIT 1)"
)

ALIASES: dict[str, list[str]] = {
    "remote_id": ["contenu", "content", "video id", "id de la video", "video_id", "id", "post id"],
    "title": [
        "titre de la video",
        "video title",
        "titre",
        "title",
        "nom de la video",
        "video name",
        "post title",
        "description",
    ],
    "views": [
        "vues",
        "views",
        "video views",
        "vues de la video",
        "nombre de vues",
        "total views",
        "vues totales",
    ],
    "likes": [
        "mentions j'aime",
        "mentions jaime",
        "likes",
        "j'aime",
        "jaime",
        "total likes",
        "mentions j aime",
    ],
    "comments": ["commentaires", "comments", "total comments"],
    "shares": ["partages", "shares", "total shares"],
    "impressions": ["impressions"],
    "ctr": [
        "taux de clics des impressions (%)",
        "impressions click-through rate (%)",
        "ctr",
        "taux de clics",
        "click-through rate",
    ],
    "avg_view_pct": [
        "pourcentage moyen visionne (%)",
        "average percentage viewed (%)",
        "pourcentage moyen de visionnage (%)",
        "average percentage viewed",
    ],
    "watch_time_h": ["duree de visionnage (heures)", "watch time (hours)"],
    "published_at": [
        "heure de publication de la video",
        "video publish time",
        "post time",
        "date de publication",
        "publish time",
        "date",
    ],
}


def norm_header(h: str) -> str:
    s = normalize_question(h.replace("’", "'"))
    return re.sub(r"\s+", " ", s).strip()


def _alias_keys() -> dict[str, dict[str, str]]:
    return {field: {norm_header(a): a for a in aliases} for field, aliases in ALIASES.items()}


def map_columns(headers: list[str]) -> dict[str, str]:
    """Champ interne → nom de colonne du CSV (première colonne qui correspond)."""
    normalized = {norm_header(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for field, aliases in _alias_keys().items():
        for norm, _ in aliases.items():
            if norm in normalized and normalized[norm] not in mapping.values():
                mapping[field] = normalized[norm]
                break
    return mapping


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace("\xa0", "").replace(" ", "").rstrip("%")
    if not s or s in ("-", "—"):
        return None
    if "," in s and "." not in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif "," in s and "." in s:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def detect_platform(headers: list[str], filename: str = "") -> str:
    norm = {norm_header(h) for h in headers}
    name = filename.lower()
    if "tiktok" in name or {"video views", "vues de la video"} & norm:
        return "tiktok"
    if (
        "youtube" in name
        or {"duree de visionnage (heures)", "watch time (hours)", "contenu", "content"} & norm
    ):
        return "youtube"
    return "unknown"


def _draft_titles(conn: sqlite3.Connection) -> dict[str, int]:
    """Clés normalisées → brouillon : titre, titre YouTube (tronqué à 100) et accroche (TikTok
    Studio exporte la légende, qui commence par l'accroche)."""
    titles: dict[str, int] = {}
    for row in list_drafts(conn):
        p = draft_payload(row)
        for text in (p.get("title", ""), youtube_title(p), p.get("hook", "")):
            key = normalize_question(text)
            if len(key) >= 8:
                titles.setdefault(key, row["id"])
    return titles


def match_title(title: str, titles: dict[str, int]) -> int | None:
    """Correspondance exacte, sinon par préfixe (titre tronqué par la plateforme, légende)."""
    key = normalize_question(title)
    if not key:
        return None
    if key in titles:
        return titles[key]
    if len(key) >= 20:
        for known, draft_id in titles.items():
            if len(known) >= 20 and (key.startswith(known) or known.startswith(key)):
                return draft_id
    return None


def link_draft(
    conn: sqlite3.Connection,
    platform: str,
    remote_id: str | None,
    title: str | None,
    titles: dict[str, int],
) -> int | None:
    if remote_id:
        row = conn.execute(
            "SELECT draft_id FROM publications "
            "WHERE platform = ? AND remote_id = ? AND dry_run = 0 "
            "ORDER BY id DESC LIMIT 1",
            (platform, remote_id),
        ).fetchone()
        if row:
            return int(row["draft_id"])
    if title:
        return match_title(title, titles)
    return None


def decode_csv(raw: bytes) -> str:
    """UTF-16 si BOM, sinon UTF-8 (avec ou sans BOM), sinon cp1252 (export retouché sous Excel)."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def sniff_delimiter(text: str) -> str:
    """Séparateur le plus fréquent dans la ligne d'en-tête (plus sûr que csv.Sniffer sur des
    titres pleins de virgules)."""
    header = next((line for line in text.splitlines() if line.strip()), "")
    counts = {d: header.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    text = decode_csv(path.read_bytes())
    # StringIO (et non splitlines) : un titre entre guillemets peut contenir un retour à la ligne
    reader = csv.DictReader(
        io.StringIO(text, newline=""), delimiter=sniff_delimiter(text), restkey="_extra"
    )
    rows: list[dict] = []
    for r in reader:
        clean = {
            k: (v if isinstance(v, str) else "") for k, v in r.items() if k not in (None, "_extra")
        }
        if any(v.strip() for v in clean.values()):
            rows.append(clean)
    return [h for h in (reader.fieldnames or []) if h], rows


def _num(row: dict, mapping: dict[str, str], field: str) -> float | None:
    col = mapping.get(field)
    return parse_number(row.get(col)) if col else None


def parse_datetime(value: str | None) -> datetime | None:
    """Date ISO (avec ou sans heure, « Z » accepté) ou préfixe AAAA-MM-JJ ; naïve = UTC."""
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if not m:
            return None
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def import_csv(conn: sqlite3.Connection, path: str | Path, platform: str | None = None) -> dict:
    """Importe un export CSV ; remplace les lignes déjà importées (CSV) pour le même contenu, sans
    toucher aux relevés API (`ce metrics --pull`), qui forment un historique daté."""
    path = Path(path)
    headers, rows = read_csv(path)
    mapping = map_columns(headers)
    if "views" not in mapping:
        raise ValueError(f"colonne « vues » introuvable dans {path.name} (colonnes : {headers})")
    if platform:
        platform = platform.strip().lower()
        if platform not in PLATFORMS:
            raise ValueError(f"plateforme inconnue : {platform!r} (choix : {', '.join(PLATFORMS)})")
    else:
        platform = detect_platform(headers, path.name)
    titles = _draft_titles(conn)
    imported = linked = skipped = 0
    for r in rows:
        remote_id = (r.get(mapping.get("remote_id", ""), "") or "").strip() or None
        title = (r.get(mapping.get("title", ""), "") or "").strip() or None
        if (remote_id or "").lower() in ("total", "totaux") or (title or "").lower() == "total":
            skipped += 1
            continue
        if not remote_id and not title:  # sans clé, la ligne serait dupliquée à chaque import
            skipped += 1
            continue
        views = parse_number(r.get(mapping["views"]))
        if views is None:
            skipped += 1
            continue

        draft_id = link_draft(conn, platform, remote_id, title, titles)
        linked += draft_id is not None
        now = utc_now_iso()
        with conn:
            if remote_id:
                conn.execute(
                    "DELETE FROM metrics WHERE platform = ? AND remote_id = ? AND source = 'csv'",
                    (platform, remote_id),
                )
            elif title:
                conn.execute(
                    "DELETE FROM metrics WHERE platform = ? AND remote_id IS NULL AND title = ? "
                    "AND source = 'csv'",
                    (platform, title),
                )
            conn.execute(
                "INSERT INTO metrics (platform, remote_id, title, draft_id, views, likes, "
                "comments, "
                "shares, impressions, ctr, avg_view_pct, watch_time_h, published_at, imported_at, "
                "source_file, measured_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'csv')",
                (
                    platform,
                    remote_id,
                    title,
                    draft_id,
                    int(views),
                    int(_num(r, mapping, "likes") or 0),
                    int(_num(r, mapping, "comments") or 0),
                    int(_num(r, mapping, "shares") or 0),
                    int(_num(r, mapping, "impressions"))
                    if _num(r, mapping, "impressions") is not None
                    else None,
                    _num(r, mapping, "ctr"),
                    _num(r, mapping, "avg_view_pct"),
                    _num(r, mapping, "watch_time_h"),
                    (r.get(mapping.get("published_at", ""), "") or "").strip() or None,
                    now,
                    path.name,
                    now,
                ),
            )
        imported += 1
    return {
        "platform": platform,
        "imported": imported,
        "linked": linked,
        "skipped": skipped,
        "columns": mapping,
    }


def angle_ranking(conn: sqlite3.Connection, product: str | None = None) -> list[dict]:
    """Angles classés par vues moyennes brutes (dernier relevé de chaque contenu lié à un
    brouillon). Le score normalisé et lissé est dans `angles.angle_scores`."""
    sql = (
        "SELECT t.product, COALESCE(t.angle, 'libre') AS angle, COUNT(*) AS n, "
        "SUM(m.views) AS views_total, AVG(m.views) AS views_avg, AVG(m.ctr) AS ctr_avg, "
        "AVG(m.avg_view_pct) AS view_pct_avg, AVG(m.likes) AS likes_avg "
        "FROM metrics m JOIN drafts d ON d.id = m.draft_id JOIN topics t ON t.id = d.topic_id "
        f"WHERE {LATEST_METRIC_SQL} "
    )
    params: list = []
    if product:
        sql += "AND t.product = ? "
        params.append(product)
    sql += "GROUP BY t.product, angle ORDER BY views_avg DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def unlinked_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM metrics WHERE draft_id IS NULL").fetchone()[0])
