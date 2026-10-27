import json
from pathlib import Path

from typer.testing import CliRunner

from avis_clients.gbp import GBPReview, LiveGBPClient, MockGBPClient

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.content = b"x"
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append(("GET", url, params))
        if url.endswith("/reviews") and not (params or {}).get("pageToken"):
            return FakeResponse(200, {"reviews": [{"reviewId": "a", "reviewer": {"displayName": "A"},
                                                   "starRating": "FOUR", "comment": "ok",
                                                   "createTime": "2026-10-01T00:00:00Z"}],
                                      "nextPageToken": "p2"})
        if url.endswith("/reviews"):
            return FakeResponse(200, {"reviews": [{"reviewId": "b", "reviewer": {"displayName": "B"},
                                                   "starRating": "TWO", "createTime": "2026-10-02T00:00:00Z"}]})
        if url.endswith("/accounts"):
            return FakeResponse(200, {"accounts": [{"name": "accounts/1"}]})
        if "/locations" in url:
            return FakeResponse(200, {"locations": [{"name": "locations/9", "title": "Chez Lou",
                                                     "metadata": {"placeId": "ChIJlou"}}]})
        return FakeResponse(404, {"error": "?"})

    def put(self, url, json=None, **kwargs):
        self.calls.append(("PUT", url, json))
        return FakeResponse(200, {"comment": json["comment"], "updateTime": "2026-10-03T00:00:00Z"})


def test_live_client_paginates_replies_and_lists_locations(tmp_path):
    session = FakeSession()
    client = LiveGBPClient(tmp_path / "token.json", session=session)
    reviews = client.list_reviews("accounts/1/locations/9")
    assert [r.review_id for r in reviews] == ["a", "b"] and reviews[1].rating == 2 and reviews[1].text == ""
    assert reviews[0].name == "accounts/1/locations/9/reviews/a"
    assert session.calls[0][1] == "https://mybusiness.googleapis.com/v4/accounts/1/locations/9/reviews"
    assert session.calls[1][2]["pageToken"] == "p2"
    out = client.reply("accounts/1/locations/9/reviews/a", "Merci")
    assert out["comment"] == "Merci"
    assert session.calls[-1] == ("PUT", "https://mybusiness.googleapis.com/v4/accounts/1/locations/9/reviews/a/reply",
                                 {"comment": "Merci"})
    locs = client.list_locations()
    assert locs == [{"name": "accounts/1/locations/9", "title": "Chez Lou", "placeId": "ChIJlou"}]


def test_live_client_without_token_raises(tmp_path):
    import pytest

    from avis_clients.gbp import GBPError

    with pytest.raises(GBPError):
        LiveGBPClient(tmp_path / "absent.json").list_reviews("accounts/1/locations/1")


def test_mock_client_persists_replies(tmp_path):
    state = tmp_path / "state.json"
    c = MockGBPClient(fixtures_path=FIXTURES / "gbp_reviews.json", state_file=state)
    reviews = c.list_reviews("accounts/x/locations/y")
    assert len(reviews) == 5 and reviews[2].reply_text == "Merci Sophie !"
    c.reply(reviews[0].name, "Merci !")
    again = MockGBPClient(fixtures_path=FIXTURES / "gbp_reviews.json", state_file=state)
    assert again.list_reviews("accounts/x/locations/y")[0].reply_text == "Merci !"
    assert c.list_locations()[0]["placeId"] == "ChIJtestplaceid0001"
    assert GBPReview.from_api({"reviewId": "z", "starRating": "FIVE"}, "accounts/1/locations/1").author == "Anonyme"


def test_cli_demo_and_jobs(tmp_path, monkeypatch):
    from avis_clients import cli
    from avis_clients import settings as settings_module

    env = {
        "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console", "SMS_PROVIDER": "dry-run", "GBP_MODE": "mock",
        "DATA_DIR": str(tmp_path / "data"), "DB_PATH": str(tmp_path / "cli.db"),
        "GBP_FIXTURES_FILE": str(FIXTURES / "gbp_reviews.json"), "SESSION_SECRET": "x",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    settings_module.get_settings.cache_clear()
    runner = CliRunner()
    r = runner.invoke(cli.app, ["init-db"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli.app, ["demo"])
    assert r.exit_code == 0, r.output
    assert '"new": 5' in r.output
    r = runner.invoke(cli.app, ["poll-reviews"])
    assert r.exit_code == 0 and '"new": 0' in r.output
    r = runner.invoke(cli.app, ["monthly-report", "--month", "2026-10", "--dry-run", "--out", str(tmp_path / "out")])
    assert r.exit_code == 0, r.output
    assert list((tmp_path / "out").glob("*.html"))
    r = runner.invoke(cli.app, ["accounts", "set-plan", "demo@exemple.fr", "pro"])
    assert r.exit_code == 0 and "formule pro" in r.output
    r = runner.invoke(cli.app, ["optouts", "add", "0612345678"])
    assert r.exit_code == 0 and "+33612345678" in r.output
    r = runner.invoke(cli.app, ["sms-test", "0612345678"])
    assert r.exit_code == 0 and "dry-run" in r.output
    r = runner.invoke(cli.app, ["establishments"])
    assert "Boulangerie Dupont" in r.output
    settings_module.get_settings.cache_clear()
