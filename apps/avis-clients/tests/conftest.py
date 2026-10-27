import json
import re
from pathlib import Path

import pytest
from core.llm import MockLLM
from core.mail import ConsoleMailer
from fastapi.testclient import TestClient

from avis_clients.gbp import MockGBPClient
from avis_clients.services import build_services
from avis_clients.settings import AppSettings
from avis_clients.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def smart_llm(prompt: str, system: str | None) -> str:
    """Mock LLM : répond selon le type de demande (exemples de ton, brouillon, recommandations)."""
    if '"exemples"' in prompt:
        return json.dumps({"exemples": ["Merci Camille, quel plaisir ! À très vite.",
                                        "Merci Camille, nous notons votre remarque sur l'attente.",
                                        "Bonjour Camille, désolés pour cette expérience, contactez-nous directement."]})
    if '"reply"' in prompt:
        m = re.search(r"note : (\d) étoiles", prompt)
        rating = int(m.group(1)) if m else 5
        if rating <= 2:
            return json.dumps({"reply": "Nous sommes sincèrement désolés de cette expérience. Nous aimerions en "
                                        "discuter avec vous : passez nous voir ou contactez-nous directement. "
                                        "L'équipe"})
        return json.dumps({"reply": "Merci beaucoup pour ce retour chaleureux, toute l'équipe est ravie. "
                                    "À très bientôt ! L'équipe"})
    if '"recommandations"' in prompt:
        return json.dumps({"recommandations": ["Répondre sous 24 h.", "Proposer le QR à l'encaissement.",
                                               "Renforcer la caisse le samedi matin."]})
    return "{}"


class FakeStripeGateway:
    def __init__(self, settings):
        self.settings = settings
        self.enabled = True
        self.checkouts: list[dict] = []
        self.portals: list[dict] = []

    def create_checkout_session(self, **kwargs):
        self.checkouts.append(kwargs)
        return f"https://checkout.stripe.test/cs_{kwargs['plan']}"

    def create_portal_session(self, **kwargs):
        self.portals.append(kwargs)
        return "https://billing.stripe.test/portal"

    def construct_event(self, payload: bytes, sig_header: str | None):
        from avis_clients.billing import StripeGateway

        return StripeGateway(self.settings).construct_event(payload, sig_header)


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        _env_file=None,
        llm_provider="mock", mail_provider="console", sms_provider="dry-run", gbp_mode="mock",
        data_dir=tmp_path / "data", db_path=tmp_path / "test.db", session_secret="secret-de-test",
        app_base_url="http://testserver", stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_test",
        stripe_price_solo="price_solo", stripe_price_pro="price_pro", stripe_price_reseau="price_reseau",
        gbp_fixtures_file=FIXTURES / "gbp_reviews.json", trial_sms_quota=3,
    )


@pytest.fixture
def services(settings):
    return build_services(
        settings,
        mailer=ConsoleMailer(quiet=True),
        llm=MockLLM(responses=smart_llm),
        gbp=MockGBPClient(fixtures_path=FIXTURES / "gbp_reviews.json"),
        stripe=FakeStripeGateway(settings),
    )


@pytest.fixture
def app(services):
    return create_app(services=services)


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def flash_of(response) -> str:
    """Décode le message flash posé dans le cookie de la réponse."""
    from urllib.parse import unquote

    cookie = response.headers.get("set-cookie", "")
    m = re.search(r"avis_flash=([^;]+)", cookie)
    return json.loads(unquote(m.group(1)))["message"] if m else ""


def login(client: TestClient, services, email: str = "gerant@exemple.fr") -> str:
    """Parcourt le flux de lien magique et retourne l'email connecté."""
    r = client.post("/login", data={"email": email})
    assert r.status_code == 200
    mail = services.mailer.sent[-1]
    m = re.search(r"http://testserver/auth/([A-Za-z0-9_\-]+)", mail.html)
    assert m, mail.html
    r = client.get(f"/auth/{m.group(1)}")
    assert r.status_code == 303, r.text
    return email


@pytest.fixture
def logged_client(client, services):
    login(client, services)
    return client


def create_establishment(client: TestClient, name: str = "Boulangerie Test",
                         place_id: str = "ChIJtestplaceid0001", style: str = "chaleureux") -> int:
    r = client.post("/app/establishments", data={"name": name, "google_place_id": place_id, "style": style})
    assert r.status_code == 303, r.text
    m = re.search(r"/app/establishments/(\d+)/tone", r.headers["location"])
    assert m
    return int(m.group(1))


@pytest.fixture
def establishment_id(logged_client) -> int:
    return create_establishment(logged_client)
