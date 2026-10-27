"""Fixtures communes : réglages isolés (tmp_path), base amorcée, LLM simulé, environnement CLI."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from core.llm import MockLLM

from content_engine.db import open_db
from content_engine.llm import FakeResponder
from content_engine.scripts import generate_scripts, set_draft_status
from content_engine.settings import Settings
from content_engine.topics import seed_topics

APP_DIR = Path(__file__).resolve().parents[1]
TOPICS_FILE = APP_DIR / "topics.yaml"
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe absents")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="mock",
        tts_provider="silent",
        tts_silent_duration_s=2.4,
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        assets_dir=tmp_path / "assets",
        topics_file=TOPICS_FILE,
        video_preset="ultrafast",
        video_crf=30,
        brand_name="@test",
    )


@pytest.fixture
def conn(settings: Settings):
    c = open_db(settings.db_path)
    seed_topics(c, settings.topics_file)
    yield c
    c.close()


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM(responses=FakeResponder())


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Variables d'environnement pour la CLI : tout dans tmp_path, LLM mock, TTS muet."""
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "DATA_DIR": str(tmp_path / "data"),
        "OUT_DIR": str(tmp_path / "out"),
        "ASSETS_DIR": str(tmp_path / "assets"),
        "TOPICS_FILE": str(TOPICS_FILE),
        "LLM_PROVIDER": "mock",
        "TTS_PROVIDER": "silent",
        "TTS_SILENT_DURATION_S": "2.4",
        "VIDEO_PRESET": "ultrafast",
        "VIDEO_CRF": "30",
        "BRAND_NAME": "@test",
    }.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def make_draft(conn, llm, topic_id: int = 1, fmt: str = "short", status: str | None = None) -> int:
    """Génère les 3 variantes d'un sujet et retourne l'identifiant de la première."""
    draft_id = generate_scripts(conn, llm, topic_id, fmt)[0]
    if status:
        set_draft_status(conn, draft_id, status)
    return draft_id


def fake_render(settings: Settings, draft_id: int, fmt: str = "short",
                synthetic_voice: bool = True) -> Path:
    """Simule un rendu (fichiers factices + render.json) pour tester la publication sans ffmpeg."""
    out = Path(settings.out_dir) / str(draft_id)
    out.mkdir(parents=True, exist_ok=True)
    info = {"draft_id": draft_id, "format": fmt, "out_dir": str(out), "video": None,
            "thumb": "thumb.jpg", "cover": "cover.jpg", "duration_s": 0.0,
            "tts_provider": "say" if synthetic_voice else "silent",
            "synthetic_voice": synthetic_voice, "synthetic_image": False}
    if fmt == "short":
        (out / "video.mp4").write_bytes(b"\x00" * 2048)
        info["video"], info["duration_s"] = "video.mp4", 30.0
    (out / "thumb.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
    (out / "cover.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
    (out / "render.json").write_text(json.dumps(info), encoding="utf-8")
    return out
