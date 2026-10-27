import re

from conftest import login

from avis_clients.auth import SessionSigner


def test_app_requires_login(client):
    r = client.get("/app")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_magic_link_flow_creates_account_and_session(client, services):
    r = client.post("/login", data={"email": "pas-un-email"})
    assert r.status_code == 400

    login(client, services, "gerant@exemple.fr")
    assert "avis_session" in client.cookies
    r = client.get("/app")
    assert r.status_code == 200
    assert "Bienvenue" in r.text

    with services.db.session() as conn:
        row = conn.execute("SELECT email, plan FROM accounts").fetchone()
        assert row["email"] == "gerant@exemple.fr" and row["plan"] == "none"
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 1


def test_magic_link_is_single_use_and_expires(client, services):
    client.post("/login", data={"email": "x@exemple.fr"})
    token = re.search(r"/auth/([A-Za-z0-9_\-]+)", services.mailer.sent[-1].html).group(1)
    assert client.get(f"/auth/{token}").status_code == 303
    r = client.get(f"/auth/{token}")
    assert r.status_code == 400 and "invalide ou a expiré" in r.text

    client.post("/login", data={"email": "x@exemple.fr"})
    token2 = re.search(r"/auth/([A-Za-z0-9_\-]+)", services.mailer.sent[-1].html).group(1)
    with services.db.session() as conn:
        conn.execute("UPDATE magic_links SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert client.get(f"/auth/{token2}").status_code == 400


def test_logout_clears_session(logged_client, services):
    r = logged_client.post("/logout")
    assert r.status_code == 303
    assert logged_client.get("/app").status_code == 303
    with services.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 0


def test_tampered_cookie_is_rejected(client, services):
    login(client, services)
    client.cookies.set("avis_session", "nimporte.quoi.signe")
    assert client.get("/app").status_code == 303


def test_session_signer_roundtrip():
    s = SessionSigner("secret", 60)
    assert s.unsign(s.sign("abc")) == "abc"
    assert SessionSigner("autre", 60).unsign(s.sign("abc")) is None
    assert s.unsign(None) is None


def test_cross_origin_post_is_refused(logged_client):
    r = logged_client.post("/logout", headers={"Origin": "https://attaquant.exemple"})
    assert r.status_code == 403
