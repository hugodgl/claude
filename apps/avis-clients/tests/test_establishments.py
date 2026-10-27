import json

from conftest import create_establishment

from avis_clients.qr import qr_png, qr_svg


def test_onboarding_generates_tone_examples_and_review_url(logged_client, services):
    est_id = create_establishment(logged_client, "Café de la Place", "ChIJcafeplace00000001", style="sobre")
    with services.db.session() as conn:
        row = conn.execute("SELECT * FROM establishments WHERE id = ?", (est_id,)).fetchone()
    assert row["review_url"] == "https://search.google.com/local/writereview?placeid=ChIJcafeplace00000001"
    assert row["slug"] == "cafe-de-la-place"
    assert row["google_location_name"] == "accounts/mock/locations/cafe-de-la-place"
    tone = json.loads(row["tone_profile_json"])
    assert tone["style"] == "sobre" and len(tone["exemples"]) == 3
    assert "Camille" in tone["exemples"][0]

    r = logged_client.get(f"/app/establishments/{est_id}/tone")
    assert r.status_code == 200 and "Exemple 1" in r.text

    r = logged_client.post(f"/app/establishments/{est_id}/tone", data={
        "style": "dynamique", "signature": "La team du Café", "do": "phrases courtes", "dont": "pas d'émoji",
        "exemple_1": "Merci !", "exemple_2": "Top !", "exemple_3": "Désolés, venez nous voir.", "action": "save",
    })
    assert r.status_code == 303
    with services.db.session() as conn:
        tone = json.loads(conn.execute("SELECT tone_profile_json FROM establishments WHERE id = ?",
                                       (est_id,)).fetchone()[0])
    assert tone["style"] == "dynamique" and tone["signature"] == "La team du Café"
    assert tone["exemples"] == ["Merci !", "Top !", "Désolés, venez nous voir."]


def test_onboarding_validation_errors(logged_client):
    r = logged_client.post("/app/establishments", data={"name": "X", "google_place_id": "court"})
    assert r.status_code == 400
    assert "est requis" in r.text and "Place ID" in r.text


def test_trial_allows_one_establishment(logged_client):
    create_establishment(logged_client, "Un", "ChIJun00000000000001")
    r = logged_client.post("/app/establishments", data={"name": "Deux", "google_place_id": "ChIJdeux000000000001"})
    assert r.status_code == 400 and "formule" in r.text


def test_qr_endpoints_and_print_page(logged_client, establishment_id):
    png = logged_client.get(f"/app/establishments/{establishment_id}/qr.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    svg = logged_client.get(f"/app/establishments/{establishment_id}/qr.svg?download=1")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in svg.content and "attachment" in svg.headers["content-disposition"]
    r = logged_client.get(f"/app/establishments/{establishment_id}/print")
    assert r.status_code == 200 and "Votre avis compte" in r.text and "size: A6" in r.text
    r = logged_client.get(f"/app/establishments/{establishment_id}")
    assert r.status_code == 200 and "/r/boulangerie-test" in r.text


def test_qr_helpers_encode_url():
    assert qr_png("http://testserver/r/x").startswith(b"\x89PNG")
    assert b"<svg" in qr_svg("http://testserver/r/x")


def test_public_review_page_links_to_google_without_filtering(client, logged_client, establishment_id, services):
    r = client.get("/r/boulangerie-test")
    assert r.status_code == 200
    assert "https://search.google.com/local/writereview?placeid=ChIJtestplaceid0001" in r.text
    assert "Laisser un avis Google" in r.text
    assert "quelle que soit votre note" in r.text
    # le bouton Google précède le formulaire privé
    assert r.text.index("Laisser un avis Google") < r.text.index("Nous écrire en privé")
    assert client.get("/r/inconnu").status_code == 404


def test_private_message_is_emailed_to_merchant(client, logged_client, establishment_id, services):
    before = len(services.mailer.sent)
    r = client.post("/r/boulangerie-test/message", data={"message": "Le café était froid.", "name": "Léa",
                                                          "contact": "lea@exemple.fr"})
    assert r.status_code == 200 and "transmis" in r.text
    mail = services.mailer.sent[-1]
    assert len(services.mailer.sent) == before + 1
    assert mail.to == ["gerant@exemple.fr"] and "Le café était froid." in mail.html
    # pot de miel : rien n'est envoyé
    client.post("/r/boulangerie-test/message", data={"message": "spam", "website": "http://spam"})
    assert len(services.mailer.sent) == before + 1


def test_settings_update_and_auto_publish_toggle(logged_client, establishment_id, services):
    r = logged_client.post(f"/app/establishments/{establishment_id}/settings", data={
        "name": "Boulangerie Test", "google_place_id": "ChIJtestplaceid0001", "google_location_name": "",
        "notification_email": "alertes@exemple.fr", "request_template": "Bonjour {prenom} : {lien}. STOP pour arrêter.",
        "auto_publish_positive": "1",
    })
    assert r.status_code == 303
    with services.db.session() as conn:
        row = conn.execute("SELECT * FROM establishments WHERE id = ?", (establishment_id,)).fetchone()
    assert row["auto_publish_positive"] == 1 and row["notification_email"] == "alertes@exemple.fr"
    assert row["google_location_name"] == "accounts/mock/locations/boulangerie-test"


def test_other_account_cannot_access_establishment(client, logged_client, establishment_id, services, app):
    from conftest import login
    from fastapi.testclient import TestClient

    with TestClient(app, follow_redirects=False) as other:
        login(other, services, "autre@exemple.fr")
        assert other.get(f"/app/establishments/{establishment_id}").status_code == 404
