"""Socle commun : LLM, mail, réglages, SQLite, JSON."""
from .db import connect, migrate
from .jsonutil import extract_json, strip_think
from .llm import (
    LLM,
    AnthropicLLM,
    LLMError,
    LLMRefusal,
    LLMResult,
    MockLLM,
    OllamaLLM,
    complete_json,
    get_llm,
)
from .mail import ConsoleMailer, Email, Mailer, MailError, ResendMailer, SMTPMailer, get_mailer
from .settings import Settings, get_settings

__all__ = [
    "LLM",
    "AnthropicLLM",
    "ConsoleMailer",
    "Email",
    "LLMError",
    "LLMRefusal",
    "LLMResult",
    "MailError",
    "Mailer",
    "MockLLM",
    "OllamaLLM",
    "ResendMailer",
    "SMTPMailer",
    "Settings",
    "complete_json",
    "connect",
    "extract_json",
    "get_llm",
    "get_mailer",
    "get_settings",
    "migrate",
    "strip_think",
]
