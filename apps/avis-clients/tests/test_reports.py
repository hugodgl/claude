from avis_clients.repo import get_account_by_email, update_account
from avis_clients.reports import (
    compute_monthly_stats,
    default_report_month,
    previous_month,
    send_monthly_reports,
    top_words,
)
from avis_clients.reviews import poll_reviews


def test_month_helpers():
    assert previous_month("2026-01") == "2025-12" and previous_month("2026-10") == "2026-09"
    assert len(default_report_month()) == 7
    words = top_words(["Le pain est excellent et le pain est frais", "Excellent accueil"])
    assert words[0] == ("pain", 2) and ("excellent", 2) in words


def test_monthly_report_stats_and_email(logged_client, establishment_id, services):
    with services.db.session() as conn:
        poll_reviews(conn, services)
        conn.execute("UPDATE reviews SET reply_status='published', reply_text='Merci', "
                     "reply_published_at='2026-10-02T21:00:00+00:00' WHERE external_id='r1'")
        conn.commit()
        from avis_clients.repo import get_establishment

        est = get_establishment(conn, establishment_id)
        stats = compute_monthly_stats(conn, est, "2026-10")
    assert stats.count == 5 and stats.avg_rating == 3.6 and stats.prev_count == 0
    assert stats.distribution[5] == 2 and stats.distribution[1] == 1
    assert stats.replied == 2  # r1 (12 h) et r3 (déjà répondu sur Google)
    assert stats.avg_reply_delay_h is not None and 8 < stats.avg_reply_delay_h < 10
    assert any(w == "pain" for w, _ in stats.top_words)

    before = len(services.mailer.sent)
    with services.db.session() as conn:
        results = send_monthly_reports(conn, services, month="2026-10")
    assert results[0]["status"] == "envoyé" and results[0]["reviews"] == 5
    mail = services.mailer.sent[-1]
    assert len(services.mailer.sent) == before + 1
    assert "octobre 2026" in mail.subject and "Boulangerie Test" in mail.subject
    assert "3.6" in mail.html and "Renforcer la caisse" in mail.html and "pain" in mail.html

    # aperçu dans l'interface
    r = logged_client.get(f"/app/establishments/{establishment_id}/report?month=2026-10")
    assert r.status_code == 200 and "Trois recommandations" in r.text and "octobre 2026" in r.text


def test_monthly_report_eligibility(logged_client, establishment_id, services):
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, plan="solo", subscription_status="active")
        results = send_monthly_reports(conn, services, month="2026-10")
        assert results[0]["status"] == "non éligible"
        results = send_monthly_reports(conn, services, month="2026-10", dry_run=True, force=True)
        assert results[0]["status"] == "dry-run" and "<html" in results[0]["html"]
