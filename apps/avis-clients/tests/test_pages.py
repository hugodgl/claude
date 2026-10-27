"""Parcours de toutes les pages GET : aucune erreur de gabarit."""
from conftest import create_establishment

from avis_clients.reviews import poll_reviews


def test_public_pages_render(client):
    for path in ("/", "/login", "/legal/mentions", "/legal/cgv", "/legal/confidentialite", "/healthz"):
        r = client.get(path)
        assert r.status_code == 200, path
    r = client.get("/", headers={"Accept": "text/html"})
    assert "19 €" in r.text and "29 €" in r.text and "59 €" in r.text and "aucun tri par note" in r.text
    r = client.get("/legal/cgv")
    assert "[RAISON SOCIALE]" in r.text  # modèle à compléter
    r = client.get("/r/nexiste-pas", headers={"Accept": "text/html"})
    assert r.status_code == 404 and "Page introuvable" in r.text
    assert client.get("/static/style.css").status_code == 200


def test_app_pages_render(logged_client, services):
    for path in ("/app", "/app/establishments/new", "/app/requests", "/app/inbox", "/billing"):
        assert logged_client.get(path).status_code == 200, path
    est_id = create_establishment(logged_client)
    with services.db.session() as conn:
        poll_reviews(conn, services)
    for path in (
        "/app", f"/app/establishments/{est_id}", f"/app/establishments/{est_id}/tone",
        f"/app/establishments/{est_id}/print", f"/app/establishments/{est_id}/report?month=2026-10",
        "/app/requests", f"/app/requests?establishment={est_id}", "/app/inbox", "/app/inbox?status=all",
        "/app/inbox?status=published", f"/app/inbox?status=draft&establishment={est_id}", "/billing",
    ):
        r = logged_client.get(path)
        assert r.status_code == 200, path
    dash = logged_client.get("/app").text
    assert "réponse(s) à valider" in dash and "Boulangerie Test" in dash
    assert logged_client.get("/app/establishments/999").status_code == 404
    assert logged_client.get("/login").status_code == 303  # déjà connecté
