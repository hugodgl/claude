"""Script console `avis` : jobs planifiés (poll-reviews, monthly-report) et administration."""
import json
import logging
from pathlib import Path
from typing import Optional

import typer

from .billing import ACTIVE_STATUSES, VALID_PLANS
from .db import log_event
from .gbp import LiveGBPClient
from .models import Account
from .repo import (
    add_optout,
    create_establishment,
    get_account_by_email,
    get_establishment,
    get_establishment_by_location,
    get_or_create_account,
    list_accounts,
    list_establishments,
    list_events,
    list_optouts,
    review_url_for_place,
    slugify,
    update_account,
    update_establishment,
)
from .reports import send_monthly_reports
from .reviews import poll_reviews
from .services import build_services
from .settings import get_settings
from .sms import DEFAULT_REQUEST_TEMPLATE, normalize_phone
from .tone import default_profile, generate_examples

app = typer.Typer(help="Avis Clients : jobs et administration.", no_args_is_help=True)
accounts_app = typer.Typer(help="Comptes commerçants.", no_args_is_help=True)
google_app = typer.Typer(help="Accès Google Business Profile (mode live).", no_args_is_help=True)
optouts_app = typer.Typer(help="Liste STOP (opposition aux SMS).", no_args_is_help=True)
app.add_typer(accounts_app, name="accounts")
app.add_typer(google_app, name="google")
app.add_typer(optouts_app, name="optouts")


def _services():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    services = build_services(get_settings())
    services.db.migrate()
    return services


def _require_account(conn, email: str) -> Account:
    account = get_account_by_email(conn, email)
    if not account:
        typer.echo(f"Compte introuvable : {email}", err=True)
        raise typer.Exit(code=1)
    return account


@app.command("init-db")
def init_db():
    """Crée la base et applique les migrations."""
    services = _services()
    typer.echo(f"Base prête : {services.settings.resolved_db_path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Lance le serveur web (équivalent : uvicorn avis_clients.web:app)."""
    import uvicorn

    uvicorn.run("avis_clients.web:app", host=host, port=port, reload=reload)


@app.command("poll-reviews")
def poll_reviews_cmd(
    establishment: Optional[list[int]] = typer.Option(None, "--establishment", "-e",
                                                      help="Limiter à ces identifiants d'établissement."),
):
    """Récupère les nouveaux avis, crée les brouillons, alerte sur les avis négatifs (toutes les 15 min)."""
    services = _services()
    with services.db.session() as conn:
        summary = poll_reviews(conn, services, establishment_ids=establishment or None)
    typer.echo(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


@app.command("monthly-report")
def monthly_report_cmd(
    month: Optional[str] = typer.Option(None, help="Mois AAAA-MM (défaut : mois précédent)."),
    account: Optional[str] = typer.Option(None, help="Limiter à un compte (email)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Ne pas envoyer, seulement rendre le HTML."),
    force: bool = typer.Option(False, "--force", help="Ignorer l'éligibilité (formule)."),
    out: Optional[Path] = typer.Option(None, help="Dossier où écrire les fichiers HTML rendus."),
):
    """Envoie le rapport mensuel par établissement (formules Pro et Réseau, comptes en essai)."""
    services = _services()
    with services.db.session() as conn:
        results = send_monthly_reports(conn, services, month=month, account_email=account, dry_run=dry_run,
                                       force=force)
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for r in results:
        if "html" in r and out:
            path = out / f"rapport-{r['month']}-{slugify(r['establishment'])}.html"  # nom de fichier sûr
            path.write_text(r["html"], encoding="utf-8")
            r["file"] = str(path)
        typer.echo(" · ".join(f"{k}={v}" for k, v in r.items() if k != "html"))
    if not results:
        typer.echo("Aucun établissement.")


@app.command("demo")
def demo(email: str = "demo@exemple.fr", name: str = "Boulangerie Dupont"):
    """Crée un compte et un établissement de démonstration, puis lance un poll (mode mock)."""
    services = _services()
    settings = services.settings
    with services.db.session() as conn:
        account, _ = get_or_create_account(conn, email, settings.trial_days)
        existing = [e for e in list_establishments(conn, account.id) if e.name == name]
        if existing:
            est = existing[0]
        else:
            profile = default_profile("chaleureux", name)
            profile["exemples"], _ = generate_examples(services.llm, name, profile)
            est = create_establishment(conn, account_id=account.id, name=name,
                                       google_place_id="ChIJmockboulangeriedupont001",
                                       review_url=review_url_for_place("ChIJmockboulangeriedupont001"),
                                       tone_profile=profile, request_template=DEFAULT_REQUEST_TEMPLATE)
            location = services.gbp.list_locations()
            update_establishment(conn, est.id, google_location_name=location[0]["name"] if location
                                 else f"accounts/mock/locations/{est.slug}")
        summary = poll_reviews(conn, services, establishment_ids=[est.id])
    typer.echo(f"Compte {email} · établissement #{est.id} « {name} » · page /r/{est.slug}")
    typer.echo(f"Poll : {json.dumps(summary.as_dict(), ensure_ascii=False)}")
    typer.echo("Connectez-vous avec cet email : le lien magique s'affiche dans la console (MAIL_PROVIDER=console).")


@app.command("establishments")
def establishments_cmd():
    """Liste les établissements."""
    services = _services()
    with services.db.session() as conn:
        for e in list_establishments(conn):
            typer.echo(f"#{e.id} {e.name} · compte {e.account_id} · /r/{e.slug} · fiche {e.google_location_name or '-'}"
                       f" · auto-publication {'oui' if e.auto_publish else 'non'}")


@app.command("events")
def events_cmd(limit: int = 20):
    """Affiche les derniers événements du journal."""
    services = _services()
    with services.db.session() as conn:
        for ev in list_events(conn, limit=limit):
            typer.echo(f"{ev['created_at']} {ev['kind']} {json.dumps(ev['payload'], ensure_ascii=False)}")


@app.command("sms-test")
def sms_test(phone: str, message: str = "Test d'envoi Avis Clients. Répondre STOP pour ne plus recevoir de message."):
    """Envoie un SMS de test avec le fournisseur configuré (dry-run par défaut)."""
    services = _services()
    normalized = normalize_phone(phone)
    if not normalized:
        typer.echo("Numéro invalide", err=True)
        raise typer.Exit(code=1)
    result = services.sms.send(normalized, message)
    typer.echo(f"{result.provider} : {result.status} (id {result.message_id})")


@accounts_app.command("list")
def accounts_list():
    services = _services()
    with services.db.session() as conn:
        for a in list_accounts(conn):
            typer.echo(f"#{a.id} {a.email} · formule {a.plan} · statut {a.subscription_status or '-'}"
                       f" · essai jusqu'au {a.trial_ends_at[:10]} · créé le {a.created_at[:10]}")


@accounts_app.command("create")
def accounts_create(email: str):
    services = _services()
    with services.db.session() as conn:
        account, created = get_or_create_account(conn, email, services.settings.trial_days)
    typer.echo(f"{'Créé' if created else 'Existant'} : #{account.id} {account.email}")


@accounts_app.command("set-plan")
def accounts_set_plan(email: str, plan: str, status: str = "active"):
    """Force une formule (bêta-testeurs, dépannage) : plan solo|pro|reseau|none."""
    if plan not in (*VALID_PLANS, "none"):
        typer.echo("Formule inconnue", err=True)
        raise typer.Exit(code=1)
    services = _services()
    with services.db.session() as conn:
        account = _require_account(conn, email)
        update_account(conn, account.id, plan=plan,
                       subscription_status=status if plan != "none" else None)
        log_event(conn, "plan_set_manually", account_id=account.id, plan=plan, status=status)
    typer.echo(f"{email} : formule {plan} ({status if plan != 'none' else 'sans abonnement'}) ; "
               f"statuts actifs : {', '.join(sorted(ACTIVE_STATUSES))}")


@accounts_app.command("extend-trial")
def accounts_extend_trial(email: str, days: int = 14):
    from datetime import timedelta

    from .db import utcnow

    services = _services()
    with services.db.session() as conn:
        account = _require_account(conn, email)
        new_end = max(account.trial_end, utcnow()) + timedelta(days=days)
        update_account(conn, account.id, trial_ends_at=new_end.isoformat(timespec="seconds"))
    typer.echo(f"{email} : essai prolongé jusqu'au {new_end.date()}")


@google_app.command("auth")
def google_auth(port: int = 0):
    """Flux OAuth « application de bureau » : ouvre le navigateur, enregistre le jeton."""
    settings = get_settings()
    if not settings.google_oauth_client_secrets_file:
        typer.echo("GOOGLE_OAUTH_CLIENT_SECRETS_FILE manquant dans .env", err=True)
        raise typer.Exit(code=1)
    path = LiveGBPClient.authorize(settings.google_oauth_client_secrets_file, settings.resolved_token_file, port=port)
    typer.echo(f"Jeton enregistré : {path}")


@google_app.command("locations")
def google_locations():
    """Liste les fiches accessibles (nom de ressource, titre, Place ID)."""
    services = _services()
    for loc in services.gbp.list_locations():
        typer.echo(f"{loc.get('name')} · {loc.get('title')} · placeId={loc.get('placeId')}")


@google_app.command("link")
def google_link(establishment_id: int):
    """Relie un établissement à sa fiche Google en faisant correspondre le Place ID."""
    services = _services()
    with services.db.session() as conn:
        est = get_establishment(conn, establishment_id)
        if not est:
            typer.echo("Établissement introuvable", err=True)
            raise typer.Exit(code=1)
        match = next((loc for loc in services.gbp.list_locations()
                      if loc.get("placeId") and loc.get("placeId") == est.google_place_id), None)
        if not match:
            typer.echo("Aucune fiche avec ce Place ID parmi les fiches accessibles (vérifier l'invitation "
                       "en tant que gestionnaire).", err=True)
            raise typer.Exit(code=1)
        other = get_establishment_by_location(conn, match["name"])
        if other and other.id != est.id:
            typer.echo(f"Cette fiche est déjà reliée à l'établissement #{other.id} {other.name} (compte "
                       f"{other.account_id}) : délier d'abord l'autre établissement.", err=True)
            raise typer.Exit(code=1)
        update_establishment(conn, est.id, google_location_name=match["name"])
    typer.echo(f"#{est.id} {est.name} relié à {match['name']} ({match.get('title')})")


@optouts_app.command("add")
def optouts_add(phone: str, account_email: Optional[str] = None):
    services = _services()
    normalized = normalize_phone(phone)
    if not normalized:
        typer.echo("Numéro invalide", err=True)
        raise typer.Exit(code=1)
    with services.db.session() as conn:
        account_id = _require_account(conn, account_email).id if account_email else None
        added = add_optout(conn, normalized, account_id, source="cli")
    scope = f"compte {account_email}" if account_email else "global"
    typer.echo(f"{normalized} : {'ajouté' if added else 'déjà présent'} ({scope})")


@optouts_app.command("list")
def optouts_list():
    services = _services()
    with services.db.session() as conn:
        for row in list_optouts(conn, None):
            typer.echo(f"{row['phone']} · {row['source']} · compte {row['account_id'] or 'global'}"
                       f" · {row['created_at']}")


def main():
    app()


if __name__ == "__main__":
    main()
