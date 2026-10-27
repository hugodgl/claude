"""Fixtures communes : réglages isolés (base temporaire, LLM mock, mail console), transport HTTP simulé."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from veille_marches import db
from veille_marches.settings import VMSettings

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def settings(tmp_path: Path) -> VMSettings:
    return VMSettings(_env_file=None, db_path=tmp_path / "vm.db", out_dir=tmp_path / "out", data_dir=tmp_path,
                      llm_provider="mock", mail_provider="console", reply_to="hugo@example.com")


@pytest.fixture
def conn(settings: VMSettings):
    c = db.open_db(settings.db_path)
    yield c
    c.close()


@dataclass
class FakeApis:
    """Simule les trois API : Opendatasoft (BOAMP, DECP) et TED, avec pagination, et journalise les requêtes."""

    boamp: dict = field(default_factory=lambda: load_fixture("boamp_records.json"))
    ted: dict = field(default_factory=lambda: load_fixture("ted_search.json"))
    decp: dict = field(default_factory=lambda: load_fixture("decp_records.json"))
    requests: list[httpx.Request] = field(default_factory=list)
    fail_hosts: set[str] = field(default_factory=set)

    def _ods(self, payload: dict, request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params.get("limit", 100))
        offset = int(request.url.params.get("offset", 0))
        rows = payload["results"][offset: offset + limit]
        return httpx.Response(200, json={"total_count": len(payload["results"]), "results": rows})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.fail_hosts:
            return httpx.Response(500, text="boom")
        if host == "boamp-datadila.opendatasoft.com":
            return self._ods(self.boamp, request)
        if host == "data.economie.gouv.fr":
            return self._ods(self.decp, request)
        if host == "api.ted.europa.eu":
            body = json.loads(request.content.decode())
            page, limit = int(body.get("page", 1)), int(body.get("limit", 100))
            rows = self.ted["notices"][(page - 1) * limit: page * limit]
            return httpx.Response(200, json={"notices": rows, "totalNoticeCount": len(self.ted["notices"]),
                                             "iterationNextToken": None, "timedOut": False})
        return httpx.Response(404, text=f"hôte inconnu {host}")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def ted_bodies(self) -> list[dict]:
        return [json.loads(r.content.decode()) for r in self.requests if r.url.host == "api.ted.europa.eu"]


@pytest.fixture
def apis() -> FakeApis:
    return FakeApis()
