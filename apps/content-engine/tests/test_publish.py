import json

import httpx
import pytest

from content_engine.publish import PublishError, publish_draft
from content_engine.publish.base import redact
from content_engine.publish.linkedin import escape_little_text
from content_engine.publish.youtube import YouTubePublisher
from content_engine.scripts import get_draft
from tests.conftest import fake_render, make_draft


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_youtube_dry_run_payload(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=1, status="rendered")
    fake_render(settings, draft_id, synthetic_voice=True)
    rep = publish_draft(conn, draft_id, "youtube", settings)
    assert rep.dry_run and rep.request_file.name == "publish-youtube.json"
    data = _load(rep.request_file)
    assert data["dry_run"] is True and data["platform"] == "youtube"
    init = data["requests"][0]
    assert init["method"] == "POST" and init["params"] == {
        "uploadType": "resumable",
        "part": "snippet,status",
    }
    assert init["headers"]["Authorization"] == "Bearer <jeton OAuth YouTube>"
    status = init["json"]["status"]
    assert status["selfDeclaredMadeForKids"] is False and status["containsSyntheticMedia"] is True
    assert status["privacyStatus"] == "private"
    snippet = init["json"]["snippet"]
    assert len(snippet["title"]) <= 100 and snippet["defaultAudioLanguage"] == "fr"
    assert (
        settings.ai_disclosure in snippet["description"]
        and "example.com/avis" in snippet["description"]
    )
    assert data["requests"][1]["files"][0]["path"].endswith("video.mp4")
    assert data["requests"][2]["step"] == "thumbnails.set"
    row = conn.execute("SELECT * FROM publications WHERE draft_id = ?", (draft_id,)).fetchone()
    assert row["dry_run"] == 1 and row["platform"] == "youtube"
    assert get_draft(conn, draft_id)["status"] == "rendered"


def test_youtube_synthetic_flag_follows_render(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=2, status="rendered")
    fake_render(settings, draft_id, synthetic_voice=False)
    data = _load(publish_draft(conn, draft_id, "youtube", settings).request_file)
    assert data["requests"][0]["json"]["status"]["containsSyntheticMedia"] is False


def test_pinterest_dry_run_payload(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=30, fmt="pin", status="rendered")
    fake_render(settings, draft_id, fmt="pin")
    data = _load(publish_draft(conn, draft_id, "pinterest", settings).request_file)
    req = data["requests"][0]
    assert req["url"].endswith("/v5/pins") and req["method"] == "POST"
    body = req["json"]
    assert body["board_id"] == "<PINTEREST_BOARD_ID>" and len(body["title"]) <= 100
    assert len(body["description"]) <= 800 and settings.ai_disclosure in body["description"]
    assert body["link"] == settings.landing_url_cabinets
    assert body["media_source"]["source_type"] == "image_base64"
    assert body["media_source"]["data"].startswith("<base64")


def test_linkedin_dry_run_payload_and_redaction(conn, llm, settings):
    settings = settings.model_copy(
        update={
            "linkedin_access_token": "secret-token-123456",
            "linkedin_author_urn": "urn:li:organization:42",
        }
    )
    draft_id = make_draft(conn, llm, topic_id=16, fmt="linkedin", status="approved")
    data = _load(publish_draft(conn, draft_id, "linkedin", settings).request_file)
    req = data["requests"][0]
    assert req["url"].endswith("/rest/posts")
    assert req["headers"]["LinkedIn-Version"] == settings.linkedin_version
    assert req["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert req["headers"]["Authorization"] == "Bearer secr…[masqué]"
    body = req["json"]
    assert body["author"] == "urn:li:organization:42" and body["lifecycleState"] == "PUBLISHED"
    assert "{hashtag|\\#|marchespublics}" in body["commentary"]
    assert settings.ai_disclosure in body["commentary"] and len(body["commentary"]) <= 3000
    assert escape_little_text("a (b) #c @d") == "a \\(b\\) \\#c \\@d"
    assert (
        redact("Bearer abcdefghijkl") == "Bearer abcd…[masqué]"
        and redact("Bearer <X>") == "Bearer <X>"
    )


def test_tiktok_dry_run_payload(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=3, status="rendered")
    fake_render(settings, draft_id)
    data = _load(publish_draft(conn, draft_id, "tiktok", settings).request_file)
    init, upload, status = data["requests"]
    assert init["url"].endswith("/v2/post/publish/video/init/")
    post_info = init["json"]["post_info"]
    assert post_info["is_aigc"] is True and post_info["privacy_level"] == "SELF_ONLY"
    assert len(post_info["title"]) <= 2200 and settings.ai_disclosure in post_info["title"]
    source = init["json"]["source_info"]
    assert (
        source["source"] == "FILE_UPLOAD" and source["chunk_size"] == source["video_size"] == 2048
    )
    assert upload["headers"]["Content-Range"] == "bytes 0-2047/2048"
    assert status["url"].endswith("/v2/post/publish/status/fetch/")
    assert data["summary"]["audit_required"] is True


def test_publish_guards(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=16, fmt="linkedin")
    with pytest.raises(PublishError, match="approuver"):
        publish_draft(conn, draft_id, "linkedin", settings)
    short = make_draft(conn, llm, topic_id=1, status="rendered")
    with pytest.raises(PublishError, match="incompatible"):
        publish_draft(conn, short, "linkedin", settings)
    with pytest.raises(PublishError, match="absent"):
        publish_draft(conn, short, "youtube", settings)  # pas de video.mp4
    with pytest.raises(PublishError, match="inconnue"):
        publish_draft(conn, short, "mastodon", settings)
    with pytest.raises(PublishError, match="LINKEDIN_ACCESS_TOKEN"):
        publish_draft(
            conn,
            make_draft(conn, llm, topic_id=17, fmt="linkedin", status="approved"),
            "linkedin",
            settings,
            live=True,
        )


def test_live_pinterest_with_mock_transport(conn, llm, settings):
    settings = settings.model_copy(
        update={"pinterest_access_token": "tok", "pinterest_board_id": "b1"}
    )
    draft_id = make_draft(conn, llm, topic_id=31, fmt="pin", status="rendered")
    fake_render(settings, draft_id, fmt="pin")
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer tok" and body["board_id"] == "b1"
        assert body["media_source"]["data"].startswith("/9j/")  # base64 d'un JPEG
        return httpx.Response(201, json={"id": "9876"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rep = publish_draft(conn, draft_id, "pinterest", settings, live=True, client=client)
    assert not rep.dry_run and rep.outcome.url == "https://www.pinterest.com/pin/9876/"
    assert len(seen) == 1 and get_draft(conn, draft_id)["status"] == "published"
    row = conn.execute(
        "SELECT * FROM publications WHERE draft_id = ? AND dry_run = 0", (draft_id,)
    ).fetchone()
    assert row["remote_id"] == "9876"
    with pytest.raises(PublishError, match="déjà publié"):
        publish_draft(conn, draft_id, "pinterest", settings, live=True, client=client)
    assert _load(rep.request_file)["dry_run"] is False


def test_live_youtube_with_mock_transport(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=4, status="rendered")
    fake_render(settings, draft_id)
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, str(request.url)))
        if request.method == "POST" and "/videos" in str(request.url):
            assert json.loads(request.content)["status"]["containsSyntheticMedia"] is True
            return httpx.Response(200, headers={"Location": "https://upload.test/session/1"})
        if request.method == "PUT":
            assert len(request.content) == 2048
            return httpx.Response(200, json={"id": "vid123"})
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rep = publish_draft(
        conn,
        draft_id,
        "youtube",
        settings,
        live=True,
        client=client,
        publisher=YouTubePublisher(token="t0k"),
    )
    assert rep.outcome.remote_id == "vid123" and rep.outcome.url == "https://youtu.be/vid123"
    assert [m for m, _ in calls] == ["POST", "PUT", "POST"]
    assert calls[2][1].startswith("https://www.googleapis.com/upload/youtube/v3/thumbnails/set")


def test_live_linkedin_and_tiktok_with_mock_transport(conn, llm, settings):
    settings = settings.model_copy(
        update={
            "linkedin_access_token": "lt",
            "linkedin_author_urn": "urn:li:person:1",
            "tiktok_access_token": "tt",
        }
    )
    post = make_draft(conn, llm, topic_id=18, fmt="linkedin", status="approved")
    short = make_draft(conn, llm, topic_id=5, status="rendered")
    fake_render(settings, short)

    def handler(request: httpx.Request):
        url = str(request.url)
        if url.endswith("/rest/posts"):
            assert request.headers["LinkedIn-Version"] == settings.linkedin_version
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:77"})
        if url.endswith("/video/init/"):
            return httpx.Response(
                200, json={"data": {"publish_id": "p1", "upload_url": "https://up.test/x"}}
            )
        if request.method == "PUT":
            assert request.headers["Content-Range"] == "bytes 0-2047/2048"
            return httpx.Response(201)
        if url.endswith("/status/fetch/"):
            return httpx.Response(200, json={"data": {"status": "PROCESSING_UPLOAD"}})
        raise AssertionError(url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rep = publish_draft(conn, post, "linkedin", settings, live=True, client=client)
    assert rep.outcome.url == "https://www.linkedin.com/feed/update/urn:li:share:77/"
    rep = publish_draft(conn, short, "tiktok", settings, live=True, client=client)
    assert rep.outcome.remote_id == "p1" and rep.outcome.response["status"] == "PROCESSING_UPLOAD"
