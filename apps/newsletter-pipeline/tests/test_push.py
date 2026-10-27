import json

import httpx
import pytest

from newsletter_pipeline import db
from newsletter_pipeline.push import PushError, build_beehiiv_request, push_issue


def test_push_file_target(conn, settings, drafted):
    result = push_issue(conn, settings, 1, "file")
    assert (settings.out_dir / "push-file-001.html").exists()
    data = json.loads((settings.out_dir / "push-file-001.json").read_text(encoding="utf-8"))
    assert data["target"] == "file" and data["title"] == drafted.title
    assert result.messages and "prêt à coller" in result.messages[0]


def test_push_beehiiv_dry_run_writes_exact_request(conn, settings, drafted):
    settings.beehiiv_publication_id = "pub_test123"
    settings.beehiiv_api_key = "secret-key"
    result = push_issue(conn, settings, 1, "beehiiv")
    assert result.live is False
    data = json.loads((settings.out_dir / "push-beehiiv-001.json").read_text(encoding="utf-8"))
    assert data["method"] == "POST"
    assert data["url"] == "https://api.beehiiv.com/v2/publications/pub_test123/posts"
    assert data["headers"]["Authorization"] == "Bearer ${BEEHIIV_API_KEY}" and "secret-key" not in json.dumps(data)
    assert data["json"]["status"] == "draft" and data["json"]["title"] == drafted.title
    assert data["json"]["body_content"].lstrip().startswith("<!doctype html>")
    assert "relue et signée par un humain" in data["json"]["body_content"]
    assert db.get_issue(conn, 1)["status"] == "draft"  # rien n'est envoyé


def test_push_rerenders_from_edited_markdown(conn, settings, drafted):
    md_path = drafted.paths["md"]
    md_path.write_text(md_path.read_text(encoding="utf-8").replace("[À RELIRE]", "Relu par Hugo."), encoding="utf-8")
    push_issue(conn, settings, 1, "beehiiv")
    data = json.loads((settings.out_dir / "push-beehiiv-001.json").read_text(encoding="utf-8"))
    assert "Relu par Hugo." in data["json"]["body_content"] and "[À RELIRE]" not in data["json"]["body_content"]
    assert "Relu par Hugo." in drafted.paths["txt"].read_text(encoding="utf-8")


def test_push_beehiiv_live_requires_credentials(conn, settings, drafted):
    with pytest.raises(PushError, match="BEEHIIV_API_KEY"):
        push_issue(conn, settings, 1, "beehiiv", live=True)


def test_push_beehiiv_live_with_mock_transport(conn, settings, drafted):
    settings.beehiiv_publication_id = "pub_test123"
    settings.beehiiv_api_key = "secret-key"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "post_abc", "status": "draft"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = push_issue(conn, settings, 1, "beehiiv", live=True, client=client)
    assert seen["url"].endswith("/publications/pub_test123/posts") and seen["auth"] == "Bearer secret-key"
    assert seen["body"]["status"] == "draft"
    assert result.response["data"]["id"] == "post_abc"
    assert (settings.out_dir / "push-beehiiv-001.response.json").exists()
    issue = db.get_issue(conn, 1)
    assert issue["status"] == "pushed" and issue["pushed_target"] == "beehiiv" and issue["pushed_at"]


def test_push_beehiiv_live_error_mentions_fallback(conn, settings, drafted):
    settings.beehiiv_publication_id = "pub_test123"
    settings.beehiiv_api_key = "secret-key"
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"errors": [{"message": "not available on your plan"}]})))
    with pytest.raises(PushError, match="Repli"):
        push_issue(conn, settings, 1, "beehiiv", live=True, client=client)
    assert db.get_issue(conn, 1)["status"] == "draft"


def test_push_kessel_is_manual(conn, settings, drafted):
    result = push_issue(conn, settings, 1, "kessel")
    data = json.loads((settings.out_dir / "push-kessel-001.json").read_text(encoding="utf-8"))
    assert data["mode"] == "manuel" and data["html_path"].endswith("001-2026-11-03.html")
    assert result.messages
    with pytest.raises(PushError, match="pas d'API publique"):
        push_issue(conn, settings, 1, "kessel", live=True)


def test_push_unknown_issue_or_target(conn, settings, drafted):
    with pytest.raises(PushError, match="introuvable"):
        push_issue(conn, settings, 42, "file")
    with pytest.raises(PushError, match="cible inconnue"):
        push_issue(conn, settings, 1, "substack")


def test_build_beehiiv_request_defaults(settings, conn, drafted):
    issue = db.get_issue(conn, 1)
    req = build_beehiiv_request(settings, issue, "<html></html>", {"preheader": ""})
    assert "pub_XXXXXXXX" in req["url"] and req["json"]["content_tags"] == ["ia", "cabinets"]
    assert req["json"]["subtitle"] == settings.newsletter_tagline


def test_push_title_and_preview_follow_edited_markdown(conn, settings, drafted):
    md_path = drafted.paths["md"]
    md = md_path.read_text(encoding="utf-8")
    md = md.replace(f"# {drafted.title}", "# Titre relu par Hugo", 1).replace("> Un assistant, un décret, un chiffre.",
                                                                              "> Aperçu relu par Hugo")
    md_path.write_text(md, encoding="utf-8")
    push_issue(conn, settings, 1, "beehiiv")
    data = json.loads((settings.out_dir / "push-beehiiv-001.json").read_text(encoding="utf-8"))
    assert data["json"]["title"] == "Titre relu par Hugo"
    assert data["json"]["email_settings"]["preview_text"] == "Aperçu relu par Hugo"
    assert "<title>Titre relu par Hugo</title>" in data["json"]["body_content"]
    assert db.get_issue(conn, 1)["title"] == "Titre relu par Hugo"  # la base suit le markdown relu


def test_push_live_without_credentials_leaves_no_live_request(conn, settings, drafted):
    with pytest.raises(PushError, match="BEEHIIV_API_KEY"):
        push_issue(conn, settings, 1, "beehiiv", live=True)
    assert not (settings.out_dir / "push-beehiiv-001.json").exists()
