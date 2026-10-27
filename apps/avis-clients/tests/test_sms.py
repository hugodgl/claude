import httpx
import pytest
from conftest import flash_of

from avis_clients.billing import account_access
from avis_clients.repo import get_account_by_email, update_account
from avis_clients.requests_service import parse_contacts_csv
from avis_clients.sms import (
    DEFAULT_REQUEST_TEMPLATE,
    SMSError,
    SmsmodeSMS,
    TwilioSMS,
    looks_like_stop,
    normalize_phone,
    render_message,
)


@pytest.mark.parametrize("raw,expected", [
    ("06 12 34 56 78", "+33612345678"),
    ("0612345678", "+33612345678"),
    ("+33 6 12 34 56 78", "+33612345678"),
    ("0033612345678", "+33612345678"),
    ("612345678", "+33612345678"),
    ("+41 79 123 45 67", "+41791234567"),
    ("12", None),
    ("abc", None),
    ("", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_render_message_and_stop_detection():
    msg = render_message(DEFAULT_REQUEST_TEMPLATE, prenom="Camille", etablissement="Chez Lou",
                         lien="http://testserver/r/chez-lou")
    assert msg.startswith("Bonjour Camille, merci pour votre visite chez Chez Lou.")
    assert "http://testserver/r/chez-lou" in msg and "STOP" in msg
    anonymous = render_message(DEFAULT_REQUEST_TEMPLATE, prenom=None, etablissement="X", lien="L")
    assert anonymous.startswith("Bonjour, merci")
    assert looks_like_stop(" Stop ") and looks_like_stop("STOP SMS") and not looks_like_stop("Merci !")


def test_parse_contacts_csv_variants():
    assert parse_contacts_csv("telephone;prenom\n0612345678;Camille\n0698765432;\n") == [
        ("0612345678", "Camille"), ("0698765432", "")]
    assert parse_contacts_csv("Prénom,Téléphone\nLéa,06 11 22 33 44\n") == [("06 11 22 33 44", "Léa")]
    assert parse_contacts_csv("0612345678,Marc\n") == [("0612345678", "Marc")]
    assert parse_contacts_csv("") == []


def _sms_history(services):
    with services.db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM review_requests ORDER BY id")]


def test_dry_run_send_records_request_and_event(logged_client, establishment_id, services):
    r = logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                       "recipient": "06 12 34 56 78", "first_name": "Camille"})
    assert r.status_code == 303 and "simulé" in flash_of(r)
    rows = _sms_history(services)
    assert len(rows) == 1 and rows[0]["status"] == "dry-run" and rows[0]["recipient"] == "+33612345678"
    assert "Boulangerie Test" in rows[0]["message"] and "/r/boulangerie-test" in rows[0]["message"]
    assert services.sms.sent[0]["to"] == "+33612345678"
    with services.db.session() as conn:
        kinds = [row["kind"] for row in conn.execute("SELECT kind FROM events")]
    assert "review_request_sent" in kinds
    page = logged_client.get("/app/requests")
    assert page.status_code == 200 and "+33612345678" in page.text and "1 / 3" in page.text


def test_quota_blocks_when_exhausted_and_depends_on_plan(logged_client, establishment_id, services):
    for i in range(3):  # quota d'essai = 3 dans les tests
        logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                       "recipient": f"06 12 34 56 7{i}"})
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "06 99 99 99 99"})
    rows = _sms_history(services)
    assert [r["status"] for r in rows] == ["dry-run", "dry-run", "dry-run", "blocked_quota"]

    # formule Solo : aucun SMS ; Pro : 100
    with services.db.session() as conn:
        acc = get_account_by_email(conn, "gerant@exemple.fr")
        update_account(conn, acc.id, plan="solo", subscription_status="active")
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "06 88 88 88 88"})
    assert _sms_history(services)[-1]["status"] == "blocked_quota"
    with services.db.session() as conn:
        update_account(conn, acc.id, plan="pro", subscription_status="active")
        assert account_access(get_account_by_email(conn, "gerant@exemple.fr"), services.settings).plan == "pro"
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "06 88 88 88 88"})
    assert _sms_history(services)[-1]["status"] == "dry-run"


def test_stop_list_is_respected_and_fed_by_webhook(logged_client, client, establishment_id, services):
    logged_client.post("/app/requests/optouts", data={"phone": "06 11 11 11 11"})
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "0611111111"})
    assert _sms_history(services)[-1]["status"] == "blocked_optout"

    # envoi puis réponse STOP via le webhook Twilio : le numéro est bloqué pour ce compte
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "0622222222"})
    assert _sms_history(services)[-1]["status"] == "dry-run"
    r = client.post("/webhooks/sms/inbound", data={"From": "+33622222222", "Body": "STOP"})
    assert r.status_code == 200 and r.headers["x-optout"] == "1"
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "sms",
                                                   "recipient": "0622222222"})
    assert _sms_history(services)[-1]["status"] == "blocked_optout"
    # callback smsmode en GET, message quelconque : ignoré
    assert client.get("/webhooks/sms/inbound?numero=33633333333&message=Merci").text == "IGNORED"


def test_csv_import_sends_to_each_contact(logged_client, establishment_id, services):
    csv_content = "telephone;prenom\n0612345678;Camille\n0698765432;Lou\nabc;Invalide\n"
    r = logged_client.post("/app/requests/import", data={"establishment_id": establishment_id, "channel": "sms"},
                           files={"file": ("contacts.csv", csv_content.encode("utf-8"), "text/csv")})
    assert r.status_code == 303
    rows = _sms_history(services)
    assert [row["status"] for row in rows] == ["dry-run", "dry-run"]
    assert rows[1]["first_name"] == "Lou"


def test_email_channel_uses_mailer(logged_client, establishment_id, services):
    before = len(services.mailer.sent)
    logged_client.post("/app/requests/send", data={"establishment_id": establishment_id, "channel": "email",
                                                   "recipient": "client@exemple.fr", "first_name": "Léa"})
    assert len(services.mailer.sent) == before + 1
    assert "/r/boulangerie-test" in services.mailer.sent[-1].html
    assert _sms_history(services)[-1]["status"] == "sent"


def test_template_update_requires_link_and_stop(logged_client, establishment_id, services):
    r = logged_client.post("/app/requests/template", data={"establishment_id": establishment_id,
                                                           "request_template": "Bonjour, un avis ? STOP pour arrêter"})
    assert "doit contenir" in flash_of(r)
    r = logged_client.post("/app/requests/template", data={"establishment_id": establishment_id,
                                                           "request_template": "Bonjour {prenom}, un avis ? {lien}"})
    assert "STOP" in flash_of(r)
    r = logged_client.post("/app/requests/template", data={"establishment_id": establishment_id,
                                                           "request_template": "Bonjour {prenom}, avis ? {lien} STOP"})
    assert "enregistr" in flash_of(r)


def test_smsmode_adapter_rest_and_http16_without_network():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.host == "rest.smsmode.com":
            assert request.headers["X-Api-Key"] == "k"
            assert b'"to": "33612345678"' in request.read() or b'"to":"33612345678"' in request.read()
            return httpx.Response(201, json={"messageId": "m-1", "status": "SCHEDULED"})
        return httpx.Response(200, text="0 | Accepté | 12345")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rest = SmsmodeSMS("k", "AvisClients", api="rest", client=client)
    res = rest.send("+33612345678", "Bonjour")
    assert res.status == "sent" and res.message_id == "m-1"
    legacy = SmsmodeSMS("k", "AvisClients", api="http16", client=client)
    res = legacy.send("+33612345678", "Bonjour")
    assert res.message_id == "12345" and "accessToken=k" in seen[-1].read().decode()
    with pytest.raises(SMSError):
        rest.send("+33612345678", "x", channel="whatsapp")


def test_twilio_adapter_sms_and_whatsapp_without_network():
    bodies = []

    def handler(request: httpx.Request):
        bodies.append(request.read().decode())
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(201, json={"sid": "SM123", "status": "queued"})

    tw = TwilioSMS("AC1", "tok", "+33700000000", "whatsapp:+14155238886",
                   client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert tw.send("+33612345678", "Hello").message_id == "SM123"
    assert "To=%2B33612345678" in bodies[0]
    tw.send("+33612345678", "Hello", channel="whatsapp")
    assert "To=whatsapp%3A%2B33612345678" in bodies[1] and "From=whatsapp%3A%2B14155238886" in bodies[1]
