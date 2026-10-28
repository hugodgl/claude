"""CLI `ce` : banque de sujets, scripts, relecture, rendu, publication, planification, métriques."""

from __future__ import annotations

import functools
import shutil
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

import typer
from core.llm import LLMError
from rich.console import Console
from rich.table import Table

from . import __version__
from .angles import angle_scores, explain, set_angle_status, status_label
from .db import open_db
from .llm import get_engine_llm
from .metrics import MIN_CONTENTS_PER_ANGLE, angle_ranking, import_csv, unlinked_count
from .planning import build_plan, list_schedule, local_now, run_daily, run_publish, save_plan
from .products import ANGLES, PRODUCTS
from .publish import PLATFORMS, PublishError, publish_draft
from .publish.youtube import ANALYTICS_SCOPE, READONLY_SCOPE, token_scopes
from .pull import PLATFORMS as PULL_PLATFORMS
from .pull import PullError, last_measurement, pull_metrics
from .render import RenderError, find_font, render_draft
from .render.ffmpeg import ffmpeg_version
from .review import approve as approve_draft
from .review import draft_markdown, export_review, pending_drafts, review_table
from .review import reject as reject_draft
from .scripts import FORMATS, generate_scripts, get_draft, list_drafts
from .settings import Settings
from .topics import add_topic, count_topics, generate_ideas, list_topics, seed_topics
from .tts.base import TTSError

app = typer.Typer(
    help=(
        "Moteur de contenu : sujets → scripts → relecture → rendu vertical → publication (dry-run)."
    ),
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
# OSError couvre disque plein, permissions, fichier absent ; sqlite3.Error la base verrouillée.
ERRORS = (
    ValueError,
    LookupError,
    LLMError,
    RenderError,
    PublishError,
    PullError,
    TTSError,
    OSError,
    sqlite3.Error,
)


def _settings() -> Settings:
    return Settings()


def _db(settings: Settings):
    return open_db(settings.db_path)


def guard(fn):
    """Convertit les erreurs métier en message lisible et code de sortie 1."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ERRORS as e:
            console.print(f"[bold red]Erreur :[/bold red] {e}")
            raise typer.Exit(code=1) from None

    return wrapper


def _version(value: bool):
    if value:
        console.print(f"content-engine {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Affiche la version."
    ),
):
    """Commandes du moteur de contenu. Tout est en dry-run tant que --live n'est pas passé."""


# ----------------------------------------------------------------------------------------------
# Banque de sujets
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def init():
    """Crée la base et charge topics.yaml (idempotent)."""
    s = _settings()
    conn = _db(s)
    added = seed_topics(conn, s.topics_file)
    console.print(f"Base : {s.db_path} · sujets ajoutés : {added}")
    for slug in PRODUCTS:
        console.print(
            f"  {slug:<9} {count_topics(conn, slug, 'new'):>3} nouveaux, "
            f"{count_topics(conn, slug, 'used'):>3} utilisés"
        )


@app.command()
@guard
def topics(
    product: str | None = typer.Option(None, "--product", "-p", help="avis | marches | cabinets"),
    status: str | None = typer.Option(None, "--status", help="new | used | rejected"),
    limit: int = typer.Option(60, "--limit"),
):
    """Liste la banque de sujets."""
    conn = _db(_settings())
    rows = list_topics(conn, product, status, limit)
    table = Table(title=f"Sujets ({len(rows)})")
    for col in ("ID", "Produit", "Statut", "Angle", "Question"):
        table.add_column(col)
    for r in rows:
        table.add_row(str(r["id"]), r["product"], r["status"], r["angle"] or "-", r["question"])
    console.print(table)


@app.command("add-topic")
@guard
def add_topic_cmd(
    question: str = typer.Argument(..., help="La question telle qu'un prospect la tape."),
    product: str = typer.Option(..., "--product", "-p"),
    angle: str | None = typer.Option(None, "--angle", help="Voir `ce angles --list`."),
):
    """Ajoute un sujet à la main."""
    if angle and angle not in ANGLES:
        raise ValueError(f"angle inconnu : {angle} (voir `ce angles --list`)")
    conn = _db(_settings())
    topic_id = add_topic(conn, product, question, angle, source="manual")
    if topic_id is None:
        console.print("[yellow]Sujet déjà présent, rien ajouté.[/yellow]")
    else:
        console.print(f"Sujet #{topic_id} ajouté.")


@app.command()
@guard
def ideas(
    product: str = typer.Option(..., "--product", "-p", help="avis | marches | cabinets"),
    count: int = typer.Option(10, "--count", "-n", min=1, max=40),
):
    """Génère de nouvelles questions via le LLM, sans doublons."""
    s = _settings()
    conn = _db(s)
    inserted = generate_ideas(conn, get_engine_llm(s), product, count)
    for item in inserted:
        console.print(f"  #{item['id']} [{item.get('angle') or 'libre'}] {item['question']}")
    console.print(
        f"{len(inserted)} nouveau(x) sujet(s) pour {product} "
        f"(banque : {count_topics(conn, product, 'new')} nouveaux)."
    )


# ----------------------------------------------------------------------------------------------
# Scripts et relecture
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def script(
    topic_id: int = typer.Option(..., "--topic-id", "-t"),
    fmt: str = typer.Option("short", "--format", "-f", help="short | long | linkedin | pin"),
    variants: int = typer.Option(3, "--variants", min=1, max=5),
):
    """Génère 3 variantes de script pour un sujet et un format."""
    s = _settings()
    conn = _db(s)
    if fmt not in FORMATS:
        raise ValueError(f"format inconnu : {fmt} (choix : {', '.join(FORMATS)})")
    ids = generate_scripts(conn, get_engine_llm(s), topic_id, fmt, variants)
    console.print(f"Brouillons créés : {', '.join('#' + str(i) for i in ids)} → `ce review`")


@app.command()
@guard
def review():
    """Liste les brouillons en attente de validation."""
    conn = _db(_settings())
    rows = pending_drafts(conn)
    console.print(review_table(rows))
    counts = {
        r["status"]: r["n"]
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM drafts GROUP BY status")
    }
    console.print(
        "Statuts : " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "aucun")
    )


@app.command()
@guard
def show(draft_id: int = typer.Argument(...)):
    """Affiche un brouillon complet."""
    conn = _db(_settings())
    row = get_draft(conn, draft_id)
    console.print(draft_markdown(row))
    console.print(
        f"Statut : {row['status']}" + (f" ({row['reject_reason']})" if row["reject_reason"] else "")
    )


@app.command()
@guard
def approve(draft_ids: list[int] = typer.Argument(..., help="Un ou plusieurs identifiants.")):
    """Approuve un ou plusieurs brouillons."""
    conn = _db(_settings())
    for draft_id in draft_ids:
        row = approve_draft(conn, draft_id)
        console.print(f"#{draft_id} approuvé ({row['product']}/{row['format']}).")


@app.command()
@guard
def reject(
    draft_id: int = typer.Argument(...),
    reason: str = typer.Option(
        ..., "--reason", "-r", help="Motif court (conservé en base, visible avec `ce show`)."
    ),
):
    """Rejette un brouillon avec un motif."""
    conn = _db(_settings())
    reject_draft(conn, draft_id, reason)
    console.print(f"#{draft_id} rejeté : {reason}")


@app.command("export-review")
@guard
def export_review_cmd(
    day: str | None = typer.Option(None, "--date", help="AAAA-MM-JJ (défaut : aujourd'hui)"),
):
    """Écrit out/review-AAAA-MM-JJ.md pour la relecture du matin."""
    s = _settings()
    conn = _db(s)
    d = date.fromisoformat(day) if day else date.today()
    path = export_review(conn, s.out_dir, d)
    console.print(f"Relecture écrite : {path} ({len(pending_drafts(conn))} brouillon(s))")


# ----------------------------------------------------------------------------------------------
# Rendu et publication
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def render(
    draft_id: int | None = typer.Option(None, "--draft-id", "-d"),
    approved: bool = typer.Option(False, "--approved", help="Rend tous les brouillons approuvés."),
    force: bool = typer.Option(False, "--force", help="Aperçu d'un brouillon non approuvé."),
):
    """Rend la vidéo verticale (short), la couverture et la miniature dans out/<id>/."""
    s = _settings()
    conn = _db(s)
    if draft_id is None and not approved:
        raise ValueError("préciser --draft-id N ou --approved")
    ids = (
        [draft_id]
        if draft_id is not None
        else [r["id"] for r in list_drafts(conn, status="approved")]
    )
    if not ids:
        console.print("Aucun brouillon approuvé à rendre.")
        return
    failed = 0
    for did in ids:
        try:
            res = render_draft(conn, did, s, force=force)
        except ERRORS as e:
            if len(ids) == 1:
                raise
            failed += 1  # un brouillon en échec n'empêche pas de rendre les autres
            console.print(f"[red]#{did} non rendu : {e}[/red]")
            continue
        files = ", ".join(f for f in (res.video, res.cover, res.thumb, res.text_file) if f)
        dur = f" · {res.duration_s:.1f} s" if res.video else ""
        console.print(f"#{did} rendu ({res.format}) → {res.out_dir}/ [{files}]{dur}")
    if failed:
        raise typer.Exit(code=1)


@app.command()
@guard
def publish(
    draft_id: int = typer.Option(..., "--draft-id", "-d"),
    platform: str = typer.Option(..., "--platform", help="youtube | pinterest | linkedin | tiktok"),
    live: bool = typer.Option(False, "--live", help="Envoi réel (sinon dry-run : fichier JSON)."),
    force: bool = typer.Option(False, "--force", help="Republier même si déjà publié."),
):
    """Publie un brouillon rendu (dry-run par défaut : out/<id>/publish-<plateforme>.json)."""
    s = _settings()
    conn = _db(s)
    if platform not in PLATFORMS:
        raise ValueError(f"plateforme inconnue : {platform} (choix : {', '.join(PLATFORMS)})")
    rep = publish_draft(conn, draft_id, platform, s, live=live, force=force)
    if rep.dry_run:
        console.print(
            f"[yellow]Dry-run[/yellow] {platform} #{draft_id} : requête décrite dans "
            f"{rep.request_file}"
        )
    else:
        console.print(
            f"[green]Publié[/green] sur {platform} : {rep.outcome.url or rep.outcome.remote_id}"
        )


# ----------------------------------------------------------------------------------------------
# Planification et routines
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def plan(
    days: int = typer.Option(7, "--days", min=1, max=60),
    start: str | None = typer.Option(None, "--start", help="AAAA-MM-JJ (défaut : demain)"),
):
    """Calendrier : 1 short, 1 TikTok, 5 pins par jour ; 3 LinkedIn et 1 long par semaine."""
    s = _settings()
    conn = _db(s)
    first = (
        date.fromisoformat(start)
        if start
        else date.fromordinal(local_now(s).date().toordinal() + 1)
    )
    slots = build_plan(first, days)
    added = save_plan(conn, slots)
    table = Table(
        title=f"Calendrier du {first.isoformat()} sur {days} jour(s) : {added} créneau(x) ajouté(s)"
    )
    for col in ("Créneau", "Plateforme", "Format", "Produit"):
        table.add_column(col)
    for sl in slots:
        table.add_row(sl.slot_at.replace("T", " "), sl.platform, sl.format, sl.product)
    console.print(table)


@app.command()
@guard
def schedule(
    from_day: str | None = typer.Option(None, "--from"),
    to_day: str | None = typer.Option(None, "--to"),
    status: str | None = typer.Option(None, "--status", help="planned | published | skipped"),
):
    """Affiche les créneaux planifiés."""
    conn = _db(_settings())
    rows = list_schedule(conn, from_day, to_day, status)
    table = Table(title=f"Créneaux ({len(rows)})")
    for col in ("ID", "Créneau", "Plateforme", "Format", "Produit", "Statut", "Brouillon", "Note"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["id"]),
            r["slot_at"].replace("T", " "),
            r["platform"],
            r["format"],
            r["product"] or "-",
            r["status"],
            str(r["draft_id"] or "-"),
            r["note"] or "",
        )
    console.print(table)


@app.command("run-daily")
@guard
def run_daily_cmd(
    min_bank: int = typer.Option(20, "--min-bank", help="Seuil de sujets `new` par produit."),
    scripts: int = typer.Option(5, "--scripts", help="Sujets à scripter aujourd'hui."),
):
    """Routine du matin : idées si la banque est basse, scripts pour 5 sujets, export relecture."""
    s = _settings()
    conn = _db(s)
    rep = run_daily(conn, s, get_engine_llm(s), min_bank=min_bank, scripts_per_day=scripts)
    angles_info = rep.get("angles", {})
    for d in angles_info.get("decisions", []):
        verb = "mis en pause" if d["status"] == "paused" else "réactivé"
        console.print(f"Angle {d['product']}/{d['angle']} {verb} : {d['reason']}")
    if angles_info.get("paused"):
        console.print(
            "Angles en pause : "
            + ", ".join(angles_info["paused"])
            + " (`ce angles --explain`, `ce angles --reactivate`)"
        )
    for product, favored in angles_info.get("favored", {}).items():
        console.print(f"Angles privilégiés pour {product} : {', '.join(favored) or 'aucun'}")
    for product, n in rep["ideas"].items():
        console.print(f"Idées : {n} nouveau(x) sujet(s) pour {product}")
    for item in rep["scripts"]:
        console.print(
            f"Scripts : sujet #{item['topic_id']} ({item['format']}, angle "
            f"{item.get('angle', 'libre')}, {item.get('mode', 'ancienneté')}) → "
            + ", ".join("#" + str(i) for i in item["draft_ids"])
        )
    for e in rep["errors"]:
        console.print(f"[red]{e}[/red]")
    console.print(f"Relecture : {rep['review_file']}")


@app.command("run-publish")
@guard
def run_publish_cmd(
    live: bool = typer.Option(False, "--live", help="Envoi réel (sinon dry-run)."),
    do_render: bool = typer.Option(
        True, "--render/--no-render", help="Rend d'abord les approuvés."
    ),
):
    """Publie les créneaux échus dont un brouillon rendu est prêt (dry-run par défaut)."""
    s = _settings()
    conn = _db(s)
    rep = run_publish(conn, s, live=live, render_missing=do_render)
    for r in rep["rendered"]:
        console.print(
            f"Rendu #{r['draft_id']} : " + ("ok" if r["ok"] else f"[red]{r['error']}[/red]")
        )
    for p in rep["published"]:
        tag = "[yellow]dry-run[/yellow]" if p["dry_run"] else "[green]publié[/green]"
        console.print(f"{tag} {p['slot_at']} {p['platform']} #{p['draft_id']} → {p['note']}")
    for w in rep["waiting"]:
        console.print(
            f"[dim]en attente[/dim] {w['slot_at']} {w['platform']}/{w['format']} : "
            "aucun brouillon prêt"
        )
    for sk in rep["skipped"]:
        console.print(
            f"[red]ignoré[/red] {sk['slot_at']} {sk['platform']} : "
            f"{sk.get('error') or sk.get('note') or ''}"
        )
    if not any(rep.values()):
        console.print("Rien à faire.")


# ----------------------------------------------------------------------------------------------
# Métriques
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def metrics(
    import_file: Path | None = typer.Option(
        None, "--import", exists=True, dir_okay=False, help="Export CSV YouTube Studio ou TikTok."
    ),
    pull: bool = typer.Option(
        False, "--pull", help="Relève les métriques des publications réelles via les API."
    ),
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="--pull : youtube | pinterest | tiktok | linkedin | all ; --import : youtube | tiktok "
        "(détection auto sinon)",
    ),
    days: int = typer.Option(
        90, "--days", min=1, max=3650, help="--pull : publications des N derniers jours."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="--pull : affiche sans rien écrire."),
):
    """Importe un export CSV (--import) ou relève les métriques via les API (--pull)."""
    if import_file is None and not pull:
        raise ValueError("préciser --import export.csv ou --pull")
    s = _settings()
    conn = _db(s)
    if import_file is not None:
        rep = import_csv(conn, import_file, platform)
        console.print(
            f"{rep['platform']} : {rep['imported']} ligne(s) importée(s), {rep['linked']} liée(s) "
            f"à un brouillon, {rep['skipped']} ignorée(s). Colonnes : {rep['columns']}"
        )
    if not pull:
        return
    wanted = (
        None
        if platform in (None, "all")
        else [p.strip().lower() for p in platform.split(",") if p.strip()]
    )
    if wanted and any(p not in PULL_PLATFORMS for p in wanted):
        raise ValueError(
            f"plateforme inconnue : {platform} (choix : {', '.join(PULL_PLATFORMS)}, all)"
        )
    report = pull_metrics(conn, s, platforms=wanted, days=days, dry_run=dry_run)
    if dry_run:
        console.print("[yellow]Dry-run[/yellow] : rien n'est écrit en base.")
    table = Table(title=f"Relevé du {report.measured_at[:16].replace('T', ' ')} UTC")
    cols = ("Plateforme", "Brouillon", "Identifiant", "Vues", "J'aime", "Comm.", "Partages")
    cols += ("Impr.", "Clics", "Rétention %")
    for col in cols:
        table.add_column(col, justify="left" if col in cols[:3] else "right")
    for pr in report.platforms.values():
        for snap in pr.snapshots:
            table.add_row(
                pr.platform,
                f"#{snap.item.draft_id}",
                snap.item.remote_id[:24],
                str(snap.views),
                str(snap.likes),
                str(snap.comments),
                str(snap.shares),
                str(snap.impressions) if snap.impressions is not None else "-",
                str(snap.clicks) if snap.clicks is not None else "-",
                f"{snap.avg_view_pct:.0f}" if snap.avg_view_pct is not None else "-",
            )
    if table.row_count:
        console.print(table)
    for pr in report.platforms.values():
        head = f"{pr.platform} : {pr.publications} publication(s)"
        if pr.error:
            console.print(f"[red]{head} — erreur : {pr.error}[/red]")
        elif pr.publications and pr.available:
            done = "affiché(s)" if dry_run else "enregistré(s)"
            console.print(f"{head}, {len(pr.snapshots)} relevé(s) {done}")
        else:
            console.print(f"[dim]{head}[/dim]")
        for note in pr.notes:
            console.print(f"  [dim]{note}[/dim]")
    if report.attempted and not report.succeeded:
        raise typer.Exit(code=1)  # toutes les plateformes tentées ont échoué : code 1 pour launchd


def _target_angle(angle: str) -> str:
    if angle not in ANGLES and angle != "libre":
        raise ValueError(f"angle inconnu : {angle} (voir `ce angles --list`)")
    return angle


@app.command()
@guard
def angles(
    product: str | None = typer.Option(None, "--product", "-p"),
    list_angles: bool = typer.Option(False, "--list", help="Liste les angles disponibles."),
    explain_scores: bool = typer.Option(
        False, "--explain", help="Détaille le calcul et la décision pour chaque angle."
    ),
    reactivate: str | None = typer.Option(
        None, "--reactivate", help="Réactive un angle en pause (tous les produits sans -p)."
    ),
    pause: str | None = typer.Option(
        None, "--pause", help="Met un angle en pause à la main (tous les produits sans -p)."
    ),
):
    """Classe les angles par score (vues normalisées par plateforme et par âge, lissées) et
    montre lesquels sont privilégiés, à explorer ou en pause."""
    if list_angles:
        for slug, desc in ANGLES.items():
            console.print(f"  {slug:<20} {desc}")
        return
    s = _settings()
    if product and product not in PRODUCTS:
        raise ValueError(f"produit inconnu : {product} (choix : {', '.join(PRODUCTS)})")
    if reactivate or pause:
        conn = _db(s)
        angle = _target_angle(reactivate or pause)
        status = "active" if reactivate else "paused"
        reason = "réactivé à la main" if reactivate else "mis en pause à la main"
        counts = {(a.product, a.angle): a.n for a in angle_scores(conn, product)}
        for prod in [product] if product else list(PRODUCTS):
            set_angle_status(
                conn, prod, angle, status, reason, "manual", n=counts.get((prod, angle), 0)
            )
            console.print(f"{prod}/{angle} : {reason}.")
        return
    conn = _db(s)
    rows = angle_ranking(conn, product)
    scores = angle_scores(conn, product, prior_weight=s.angle_prior_weight)
    raw = {(r["product"], r["angle"]): r for r in rows}
    table = Table(title="Angles par performance")
    for col in ("Produit", "Angle", "Contenus", "Vues moy.", "CTR moy.", "Score", "Statut"):
        table.add_column(
            col,
            justify="right" if col in ("Contenus", "Vues moy.", "CTR moy.", "Score") else "left",
        )
    for a in scores:
        r = raw.get((a.product, a.angle))
        table.add_row(
            a.product,
            a.angle,
            str(a.n),
            f"{a.views_avg:.0f}" if a.n else "-",
            f"{r['ctr_avg']:.1f}" if r and r["ctr_avg"] is not None else "-",
            f"×{a.ratio:.2f} ({a.score:+.2f})" if a.n else "-",
            status_label(a),
        )
    console.print(table)
    if explain_scores:
        for a in scores:
            console.print(f"[bold]{a.product}/{a.angle}[/bold] — {status_label(a)}")
            for line in explain(
                a,
                prior_weight=s.angle_prior_weight,
                min_contents=s.angle_pause_min_contents,
                pause_ratio=s.angle_pause_ratio,
            ):
                console.print(f"  · {line}")
    if rows:
        # un angle mesuré sur un ou deux contenus ne dit rien : on ne conclut qu'au-delà du seuil
        reliable = [a for a in scores if a.n >= MIN_CONTENTS_PER_ANGLE]
        if reliable:
            best, worst = reliable[0], reliable[-1]
            msg = f"À décliner : {best.product}/{best.angle}"
            if len(reliable) > 1:
                msg += f" · à revoir : {worst.product}/{worst.angle}"
            console.print(msg)
        else:
            console.print(
                f"Trop peu de données : au moins {MIN_CONTENTS_PER_ANGLE} contenus mesurés par "
                "angle avant de conclure."
            )
        paused = [f"{a.product}/{a.angle}" for a in scores if a.status == "paused"]
        if paused:
            console.print(
                "En pause : " + ", ".join(paused) + " · `ce angles --reactivate ANGLE -p PRODUIT`"
            )
        console.print(
            f"Sélection dans `ce run-daily` : {1 - s.angle_exploration_rate:.0%} des sujets sur "
            f"les angles privilégiés, {s.angle_exploration_rate:.0%} en exploration "
            "(ANGLE_EXPLORATION_RATE)."
        )
    else:
        console.print(
            "Pas encore de métriques liées : `ce metrics --pull` (publications réelles) ou "
            "`ce metrics --import export.csv` après publication."
        )
    n = unlinked_count(conn)
    if n:
        console.print(
            f"[dim]{n} ligne(s) de métriques sans brouillon associé (titre différent).[/dim]"
        )


# ----------------------------------------------------------------------------------------------
# Diagnostic
# ----------------------------------------------------------------------------------------------
@app.command()
@guard
def doctor():
    """Vérifie ffmpeg, la police, la voix, le LLM et les clés configurées."""
    s = _settings()
    ok, ko = "[green]ok[/green]", "[red]absent[/red]"
    ver = ffmpeg_version()
    console.print(f"ffmpeg : {ok + ' ' + ver if ver else ko + ' (brew install ffmpeg)'}")
    console.print(f"ffprobe : {ok if shutil.which('ffprobe') else ko}")
    font = find_font(s.font_path)
    if s.font_path and not Path(s.font_path).expanduser().exists():
        console.print(f"police : [red]FONT_PATH introuvable : {s.font_path}[/red]")
    else:
        console.print(f"police : {font.path or '[yellow]défaut système[/yellow]'} ({font.family})")
    console.print(f"TTS : {s.tts_provider}", end="")
    if s.tts_provider == "say":
        if shutil.which("say"):
            voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
            fr = [line.split()[0] for line in voices.splitlines() if "fr_" in line]
            console.print(f" · voix {s.say_voice} · voix françaises : {', '.join(fr) or 'aucune'}")
        else:
            console.print(" · [red]`say` introuvable (macOS uniquement)[/red]")
    elif s.tts_provider == "elevenlabs":
        console.print(" · clé " + (ok if s.elevenlabs_api_key else ko))
    elif s.tts_provider == "kokoro":
        console.print(" · modèle " + (ok if s.kokoro_model_path.exists() else ko))
    else:
        console.print()
    model = {"ollama": s.ollama_model, "anthropic": s.anthropic_model}.get(
        s.llm_provider, "simulateur"
    )
    console.print(f"LLM : {s.llm_provider} ({model})")
    keys = {
        "YouTube (secrets OAuth)": Path(s.youtube_client_secrets_file).exists(),
        "YouTube (jeton)": Path(s.youtube_token_file).exists(),
        "Pinterest": bool(s.pinterest_access_token and s.pinterest_board_id),
        "LinkedIn": bool(s.linkedin_access_token and s.linkedin_author_urn),
        "TikTok": bool(s.tiktok_access_token),
    }
    for name, present in keys.items():
        console.print(f"clé {name} : {ok if present else '[yellow]manquante (dry-run)[/yellow]'}")
    scopes = token_scopes(s)
    if scopes:
        console.print(
            "YouTube (portées du jeton) : "
            + (
                "lecture " + ok
                if READONLY_SCOPE in scopes
                else "[yellow]sans youtube.readonly "
                "(métriques impossibles : refaire le consentement)[/yellow]"
            )
            + " · analytics "
            + (ok if ANALYTICS_SCOPE in scopes else "[yellow]absente (rétention ignorée)[/yellow]")
        )
    audit = "app auditée" if s.tiktok_app_audited else "app non auditée : SELF_ONLY forcé"
    console.print(f"TikTok : visibilité {s.tiktok_effective_privacy} ({audit})")
    console.print(f"YouTube : visibilité {s.youtube_privacy_status}")
    conn = _db(s)
    console.print(
        f"base : {s.db_path} · sujets new : {count_topics(conn)} · "
        f"brouillons : {len(list_drafts(conn))} · sortie : {s.out_dir} · "
        f"heure locale : {local_now(s).strftime('%H:%M')} ({s.timezone})"
    )
    last = last_measurement(conn)
    console.print(
        "métriques : dernier relevé API "
        + (last[:16].replace("T", " ") + " UTC" if last else "[yellow]aucun[/yellow]")
        + f" · angles : exploration {s.angle_exploration_rate:.0%}, pause après "
        f"{s.angle_pause_min_contents} contenus sous {s.angle_pause_ratio:.0%} de la médiane"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
