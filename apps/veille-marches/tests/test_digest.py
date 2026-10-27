"""Digest quotidien : sélection, sections, rendu HTML/texte, envoi, deliveries (jamais deux fois le même avis)."""
import json
from datetime import timedelta

from core.llm import MockLLM
from core.mail import ConsoleMailer

from veille_marches import db
from veille_marches.digest import build_digest, render_digest, send_digests
from veille_marches.models import LLMSummary, Notice, Subscriber
from veille_marches.scoring import score_pending

SUMMARY_YES = json.dumps({"resume": "Entretien des espaces verts communaux sur 4 ans.", "lieu": "Villeurbanne (69)",
                          "montant_estime": "180 000 € HT", "date_limite": "28/11/2026",
                          "pieces_a_fournir": ["DC1", "DC2"], "criteres": "Prix 60 %, technique 40 %",
                          "verdict": "oui", "raison": "Marché récurrent accessible à une PME."})
SUMMARY_NO = json.dumps({"resume": "Élagage d'arbres d'alignement, 4 lots.", "lieu": "Lyon", "montant_estime": "1,2 M€",
                         "date_limite": "02/11/2026", "pieces_a_fournir": [], "criteres": "non précisés",
                         "verdict": "non", "raison": "Volume et délai incompatibles avec une petite structure."})


def seed_notices(conn, now):
    rows = [
        Notice(source="boamp", source_id="26-145201", title="Entretien des espaces verts des bâtiments communaux",
               buyer_name="Commune de Villeurbanne", departments=["69"], cpv_codes=["77310000", "77340000"],
               estimated_amount=180000.0, published_at=now - timedelta(days=1), deadline_at=now + timedelta(days=32),
               procedure_type="Procédure adaptée", url="https://www.boamp.fr/pages/avis/?q=idweb:%2226-145201%22",
               description="Accord-cadre d'entretien."),
        Notice(source="boamp", source_id="26-145622", title="Élagage et abattage d'arbres <script>alert(1)</script>",
               buyer_name="Métropole de Lyon", departments=["69"], cpv_codes=["77341000"],
               estimated_amount=1200000.0, published_at=now - timedelta(days=3), deadline_at=now + timedelta(days=6),
               procedure_type="Appel d'offres ouvert", url="https://www.boamp.fr/pages/avis/?q=idweb:%2226-145622%22"),
        Notice(source="ted", source_id="650123-2026", title="Entretien des espaces verts du patrimoine métropolitain",
               buyer_name="Métropole de Lyon", departments=["69"], cpv_codes=["77310000"], estimated_amount=1250000.0,
               published_at=now - timedelta(days=3), deadline_at=now + timedelta(days=34),
               url="https://ted.europa.eu/fr/notice/-/detail/650123-2026"),
        Notice(source="boamp", source_id="26-000001", title="Marché expiré", buyer_name="Commune de Bron",
               departments=["69"], cpv_codes=["77310000"], published_at=now - timedelta(days=5),
               deadline_at=now - timedelta(days=1), url="https://www.boamp.fr/x"),
        Notice(source="boamp", source_id="26-000002", title="Voirie", buyer_name="Commune d'Aubagne",
               departments=["13"], cpv_codes=["45233140"], published_at=now - timedelta(days=1),
               url="https://www.boamp.fr/y"),
    ]
    for n in rows:
        db.upsert_notice(conn, n, now)
    return rows


def test_build_digest_sections_and_zero_email(conn, settings, now):
    sub = db.add_subscriber(conn, Subscriber(email="Contact@Paysages69.fr", label="Paysages 69",
                                             cpv_prefixes=["773"], departments=["69", "01"], amount_max=800000))
    seed_notices(conn, now)
    # 26-145201 → oui ; TED (hors fourchette, 1,25 M€) non scoré par LLM côté abonné ; élagage hors fourchette
    score_pending(conn, settings, llm=MockLLM([SUMMARY_YES, SUMMARY_NO, SUMMARY_NO]), now=now)
    digest = build_digest(conn, sub, settings, now)
    assert digest is not None and digest.total == 1
    item = digest.priority[0]
    assert item.notice.source_id == "26-145201" and item.score >= settings.priority_threshold and item.llm_used
    assert digest.others == []
    # nouvel abonné sans fourchette : au passage suivant, les deux gros marchés (résumés de repli) passent au LLM
    wide = db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", cpv_prefixes=["773"], departments=["69"]))
    llm = MockLLM([SUMMARY_NO, SUMMARY_NO])
    rescored = score_pending(conn, settings, llm=llm, now=now)
    assert sorted(s.notice.source_id for s in rescored) == ["26-145622", "650123-2026"] and len(llm.calls) == 2
    d2 = build_digest(conn, wide, settings, now)
    assert d2.total == 3 and [i.notice.source_id for i in d2.priority] == ["26-145201"]
    assert [i.notice.source_id for i in d2.others] == ["650123-2026", "26-145622"]   # verdict « non » → 63 et 57
    assert [i.score for i in d2.others] == [63, 57] and d2.priority[0].score == 86
    # abonné hors zone : rien → pas d'email
    other = db.add_subscriber(conn, Subscriber(email="nord@b.fr", cpv_prefixes=["773"], departments=["59"]))
    assert build_digest(conn, other, settings, now) is None


def test_render_digest_html_and_text(conn, settings, now):
    sub = db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", label="Pro EV", cpv_prefixes=["773"],
                                             departments=["69"]))
    seed_notices(conn, now)
    score_pending(conn, settings, llm=MockLLM([SUMMARY_YES, SUMMARY_NO, SUMMARY_NO]), now=now)
    digest = build_digest(conn, sub, settings, now)
    subject, html, text = render_digest(digest, settings)
    assert subject.startswith("Veille marchés 27/10/2026 : 3 nouveau(x) marché(s), 1 à regarder en priorité")
    assert "À regarder en priorité" in html and "Autres marchés" in html
    assert "Entretien des espaces verts des bâtiments communaux" in html
    assert 'href="https://www.boamp.fr/pages/avis/?q=idweb:%2226-145201%22"' in html
    assert 'href="https://ted.europa.eu/fr/notice/-/detail/650123-2026"' in html
    assert "Voir l'avis original" in html and "Résumé assisté par IA" in html
    assert "vérifiez toujours l'avis original" in html
    assert "DC1" in html and "Prix 60 %" in html and "Marché récurrent" in html
    assert "<script>" not in html and "&lt;script&gt;" in html           # autoescape
    assert "montant non précisé" not in html.split("Autres marchés")[0]   # pas de fausse mention sur l'avis prioritaire
    assert "Bonjour Pro EV" in html and "départements 69" in html
    assert "== À REGARDER EN PRIORITÉ" in text and "== AUTRES MARCHÉS ==" in text
    assert "Avis original : https://www.boamp.fr/pages/avis/?q=idweb:%2226-145201%22" in text
    assert "Résumé assisté par IA" in text and "délai court" in text


def test_send_digests_records_deliveries_and_never_resends(conn, settings, now):
    db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", cpv_prefixes=["773"], departments=["69"]))
    db.add_subscriber(conn, Subscriber(email="off@b.fr", cpv_prefixes=["773"], departments=["69"], active=False))
    seed_notices(conn, now)
    score_pending(conn, settings, llm=MockLLM([SUMMARY_YES, SUMMARY_NO, SUMMARY_NO]), now=now)
    mailer = ConsoleMailer(quiet=True)
    # dry-run : rien d'envoyé, rien d'écrit
    outcomes = send_digests(conn, settings, mailer, dry_run=True, now=now)
    assert len(outcomes) == 1 and not outcomes[0].sent and not outcomes[0].files and mailer.sent == []
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 0
    # aperçu : fichiers écrits, pas de deliveries
    outcomes = send_digests(conn, settings, mailer, now=now)
    assert outcomes[0].files and outcomes[0].files[0].exists() and outcomes[0].files[0].suffix == ".html"
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 0
    # envoi réel (console) : email + deliveries
    outcomes = send_digests(conn, settings, mailer, send=True, now=now)
    assert len(outcomes) == 1 and outcomes[0].sent and outcomes[0].message_id == "console-1"
    email = mailer.sent[0]
    assert email.to == ["pro@espaces-verts.fr"] and email.reply_to == "hugo@example.com" and email.text
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 3
    # second envoi : rien de nouveau → zéro email
    assert send_digests(conn, settings, mailer, send=True, now=now + timedelta(hours=1)) == []
    assert len(mailer.sent) == 1
    # un nouvel avis arrive : seul lui part
    db.upsert_notice(conn, Notice(source="boamp", source_id="26-777", title="Fleurissement estival",
                                  buyer_name="Commune de Vaulx-en-Velin", departments=["69"], cpv_codes=["77310000"],
                                  published_at=now, deadline_at=now + timedelta(days=20), url="https://www.boamp.fr/z"),
                     now)
    score_pending(conn, settings, llm=MockLLM(SUMMARY_YES), now=now)
    outcomes = send_digests(conn, settings, mailer, send=True, subscriber_email="PRO@espaces-verts.fr", now=now)
    assert len(outcomes) == 1 and outcomes[0].digest.total == 1
    assert outcomes[0].digest.items[0].notice.source_id == "26-777"
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 4


def test_digest_without_llm_summary_uses_fallback(conn, settings, now):
    sub = db.add_subscriber(conn, Subscriber(email="pro@espaces-verts.fr", cpv_prefixes=["773"], departments=["69"]))
    seed_notices(conn, now)
    score_pending(conn, settings.model_copy(update={"llm_enabled": False}), now=now)
    digest = build_digest(conn, sub, settings, now)
    assert digest is not None and all(not i.llm_used for i in digest.items)
    _, html, text = render_digest(digest, settings)
    assert "Avis de l'assistant" not in html and "Avis de l'assistant" not in text
    assert isinstance(digest.items[0].summary, LLMSummary)
