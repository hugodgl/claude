"""CLI `vm` : collecte, score, digest, abonnés, brief hebdo, statistiques."""
from __future__ import annotations

import sqlite3
import sys
from typing import Annotated

import typer
from core.llm import get_llm
from core.mail import get_mailer

from . import __version__, db
from .accounts import account_url
from .billing import get_gateway, sync_subscriptions
from .brief import send_briefs
from .collectors import SOURCES, run_collect
from .dates import fr_amount
from .digest import send_digests
from .models import Subscriber
from .scoring import score_pending
from .settings import VMSettings, get_settings

app = typer.Typer(help="Veille marchés publics : collecte BOAMP / TED / DECP, score, digest quotidien, brief hebdo.",
                  no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)
subscribers_app = typer.Typer(help="Gestion des abonnés.", no_args_is_help=True)
app.add_typer(subscribers_app, name="subscribers")


def _ctx() -> tuple[VMSettings, sqlite3.Connection]:
    settings = get_settings()
    return settings, db.open_db(settings.db_path)


def _echo(msg: str = "") -> None:
    typer.echo(msg)


def _parse_csv_option(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


@app.callback()
def _main() -> None:
    """Sous-commandes : collect, score, digest, subscribers, brief-weekly, stats, web."""


@app.command()
def version() -> None:
    """Affiche la version."""
    _echo(f"veille-marches {__version__}")


@app.command()
def collect(
    source: Annotated[str, typer.Option("--source", help="boamp, ted, decp ou all")] = "all",
    since_days: Annotated[int | None, typer.Option("--since-days", help="Fenêtre de publication en jours")] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Nombre max d'enregistrements par source")] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv", help="Préfixe CPV (répétable ; défaut : abonnés)")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Affiche sans écrire en base")] = False,
) -> None:
    """Collecte les avis (BOAMP, TED) et les attributions (DECP), puis les enregistre."""
    sources = list(SOURCES) if source == "all" else [source]
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        _echo(f"source inconnue : {', '.join(unknown)} (attendu : {', '.join(SOURCES)} ou all)")
        raise typer.Exit(code=2)
    settings, conn = _ctx()
    results = run_collect(conn, settings, sources=sources, since_days=since_days, limit=limit,
                          cpv_prefixes=_parse_csv_option(cpv) or None, dry_run=dry_run)
    failures = 0
    for r in results:
        if r.error:
            failures += 1
            _echo(f"{r.source:6s} ERREUR : {r.error}")
            continue
        verb = "à insérer (dry-run)" if dry_run else "nouveaux"
        new_count = r.kept if dry_run else r.inserted
        _echo(f"{r.source:6s} {r.fetched} reçus, {r.kept} retenus, {new_count} {verb}, {r.excluded} exclus "
              f"({r.requests} requête(s))")
        if dry_run:
            for n in r.notices[:20]:
                _echo(f"   - [{n.source_id}] {n.title[:70]} | {n.buyer_name or '?'} | dép. "
                      f"{','.join(n.all_departments) or '?'} | CPV {','.join(n.cpv_codes) or '?'} | "
                      f"{fr_amount(n.estimated_amount)}")
            for a in r.awards[:20]:
                _echo(f"   - [{a.source_id}] {(a.title or '')[:70]} | {a.buyer_name or '?'} -> {a.holder_label} | "
                      f"dép. {a.dept or '?'} | {fr_amount(a.amount)}")
    if failures and failures == len(results):
        raise typer.Exit(code=1)


@app.command()
def score(
    limit: Annotated[int | None, typer.Option("--limit", help="Nombre max d'avis à traiter")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Calcule sans enregistrer")] = False,
) -> None:
    """Résume (LLM) et score les avis récents qui ne le sont pas encore."""
    settings, conn = _ctx()
    llm = get_llm(settings) if settings.llm_enabled else None
    scored = score_pending(conn, settings, llm=llm, limit=limit, dry_run=dry_run)
    for s in scored:
        tag = "LLM" if s.llm_used else "règles"
        _echo(f"{s.score:3d}/100 ({tag:6s}, règles {s.rules:3d}) {s.notice.source.upper()} {s.notice.source_id} "
              f"{s.notice.title[:60]} | abonnés : {len(s.matched_subscribers)}")
    llm_count = sum(1 for s in scored if s.llm_used)
    suffix = " (dry-run, rien d'enregistré)" if dry_run else ""
    _echo(f"{len(scored)} avis scorés, {llm_count} avec LLM{suffix}")


@app.command()
def digest(
    send: Annotated[bool, typer.Option("--send", help="Envoie les emails et enregistre les envois")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Affiche le texte sans envoyer ni écrire")] = False,
    subscriber: Annotated[str | None, typer.Option("--subscriber", help="Limiter à un email")] = None,
) -> None:
    """Construit le digest quotidien de chaque abonné (zéro email s'il n'y a rien de nouveau)."""
    settings, conn = _ctx()
    mailer = get_mailer(settings) if send else None
    outcomes = send_digests(conn, settings, mailer, subscriber_email=subscriber, send=send, dry_run=dry_run)
    if not outcomes:
        _echo("rien de nouveau : aucun digest à envoyer")
        return
    for o in outcomes:
        d = o.digest
        line = (f"{d.subscriber.email} : {d.total} avis ({len(d.priority)} prioritaires) — {o.subject}")
        if o.sent:
            line += f" — envoyé ({o.message_id})"
        elif o.files:
            line += f" — aperçu : {o.files[0]}"
        _echo(line)
        if dry_run:
            _echo("-" * 72)
            _echo(o.text)
            _echo("-" * 72)


@subscribers_app.command("add")
def subscribers_add(
    email: Annotated[str, typer.Argument(help="Email de l'abonné")],
    label: Annotated[str | None, typer.Option("--label", help="Nom de l'entreprise ou de la personne")] = None,
    cpv: Annotated[list[str] | None, typer.Option("--cpv", help="Préfixe CPV (répétable), ex. 773")] = None,
    dept: Annotated[list[str] | None, typer.Option("--dept", help="Département (répétable), ex. 69")] = None,
    amount_min: Annotated[float | None, typer.Option("--amount-min", help="Montant minimal en € HT")] = None,
    amount_max: Annotated[float | None, typer.Option("--amount-max", help="Montant maximal en € HT")] = None,
    plan: Annotated[str, typer.Option("--plan", help="essentiel ou pro")] = "essentiel",
) -> None:
    """Ajoute un abonné."""
    if plan not in ("essentiel", "pro"):
        _echo("plan invalide : essentiel ou pro")
        raise typer.Exit(code=2)
    settings, conn = _ctx()
    if db.get_subscriber_by_email(conn, email):
        _echo(f"abonné déjà présent : {email}")
        raise typer.Exit(code=1)
    cpv_list = _parse_csv_option(cpv) or settings.default_cpv_prefix_list
    sub = Subscriber(email=email, label=label, cpv_prefixes=cpv_list, departments=_parse_csv_option(dept),
                     amount_min=amount_min, amount_max=amount_max, plan=plan)
    limit = 2 if plan == "essentiel" else 6
    if len(sub.departments) > limit:
        _echo(f"attention : la formule {plan} prévoit {limit} départements maximum ({len(sub.departments)} donnés)")
    saved = db.add_subscriber(conn, sub)
    _echo(f"abonné #{saved.id} ajouté : {saved.email} ({saved.plan}) CPV {','.join(saved.cpv_prefixes) or '-'} "
          f"dép. {','.join(saved.departments) or 'toute la France'}")


@subscribers_app.command("list")
def subscribers_list() -> None:
    """Liste les abonnés."""
    _, conn = _ctx()
    subs = db.list_subscribers(conn)
    if not subs:
        _echo("aucun abonné")
        return
    for s in subs:
        state = "actif" if s.active else "inactif"
        amount = ""
        if s.amount_min is not None or s.amount_max is not None:
            amount = f" montant {s.amount_min or 0:.0f}-{s.amount_max if s.amount_max is not None else '∞'}"
        extra = ""
        if s.status not in ("active", "disabled"):
            extra += f" · état {s.status}"
        if s.stripe_subscription_id:
            extra += f" · stripe {s.stripe_subscription_id} ({s.billing_period})"
        zone = ",".join(s.departments) or "toute la France"
        _echo(f"#{s.id} {s.email} [{s.plan}, {state}] {s.label or s.company or ''} "
              f"CPV {','.join(s.cpv_prefixes) or '-'} dép. {zone}{amount}{extra}")


@subscribers_app.command("disable")
def subscribers_disable(email: Annotated[str, typer.Argument()]) -> None:
    """Désactive un abonné (plus aucun envoi)."""
    _, conn = _ctx()
    if not db.set_subscriber_active(conn, email, False):
        _echo(f"abonné introuvable : {email}")
        raise typer.Exit(code=1)
    _echo(f"abonné désactivé : {email}")


@subscribers_app.command("enable")
def subscribers_enable(email: Annotated[str, typer.Argument()]) -> None:
    """Réactive un abonné."""
    _, conn = _ctx()
    if not db.set_subscriber_active(conn, email, True):
        _echo(f"abonné introuvable : {email}")
        raise typer.Exit(code=1)
    _echo(f"abonné réactivé : {email}")


@subscribers_app.command("sync-stripe")
def subscribers_sync_stripe(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Compare sans modifier la base")] = False,
) -> None:
    """Relit l'état de chaque abonnement chez Stripe et aligne `status` / `active` (filet si un webhook a manqué)."""
    settings, conn = _ctx()
    gateway = get_gateway(settings)
    results = sync_subscriptions(conn, settings, gateway, dry_run=dry_run)
    if not results:
        _echo(f"mode {gateway.mode} : aucun abonné lié à un abonnement Stripe")
        return
    changed = errors = 0
    for r in results:
        if r.error:
            errors += 1
            _echo(f"{r.subscriber.email} : ERREUR {r.error}")
            continue
        if r.changed:
            changed += 1
            verb = "passerait" if dry_run else "passe"
            _echo(f"{r.subscriber.email} : Stripe {r.remote_status} → {verb} de {r.before} à {r.after}")
        else:
            _echo(f"{r.subscriber.email} : Stripe {r.remote_status} → {r.after} (inchangé)")
    suffix = " (dry-run, rien d'écrit)" if dry_run else ""
    _echo(f"mode {gateway.mode} : {len(results)} abonnement(s) vérifié(s), {changed} modifié(s), {errors} erreur(s)"
          f"{suffix}")
    if errors and errors == len(results):
        raise typer.Exit(code=1)


@subscribers_app.command("link")
def subscribers_link(
    email: Annotated[str, typer.Argument(help="Email de l'abonné")],
    days: Annotated[int | None, typer.Option("--days", help="Validité en jours (défaut : ACCOUNT_LINK_DAYS)")] = None,
) -> None:
    """Affiche un lien signé vers l'espace abonné (à envoyer à la main en cas de besoin)."""
    settings, conn = _ctx()
    sub = db.get_subscriber_by_email(conn, email)
    if sub is None:
        _echo(f"abonné introuvable : {email}")
        raise typer.Exit(code=1)
    if days is not None:
        settings = settings.model_copy(update={"account_link_days": days})
    _echo(account_url(settings, sub.id))


@app.command()
def web(
    host: Annotated[str | None, typer.Option("--host", help="Interface d'écoute (défaut : WEB_HOST)")] = None,
    port: Annotated[int | None, typer.Option("--port", help="Port (défaut : WEB_PORT)")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Rechargement automatique (développement)")] = False,
) -> None:
    """Lance le site public, l'espace abonné et le webhook Stripe (uvicorn)."""
    import uvicorn

    settings = get_settings()
    _echo(f"site : http://{host or settings.web_host}:{port or settings.web_port}  (Stripe : {settings.stripe_mode}, "
          f"URL publique : {settings.base_url})")
    uvicorn.run("veille_marches.web:app", host=host or settings.web_host, port=port or settings.web_port,
                reload=reload, proxy_headers=True, forwarded_allow_ips="*", log_level="info")


@app.command("brief-weekly")
def brief_weekly(
    send: Annotated[bool, typer.Option("--send", help="Envoie les emails")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Affiche le texte sans envoyer ni écrire")] = False,
    since_days: Annotated[int, typer.Option("--since-days", help="Période couverte en jours")] = 7,
    subscriber: Annotated[str | None, typer.Option("--subscriber", help="Limiter à un email")] = None,
    all_plans: Annotated[bool, typer.Option("--all-plans", help="Inclure les abonnés Essentiel")] = False,
) -> None:
    """Brief hebdomadaire d'attribution (DECP) pour les abonnés Pro."""
    settings, conn = _ctx()
    mailer = get_mailer(settings) if send else None
    outcomes = send_briefs(conn, settings, mailer, since_days=since_days, send=send, dry_run=dry_run,
                           subscriber_email=subscriber, all_plans=all_plans)
    if not outcomes:
        _echo("aucune attribution sur la période : aucun brief à envoyer")
        return
    for o in outcomes:
        line = f"{o.brief.subscriber.email} : {o.brief.count} attribution(s) — {o.subject}"
        if o.sent:
            line += f" — envoyé ({o.message_id})"
        elif o.files:
            line += f" — aperçu : {o.files[0]}"
        _echo(line)
        if dry_run:
            _echo("-" * 72)
            _echo(o.text)
            _echo("-" * 72)


@app.command()
def stats() -> None:
    """Compteurs : avis, résumés, abonnés, envois, attributions, dernières collectes."""
    settings, conn = _ctx()
    s = db.stats(conn)
    _echo(f"base : {settings.db_path}")
    by_source = ", ".join(f"{k} {v}" for k, v in sorted(s["notices_by_source"].items())) or "aucune"
    _echo(f"avis : {s['notices']} ({by_source}) ; dernier publié : {s['last_published'] or '-'}")
    _echo(f"  sans département : {s['notices_unknown_dept']} ; sans CPV détecté : {s['notices_without_cpv']}"
          " (si élevé : vérifier le mapping, voir README)")
    _echo(f"résumés : {s['summaries']} ; en attente de score : {s['pending_summaries']}")
    _echo(f"abonnés : {s['subscribers_active']} actifs / {s['subscribers_total']} "
          f"({s['subscribers_pending']} en attente de paiement) ; événements Stripe : {s['stripe_events']}")
    _echo(f"envois : {s['deliveries']} ; dernier : {s['last_delivery'] or '-'}")
    _echo(f"attributions DECP : {s['awards']}")
    if s["runs"]:
        _echo("dernières collectes :")
        for r in s["runs"]:
            status = f"ERREUR {r['error']}" if r["error"] else f"{r['fetched']} reçus, {r['inserted']} nouveaux"
            _echo(f"  {r['started_at'][:16]} {r['source']:6s} {status}")


def main() -> None:  # pragma: no cover - point d'entrée alternatif
    app(prog_name="vm")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
