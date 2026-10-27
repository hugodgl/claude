"""Facturation hors HTTP : liens signés, formulaires, migration, synchronisation Stripe, CLI (web, sync, link)."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import stripe
from core.db import migrate
from typer.testing import CliRunner

from veille_marches import cli, db
from veille_marches.accounts import TokenError, make_account_token, read_account_token
from veille_marches.billing import MockStripeGateway, StripeGateway, get_gateway, sync_subscriptions
from veille_marches.catalog import PLANS, next_digest_at, next_weekly_brief_at, trade_for_prefixes
from veille_marches.forms import parse_account, parse_amount, parse_cpv_prefixes, parse_departments
from veille_marches.models import Subscriber

runner = CliRunner()


def test_account_tokens_roundtrip_expiry_and_tampering(settings, now):
    s = settings.model_copy(update={"app_secret_key": "k1"})
    token = make_account_token(s, 42, now=now)
    assert token.startswith("42.") and read_account_token(s, token, now=now) == 42
    assert read_account_token(s, token, now=now + timedelta(days=6, hours=23)) == 42
    with pytest.raises(TokenError) as e:
        read_account_token(s, token, now=now + timedelta(days=7, seconds=1))
    assert e.value.expired
    for bad in (None, "", "42", "42.1.2.3", token[:-1] + ("A" if token[-1] != "A" else "B"), "43." + token[3:]):
        with pytest.raises(TokenError) as e:
            read_account_token(s, bad, now=now)
        assert not e.value.expired
    with pytest.raises(TokenError):
        read_account_token(settings.model_copy(update={"app_secret_key": "k2"}), token, now=now)
    # sans APP_SECRET_KEY : clé aléatoire par processus, mais stable dans le processus
    anon = settings.model_copy(update={"app_secret_key": None})
    assert read_account_token(anon, make_account_token(anon, 7, now=now), now=now) == 7


def test_form_parsers():
    assert parse_amount("500 000 € HT") == (500000.0, None) and parse_amount("500k") == (500000.0, None)
    assert parse_amount("1,2M") == (1200000.0, None) and parse_amount("") == (None, None)
    assert parse_amount("abc")[1] and parse_amount("-5")[1]
    assert parse_cpv_prefixes("773, 45112700-2 ; 90") == (["773", "45112700", "90"], None)
    assert parse_cpv_prefixes("7")[1] and parse_cpv_prefixes("773x")[1]
    assert parse_departments(["69", "1", "69", "2a", "999"], PLANS["pro"]) == (["69", "01", "2A"], None)
    assert "au moins un département" in parse_departments([], PLANS["essentiel"])[1]
    assert "2 départements au maximum" in parse_departments(["69", "01", "38"], PLANS["essentiel"])[1]
    f = parse_account({"trade": "autre", "cpv_extra": "45261", "departments": "69", "amount_max": "50k"}, PLANS["pro"])
    assert f.valid and f.cpv_prefixes == ["45261"] and f.departments == ["69"] and f.amount_max == 50000.0
    assert trade_for_prefixes(["773", "45"]).code == "espaces_verts" and trade_for_prefixes(["99"]) is None


def test_schedule_helpers():
    early = datetime(2026, 10, 27, 3, 30, tzinfo=UTC)      # 04:30 Paris → digest du jour même
    late = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    assert next_digest_at(early).isoformat() == "2026-10-27T07:00:00+01:00"
    assert next_digest_at(late).isoformat() == "2026-10-28T07:00:00+01:00"
    assert next_weekly_brief_at(late).isoformat() == "2026-11-01T18:00:00+01:00"
    sunday_evening = datetime(2026, 11, 1, 18, 30, tzinfo=UTC)
    assert next_weekly_brief_at(sunday_evening).isoformat() == "2026-11-08T18:00:00+01:00"


def test_migration_keeps_existing_subscribers(tmp_path: Path):
    """Base créée avec la seule migration 001 (abonnés CLI) : la 002 ajoute les colonnes sans perdre les états."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((db.MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_migrations VALUES ('001_init.sql', 'x')")
    conn.execute("INSERT INTO subscribers (email, label, cpv_prefixes, departments, plan, active, created_at)"
                 " VALUES ('a@b.fr', 'A', '[\"773\"]', '[\"69\"]', 'pro', 1, 'x'),"
                 " ('off@b.fr', NULL, '[]', '[]', 'essentiel', 0, 'x')")
    conn.commit()
    assert migrate(conn, db.MIGRATIONS_DIR) == ["002_billing.sql"]
    subs = {s.email: s for s in db.list_subscribers(conn)}
    assert subs["a@b.fr"].status == "active" and subs["a@b.fr"].active and subs["a@b.fr"].billing_period == "monthly"
    assert subs["off@b.fr"].status == "disabled" and not subs["off@b.fr"].active
    assert db.set_subscriber_active(conn, "off@b.fr", True)
    assert db.get_subscriber_by_email(conn, "off@b.fr").status == "active"
    assert db.record_stripe_event(conn, "evt_1", "x") and not db.record_stripe_event(conn, "evt_1", "x")
    with pytest.raises(ValueError):
        db.update_subscriber(conn, 1, email="nouveau@b.fr")
    conn.close()


def test_gateway_selection_and_mock(settings):
    assert isinstance(get_gateway(settings), MockStripeGateway) and settings.stripe_mode == "mock"
    live = settings.model_copy(update={"stripe_secret_key": "sk_test_x"})
    assert isinstance(get_gateway(live), StripeGateway) and live.stripe_mode == "live"
    assert live.plan_for_price("price_x") is None
    live = live.model_copy(update={"stripe_price_pro_yearly": "price_x"})
    assert live.plan_for_price("price_x") == ("pro", "yearly")


def test_sync_subscriptions_live_and_mock(conn, settings, monkeypatch):
    live = settings.model_copy(update={"stripe_secret_key": "sk_test_x", "stripe_price_essentiel_monthly": "p_em",
                                       "stripe_price_pro_monthly": "p_pm"})
    db.add_subscriber(conn, Subscriber(email="ok@b.fr", cpv_prefixes=["773"], stripe_subscription_id="sub_ok",
                                       stripe_customer_id="cus_ok"))
    db.add_subscriber(conn, Subscriber(email="parti@b.fr", cpv_prefixes=["773"], stripe_subscription_id="sub_gone",
                                       stripe_customer_id="cus_gone"))
    db.add_subscriber(conn, Subscriber(email="manuel@b.fr", cpv_prefixes=["773"]))
    remote = {"sub_ok": {"id": "sub_ok", "status": "active", "customer": "cus_ok",
                         "items": {"data": [{"price": {"id": "p_pm"}}]}},
              "sub_gone": {"id": "sub_gone", "status": "canceled", "customer": "cus_gone"}}
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sid, **kw: remote[sid])
    results = sync_subscriptions(conn, live, get_gateway(live), dry_run=True)
    assert [(r.subscriber.email, r.remote_status, r.before, r.after, r.changed) for r in results] == [
        ("ok@b.fr", "active", "active", "active", False), ("parti@b.fr", "canceled", "active", "canceled", True)]
    assert db.get_subscriber_by_email(conn, "parti@b.fr").active           # dry-run : rien d'écrit
    results = sync_subscriptions(conn, live, get_gateway(live))
    assert results[1].changed and not db.get_subscriber_by_email(conn, "parti@b.fr").active
    assert db.get_subscriber_by_email(conn, "ok@b.fr").plan == "pro"       # prix → formule
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sid, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    results = sync_subscriptions(conn, live, get_gateway(live))
    assert all(r.error == "boom" and not r.changed for r in results)
    # mock : aucun appel, statut local conservé
    results = sync_subscriptions(conn, settings, get_gateway(settings))
    assert [r.changed for r in results] == [False, False] and results[1].after == "canceled"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("LLM_PROVIDER", "MAIL_PROVIDER", "DB_PATH", "OUT_DIR", "DATA_DIR", "STRIPE_SECRET_KEY",
                "APP_SECRET_KEY", "APP_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    return {"DB_PATH": str(tmp_path / "vm.db"), "OUT_DIR": str(tmp_path / "out"), "DATA_DIR": str(tmp_path),
            "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console", "APP_SECRET_KEY": "cle-de-test",
            "APP_BASE_URL": "https://veille.example.fr"}


def run(args, env, code=0):
    result = runner.invoke(cli.app, args, env=env)
    assert result.exit_code == code, result.output
    return result.output


def test_cli_link_sync_stats_and_web(env, monkeypatch):
    run(["subscribers", "add", "contact@paysages69.fr", "--cpv", "773", "--dept", "69"], env)
    out = run(["subscribers", "link", "contact@paysages69.fr", "--days", "3"], env)
    assert out.startswith("https://veille.example.fr/compte?token=1.")
    run(["subscribers", "link", "inconnu@b.fr"], env, code=1)
    assert "aucun abonné lié" in run(["subscribers", "sync-stripe"], env)
    # abonnement Stripe (clé de test) : le SDK est remplacé par un faux
    conn = db.open_db(env["DB_PATH"])
    db.update_subscriber(conn, 1, stripe_subscription_id="sub_1", stripe_customer_id="cus_1")
    conn.close()
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sid, **kw: {"id": sid, "status": "past_due"})
    live_env = {**env, "STRIPE_SECRET_KEY": "sk_test_x"}
    out = run(["subscribers", "sync-stripe", "--dry-run"], live_env)
    assert "Stripe past_due → passerait de active à past_due" in out and "dry-run" in out
    out = run(["subscribers", "sync-stripe"], live_env)
    assert "passe de active à past_due" in out and "mode live : 1 abonnement(s) vérifié(s), 1 modifié(s)" in out
    listed = run(["subscribers", "list"], env)
    assert "état past_due" in listed and "stripe sub_1 (monthly)" in listed
    assert "mode mock : 1 abonnement(s) vérifié(s), 0 modifié(s)" in run(["subscribers", "sync-stripe"], env)
    assert "(0 en attente de paiement) ; événements Stripe : 0" in run(["stats"], env)

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    out = run(["web", "--port", "8123"], env)
    assert "http://127.0.0.1:8123" in out and "Stripe : mock" in out
    assert calls[0][0] == ("veille_marches.web:app",) and calls[0][1]["port"] == 8123
    assert "web" in run(["--help"], env)
