"""Brief hebdo DECP : agrégats par zone, acheteurs actifs, titulaires récurrents, envoi aux abonnés Pro."""
from conftest import load_fixture
from core.mail import ConsoleMailer

from veille_marches import db
from veille_marches.brief import build_brief, render_brief, send_briefs
from veille_marches.collectors.decp import map_decp_record
from veille_marches.models import Subscriber


def seed_awards(conn, now):
    for row in load_fixture("decp_records.json")["results"]:
        db.upsert_award(conn, map_decp_record(row), now)


def test_build_brief_for_zone(conn, settings, now):
    seed_awards(conn, now)
    sub = Subscriber(id=1, email="pro@b.fr", plan="pro", cpv_prefixes=["773"], departments=["69", "01"])
    brief = build_brief(conn, sub, settings, since_days=7, now=now)
    assert brief is not None and brief.count == 3
    assert sorted(brief.by_dept) == ["01", "69"] and len(brief.by_dept["69"]) == 2
    assert brief.total_amount == 92000 + 240000 + 410000 and brief.with_amount == 3
    names = [c.name for c in brief.recurring_holders]
    assert names == ["Parcs et Jardins du Rhône SARL"] and brief.recurring_holders[0].count == 2
    buyers = {c.name: c for c in brief.top_buyers}
    assert buyers["Commune de Vénissieux"].count == 2 and buyers["Commune de Vénissieux"].recent == 1
    assert "Ville de Marseille" not in buyers
    # zone sans attribution récente → pas de brief
    assert build_brief(conn, Subscriber(id=2, email="x@b.fr", cpv_prefixes=["773"], departments=["59"]),
                       settings, now=now) is None


def test_render_brief(conn, settings, now):
    seed_awards(conn, now)
    sub = Subscriber(id=1, email="pro@b.fr", label="Pro", plan="pro", cpv_prefixes=["773"], departments=["69", "01"])
    brief = build_brief(conn, sub, settings, now=now)
    subject, html, text = render_brief(brief, settings)
    assert subject == "Veille marchés — brief de la semaine : 3 attribution(s) du 20/10 au 27/10/2026"
    assert "Département 69" in html and "Département 01" in html
    assert "Parcs et Jardins du Rhône SARL" in html and "Paysages Bressans" in html
    assert "Titulaires récurrents" in html and "Acheteurs actifs" in html and "410 k€ HT" in html
    assert "== TITULAIRES RÉCURRENTS" in text and "Commune de Vénissieux : 2 marché(s), 1 cette semaine" in text
    assert "data.economie.gouv.fr" in html


def test_send_briefs_pro_only(conn, settings, now):
    seed_awards(conn, now)
    db.add_subscriber(conn, Subscriber(email="pro@b.fr", plan="pro", cpv_prefixes=["773"], departments=["69"]))
    db.add_subscriber(conn, Subscriber(email="ess@b.fr", plan="essentiel", cpv_prefixes=["773"], departments=["69"]))
    mailer = ConsoleMailer(quiet=True)
    outcomes = send_briefs(conn, settings, mailer, send=True, now=now)
    assert [o.brief.subscriber.email for o in outcomes] == ["pro@b.fr"] and outcomes[0].sent
    assert mailer.sent[0].to == ["pro@b.fr"] and "brief de la semaine" in mailer.sent[0].subject
    outcomes = send_briefs(conn, settings, mailer, dry_run=True, all_plans=True, now=now)
    assert len(outcomes) == 2 and not any(o.sent for o in outcomes) and len(mailer.sent) == 1
    outcomes = send_briefs(conn, settings, None, now=now)
    assert outcomes[0].files and outcomes[0].files[1].suffix == ".txt"
