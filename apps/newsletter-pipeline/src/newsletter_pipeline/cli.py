"""CLI `np` : collect, rank, draft, render, push, linkedin, stats, sources, run-monday."""
from __future__ import annotations

import logging
import sys
from datetime import date

import typer
from core.llm import get_llm

from . import db
from .collect import Collector, CollectReport
from .draft import Drafter, next_tuesday
from .linkedin import generate_linkedin_posts
from .push import TARGETS, PushError, prepare_issue, push_issue
from .rank import Ranker
from .settings import Settings, get_settings
from .stats import collect_stats, format_stats

app = typer.Typer(
    help="Pipeline de la newsletter « l'IA en cabinet » : sources → items → classement → numéro → push.",
    no_args_is_help=True, add_completion=False,
)
log = logging.getLogger("newsletter_pipeline")


def _fail(message: str, code: int = 1) -> None:
    typer.echo(f"Erreur : {message}", err=True)
    raise typer.Exit(code=code)


def _settings() -> Settings:
    return get_settings()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"date invalide : {value!r} (attendu AAAA-MM-JJ)")
    return None


def _print_collect_report(report: CollectReport) -> None:
    prefix = "[dry-run] " if report.dry_run else ""
    for s in report.sources:
        if s.error:
            typer.echo(f"{prefix}{s.name:<40} ERREUR  {s.error[:120]}")
        else:
            typer.echo(f"{prefix}{s.name:<40} {s.inserted:>3} nouveaux / {s.seen:>3} vus "
                       f"({s.duplicates} doublons)")
            if report.dry_run:
                for title in s.titles[:5]:
                    typer.echo(f"{prefix}    + {title[:90]}")
    typer.echo(f"{prefix}Total : {report.inserted} nouveaux items, {len(report.errors)} source(s) en erreur.")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Journal détaillé.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s", stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)


@app.command()
def sources(
    sync: bool = typer.Option(True, "--sync/--no-sync", help="Synchronise sources.yaml avant d'afficher."),
) -> None:
    """Liste les sources (et synchronise sources.yaml dans la base)."""
    settings = _settings()
    conn = db.open_db(settings)
    if sync:
        try:
            stats = Collector(conn, settings).sync_from_yaml()
        except (FileNotFoundError, ValueError) as exc:
            _fail(str(exc))
        typer.echo(f"sources.yaml : {stats['total']} sources ({stats['inserted']} ajoutées, "
                   f"{stats['updated']} mises à jour, {stats['deactivated']} désactivées)")
    for s in db.list_sources(conn):
        flags = ("" if s["active"] else " inactive") + (" à-vérifier" if s["verify"] else "")
        err = f"  ERREUR : {s['last_error'][:60]}" if s["last_error"] else ""
        typer.echo(f"{s['category']:<14} {s['kind']:<4} {s['weight']:<4} {s['name']:<40}{flags}{err}")


@app.command()
def collect(
    source: str | None = typer.Option(None, "--source", help="Nom exact d'une source (sinon toutes les actives)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Lit les sources sans rien écrire en base."),
) -> None:
    """Collecte les flux RSS/Atom et les pages, dédoublonne, stocke les items."""
    settings = _settings()
    conn = db.open_db(settings)
    collector = Collector(conn, settings)
    try:
        collector.sync_from_yaml()
        report = collector.run(source, dry_run=dry_run)
    except (FileNotFoundError, ValueError, LookupError) as exc:
        _fail(str(exc))
    _print_collect_report(report)


LIMIT_HELP = "Nombre max d'items à classer (défaut : RANK_DEFAULT_LIMIT)."


@app.command()
def rank(limit: int | None = typer.Option(None, "--limit", help=LIMIT_HELP)) -> None:
    """Classe les items nouveaux avec le LLM (pertinence cabinet, nouveauté, actionnable, thème)."""
    settings = _settings()
    conn = db.open_db(settings)
    report = Ranker(conn, settings, get_llm(settings)).run(limit)
    typer.echo(f"Classement : {report.scored} items notés en {report.batches} lot(s) "
               f"({report.failed_batches} lot(s) en échec, {report.missing} item(s) sans réponse).")


@app.command()
def draft(
    issue: int = typer.Option(..., "--issue", help="Numéro du numéro (ex. 1)."),
    date_: str | None = typer.Option(None, "--date", help="Date d'envoi AAAA-MM-JJ (défaut : mardi suivant)."),
    case: str | None = typer.Option(None, "--case", help="Slug d'un cas d'usage à imposer (voir cases/)."),
    force: bool = typer.Option(False, "--force", help="Regénère un numéro existant."),
) -> None:
    """Sélectionne les 8 meilleurs items et génère le brouillon (markdown + HTML + texte)."""
    settings = _settings()
    conn = db.open_db(settings)
    try:
        result = Drafter(conn, settings, get_llm(settings)).run(issue, _parse_date(date_), force_case=case, force=force)
    except (FileExistsError, RuntimeError, LookupError, OSError, ValueError) as exc:
        _fail(str(exc))
    typer.echo(f"Numéro {result.number:03d} du {result.issue_date.isoformat()} : « {result.title} »")
    typer.echo(f"  items sélectionnés : {len(result.item_ids)}, cités : {len(result.used_item_ids)}, "
               f"cas d'usage : {result.case_slug}")
    for k, p in result.paths.items():
        typer.echo(f"  {k:<4} {p}")
    for w in result.warnings:
        typer.echo(f"  attention : {w}")
    typer.echo("Relis le markdown (édito marqué [À RELIRE]), puis `np render` ou `np push`.")


@app.command()
def render(issue: int = typer.Option(..., "--issue")) -> None:
    """Régénère le HTML et le texte depuis le markdown relu (titre et aperçu compris)."""
    settings = _settings()
    conn = db.open_db(settings)
    try:
        _, meta, paths = prepare_issue(conn, settings, issue, render=True)
    except PushError as exc:
        _fail(str(exc))
    typer.echo(f"Numéro {issue:03d} : « {meta['title']} »")
    for k, p in paths.items():
        typer.echo(f"  {k:<4} {p}")


@app.command()
def push(
    issue: int = typer.Option(..., "--issue"),
    target: str = typer.Option("beehiiv", "--target", help="beehiiv | kessel | file"),
    live: bool = typer.Option(False, "--live", help="Envoie réellement (défaut : dry-run)."),
) -> None:
    """Pousse le numéro vers la plateforme (dry-run par défaut : écrit la requête dans out/)."""
    settings = _settings()
    conn = db.open_db(settings)
    if target not in TARGETS:
        _fail(f"cible inconnue : {target!r} (attendu : {', '.join(TARGETS)})")
    try:
        result = push_issue(conn, settings, issue, target, live=live)
    except PushError as exc:
        _fail(str(exc))
    for m in result.messages:
        typer.echo(m)


@app.command()
def linkedin(issue: int = typer.Option(..., "--issue")) -> None:
    """Extrait 3 posts LinkedIn du numéro dans out/linkedin-NNN.md."""
    settings = _settings()
    conn = db.open_db(settings)
    try:
        result = generate_linkedin_posts(conn, settings, get_llm(settings), issue)
    except (LookupError, RuntimeError, OSError) as exc:
        _fail(str(exc))
    typer.echo(f"{len(result.posts)} posts écrits dans {result.path}")
    for w in result.warnings:
        typer.echo(f"  attention : {w}")


@app.command()
def stats() -> None:
    """Items collectés par source, taux de sélection, numéros produits."""
    settings = _settings()
    conn = db.open_db(settings)
    typer.echo(format_stats(collect_stats(conn)))


@app.command("run-monday")
def run_monday(
    issue: int | None = typer.Option(None, "--issue", help="Numéro à produire (défaut : dernier + 1)."),
    date_: str | None = typer.Option(None, "--date", help="Date d'envoi (défaut : mardi suivant)."),
    limit: int | None = typer.Option(None, "--limit", help=LIMIT_HELP),
) -> None:
    """Routine du lundi : collecte de toutes les sources actives → classement → brouillon du prochain numéro."""
    settings = _settings()
    conn = db.open_db(settings)
    llm = get_llm(settings)
    collected, source_errors, ranked = 0, 0, 0

    try:
        collector = Collector(conn, settings)
        collector.sync_from_yaml()
        report = collector.run()
        _print_collect_report(report)
        collected, source_errors = report.inserted, len(report.errors)
    except Exception as exc:  # noqa: BLE001 - on continue avec les items déjà en base
        log.error("collecte en échec : %s", exc)
        typer.echo(f"Collecte en échec : {exc}", err=True)

    try:
        rank_report = Ranker(conn, settings, llm).run(limit)
        ranked = rank_report.scored
        typer.echo(f"Classement : {ranked} items notés ({rank_report.failed_batches} lot(s) en échec).")
    except Exception as exc:  # noqa: BLE001
        log.error("classement en échec : %s", exc)
        typer.echo(f"Classement en échec : {exc}", err=True)

    number = issue or db.last_issue_number(conn) + 1
    issue_date = _parse_date(date_) or next_tuesday()
    try:
        result = Drafter(conn, settings, llm).run(number, issue_date)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Compte rendu : {collected} items collectés ({source_errors} source(s) en erreur), "
                   f"{ranked} items classés, brouillon : ÉCHEC ({exc})", err=True)
        raise typer.Exit(code=1) from None
    for w in result.warnings:
        typer.echo(f"  attention : {w}")
    typer.echo(f"Compte rendu : {collected} items collectés ({source_errors} source(s) en erreur), "
               f"{ranked} items classés, brouillon : {result.paths['md']} "
               f"(n° {number:03d} du {issue_date.isoformat()}, « {result.title} »)")


if __name__ == "__main__":  # pragma: no cover
    app()
