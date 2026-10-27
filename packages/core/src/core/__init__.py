"""Socle commun : LLM, mail, réglages, SQLite, JSON."""
from .settings import Settings, get_settings
from .llm import LLM, LLMResult, LLMError, LLMRefusal, MockLLM, OllamaLLM, AnthropicLLM, get_llm, complete_json
from .mail import Email, Mailer, ConsoleMailer, SMTPMailer, ResendMailer, get_mailer
from .db import connect, migrate
from .jsonutil import extract_json

__all__ = [
    "Settings", "get_settings",
    "LLM", "LLMResult", "LLMError", "LLMRefusal", "MockLLM", "OllamaLLM", "AnthropicLLM", "get_llm", "complete_json",
    "Email", "Mailer", "ConsoleMailer", "SMTPMailer", "ResendMailer", "get_mailer",
    "connect", "migrate", "extract_json",
]
