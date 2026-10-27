"""CLI `ce` : banque de sujets, scripts, relecture, rendu, publication, planification, métriques."""

from __future__ import annotations

import functools
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

import typer
from core.llm import LLMError
from rich.console import Console
from rich.table import Table

from . import __version__
from .db import open_db
from .llm import get_engine_llm
from .metrics import angle_ranking, import_csv, unlinked_count
from .planning import build_plan, list_schedule, local_now, run_daily, run_publish, save_plan
from .products import ANGLES, PRODUCTS
from .publish import PLATFORMS, PublishError, publish_draft
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
ERRORS = (ValueError, LookupError, LLMError, RenderError, PublishError, TTSError, FileNotFoundError)


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
        "Statuts : " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "aucun"
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
        ..., "--reason", "-r", help="Motif court (nourrit les prochains scripts)."
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
    for did in ids:
        res = render_draft(conn, did, s, force=force)
        files = ", ".join(f for f in (res.video, res.cover, res.thumb, res.text_file) if f)
        dur = f" · {res.duration_s:.1f} s" if res.video else ""
        console.print(f"#{did} rendu ({res.format}) → {res.out_dir}/ [{files}]{dur}")


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
    for product, n in rep["ideas"].items():
        console.print(f"Idées : {n} nouveau(x) sujet(s) pour {product}")
    for item in rep["scripts"]:
        console.print(
            f"Scripts : sujet #{item['topic_id']} ({item['format']}) → "
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
    import_file: Path = typer.Option(
        ..., "--import", exists=True, dir_okay=False, help="Export CSV YouTube Studio ou TikTok."
    ),
    platform: str | None = typer.Option(
        None, "--platform", help="youtube | tiktok (détection auto sinon)"
    ),
):
    """Importe un export CSV de métriques."""
    conn = _db(_settings())
    rep = import_csv(conn, import_file, platform)
    console.print(
        f"{rep['platform']} : {rep['imported']} ligne(s) importée(s), {rep['linked']} liée(s) "
        f"à un brouillon, {rep['skipped']} ignorée(s). Colonnes : {rep['columns']}"
    )


@app.command()
@guard
def angles(
    product: str | None = typer.Option(None, "--product", "-p"),
    list_angles: bool = typer.Option(False, "--list", help="Liste les angles disponibles."),
):
    """Classe les angles par performance (vues moyennes)."""
    if list_angles:
        for slug, desc in ANGLES.items():
            console.print(f"  {slug:<20} {desc}")
        return
    conn = _db(_settings())
    rows = angle_ranking(conn, product)
    table = Table(title="Angles par performance")
    for col in (
        "Produit",
        "Angle",
        "Contenus",
        "Vues moy.",
        "Vues total",
        "CTR moy.",
        "Vision. moy. %",
    ):
        table.add_column(col, justify="right" if col not in ("Produit", "Angle") else "left")
    for r in rows:
        table.add_row(
            r["product"],
            r["angle"],
            str(r["n"]),
            f"{r['views_avg']:.0f}",
            str(r["views_total"]),
            f"{r['ctr_avg']:.1f}" if r["ctr_avg"] is not None else "-",
            f"{r['view_pct_avg']:.0f}" if r["view_pct_avg"] is not None else "-",
        )
    console.print(table)
    if rows:
        best, worst = rows[0], rows[-1]
        msg = f"À décliner : {best['product']}/{best['angle']}"
        if len(rows) > 1:
            msg += f" · à revoir : {worst['product']}/{worst['angle']}"
        console.print(msg)
    else:
        console.print(
            "Pas encore de métriques liées : `ce metrics --import export.csv` après publication."
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
    conn = _db(s)
    console.print(
        f"base : {s.db_path} · sujets new : {count_topics(conn)} · "
        f"brouillons : {len(list_drafts(conn))} · sortie : {s.out_dir} · "
        f"heure locale : {datetime.now().strftime('%H:%M')} ({s.timezone})"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
