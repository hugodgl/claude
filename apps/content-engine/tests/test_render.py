import json
from pathlib import Path

import httpx
import pytest

from content_engine.products import PRODUCTS
from content_engine.render import RenderError, find_font, probe, render_draft
from content_engine.render.ffmpeg import ffmpeg_bin, run, wrap_text
from content_engine.render.subtitles import (
    ass_color,
    ass_time,
    proportional_segments,
    split_sentences,
    srt_time,
    write_ass,
    write_srt,
)
from content_engine.render.video import fit_chars
from content_engine.scripts import get_draft
from content_engine.tts import ElevenLabsTTS, SilentTTS, get_tts
from tests.conftest import make_draft, needs_ffmpeg


def test_split_sentences_and_timings():
    grouped = split_sentences(["Première phrase. Deuxième phrase !", "Une seule.",
                               "Phrase très longue, avec plusieurs virgules, " * 4 + "fin."])
    assert grouped[0] == ["Première phrase.", "Deuxième phrase !"] and grouped[1] == ["Une seule."]
    assert all(len(s) <= 90 for s in grouped[2]) and len(grouped[2]) >= 2
    sentences = [s for g in grouped for s in g]
    segments = proportional_segments(sentences, 10.0)
    assert segments[0].start == 0 and abs(segments[-1].end - 10.0) < 0.01
    assert all(b.start >= a.end - 0.001 for a, b in zip(segments, segments[1:], strict=False))
    assert ass_time(61.5) == "0:01:01.50" and srt_time(61.5) == "00:01:01,500"
    assert ass_color("#FFD166") == "&H0066D1FF"


def test_write_ass_and_srt(tmp_path):
    segs = proportional_segments(["Bonjour {monde}.", "Suite."], 4.0)
    ass = write_ass(segs, tmp_path / "s.ass", "DejaVu Sans", PRODUCTS["avis"].palette)
    text = ass.read_text(encoding="utf-8")
    assert text.count("Dialogue:") == 2 and "PlayResX: 1080" in text and "(monde)" in text
    assert "Style: Hook,DejaVu Sans" in text
    srt = write_srt(segs, tmp_path / "s.srt").read_text(encoding="utf-8")
    assert srt.count("-->") == 2 and srt.startswith("1\n00:00:00,000")


def test_wrap_and_font_helpers(tmp_path):
    assert wrap_text("un deux trois quatre cinq six", 10, 2).endswith("…")
    assert fit_chars(1080, 64, 60, 26) == 21
    font = find_font(tmp_path / "absente.ttf")
    assert font.family
    assert get_tts(type("S", (), {"tts_provider": "silent", "tts_silent_duration_s": 3.0})()).name == "silent"


def test_silent_tts_timings(tmp_path):
    res = SilentTTS(duration_s=3.0).synthesize(["Une phrase.", "Une autre phrase plus longue."], tmp_path)
    assert res.audio_path is None and res.duration_s == 3.0 and not res.synthetic
    assert len(res.segments) == 2 and abs(res.segments[-1].end - 3.0) < 0.01


@needs_ffmpeg
def test_render_short_three_seconds(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=1, status="approved")
    result = render_draft(conn, draft_id, settings, tts=SilentTTS(duration_s=2.4))
    out = Path(settings.out_dir) / str(draft_id)
    video = out / "video.mp4"
    assert video.exists() and result.video == "video.mp4"
    info = probe(video)
    assert (info.width, info.height) == (1080, 1920)
    assert info.fps == 30 and info.has_audio and info.video_codec == "h264"
    assert 2.8 <= info.duration_s <= 3.4
    assert probe(out / "thumb.jpg").width == 1280 and probe(out / "thumb.jpg").height == 720
    assert probe(out / "cover.jpg").width == 1080 and probe(out / "cover.jpg").height == 1920
    ass = (out / "subs.ass").read_text(encoding="utf-8")
    assert ass.count("Dialogue:") == len((out / "subs.srt").read_text().strip().split("\n\n"))
    meta = json.loads((out / "render.json").read_text(encoding="utf-8"))
    assert meta["synthetic_voice"] is False and meta["tts_provider"] == "silent"
    assert get_draft(conn, draft_id)["status"] == "rendered"
    assert "drawtext" in (out / "ffmpeg-command.txt").read_text() and "subtitles=subs.ass" in (out / "ffmpeg-command.txt").read_text()


@needs_ffmpeg
def test_render_other_formats(conn, llm, settings):
    pin = make_draft(conn, llm, topic_id=30, fmt="pin", status="approved")
    res = render_draft(conn, pin, settings)
    assert res.video is None and res.cover == "cover.jpg" and res.thumb == "thumb.jpg"
    assert probe(Path(settings.out_dir) / str(pin) / "cover.jpg").height == 1920
    post = make_draft(conn, llm, topic_id=16, fmt="linkedin", status="approved")
    res = render_draft(conn, post, settings)
    text = (Path(settings.out_dir) / str(post) / "post.txt").read_text(encoding="utf-8")
    assert res.text_file == "post.txt" and settings.ai_disclosure in text and "example.com/marches" in text
    long = make_draft(conn, llm, topic_id=2, fmt="long", status="approved")
    res = render_draft(conn, long, settings)
    assert res.text_file == "script.txt" and res.cover and res.video is None


def test_render_requires_approval_and_rejects_long_narration(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=1)
    with pytest.raises(ValueError, match="approuver"):
        render_draft(conn, draft_id, settings)
    if ffmpeg_bin() and probe.__module__:
        pytest.importorskip("shutil")
    draft_id = make_draft(conn, llm, topic_id=2, status="approved")
    with pytest.raises(RenderError, match="raccourcir"):
        render_draft(conn, draft_id, settings, tts=SilentTTS(duration_s=70))


@needs_ffmpeg
def test_render_force_preview_keeps_draft_status(conn, llm, settings):
    draft_id = make_draft(conn, llm, topic_id=3)
    render_draft(conn, draft_id, settings, tts=SilentTTS(duration_s=2.4), force=True)
    assert get_draft(conn, draft_id)["status"] == "draft"


@needs_ffmpeg
def test_elevenlabs_adapter_with_mock_transport(tmp_path):
    mp3 = tmp_path / "beep.mp3"
    run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=channel_layout=mono:sample_rate=22050", "-t", "0.4", "-c:a", "libmp3lame", str(mp3)])
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        assert request.headers["xi-api-key"] == "k" and "/v1/text-to-speech/v1" in str(request.url)
        return httpx.Response(200, content=mp3.read_bytes(), headers={"content-type": "audio/mpeg"})

    tts = ElevenLabsTTS("k", "v1", client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = tts.synthesize(["Une.", "Deux."], tmp_path / "out")
    assert len(seen) == 2 and res.audio_path.exists() and res.synthetic
    assert len(res.segments) == 2 and res.segments[1].start > res.segments[0].end
    assert 1.0 <= res.duration_s <= 2.0
