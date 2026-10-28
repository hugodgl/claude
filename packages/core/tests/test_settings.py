import pytest
from pydantic import ValidationError

from core.settings import Settings, get_settings


def test_unknown_provider_gives_clear_message():
    with pytest.raises(ValidationError) as exc:
        get_settings(llm_provider="openai")
    assert "LLM_PROVIDER='openai'" in str(exc.value) and "mock, ollama, anthropic" in str(exc.value)
    with pytest.raises(ValidationError, match="MAIL_PROVIDER"):
        get_settings(mail_provider="sendgrid")
    with pytest.raises(ValidationError, match="ANTHROPIC_EFFORT"):
        get_settings(anthropic_effort="extreme")


def test_choices_are_normalized():
    s = get_settings(llm_provider=" Mock ", mail_provider="SMTP", anthropic_effort="High")
    assert (s.llm_provider, s.mail_provider, s.anthropic_effort) == ("mock", "smtp", "high")


def test_env_file_absent_env_vars_and_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LLM_PROVIDER", "OLLAMA_MODEL", "MAIL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    s = get_settings()  # pas de .env : valeurs par défaut
    assert s.llm_provider == "ollama" and s.mail_provider == "console" and s.data_dir.name == "data"
    (tmp_path / ".env").write_text("LLM_PROVIDER=mock\nOLLAMA_MODEL=qwen3:8b\n", encoding="utf-8")
    assert get_settings().llm_provider == "mock" and get_settings().ollama_model == "qwen3:8b"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # l'environnement prime sur .env
    assert get_settings().llm_provider == "anthropic"
    assert get_settings(llm_provider="ollama").llm_provider == "ollama"  # la surcharge explicite prime sur tout


def test_subclass_keeps_validation():
    class AppSettings(Settings):
        extra_flag: bool = False

    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        AppSettings(llm_provider="nope")
    assert AppSettings(llm_provider="MOCK", extra_flag=True).llm_provider == "mock"
