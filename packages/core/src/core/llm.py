"""Fournisseurs de modèles de langage : mock (tests), Ollama (local, défaut), Anthropic (option).

Contrat unique : `llm.complete(prompt, system=..., max_tokens=..., json_mode=...) -> LLMResult`.
Les apps ne doivent jamais appeler un fournisseur directement : toujours `get_llm()`.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .jsonutil import extract_json, strip_think
from .settings import Settings, get_settings


class LLMError(RuntimeError):
    """Erreur générique d'appel au modèle (réseau, quota, réponse vide)."""


class LLMRefusal(LLMError):
    """Le fournisseur a refusé la requête (classifieurs de sécurité)."""

    def __init__(self, category: str | None, explanation: str | None):
        super().__init__(f"refus du modèle (catégorie={category}) : {explanation}")
        self.category = category
        self.explanation = explanation


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


class LLM(Protocol):
    name: str
    model: str

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResult: ...


# ----------------------------------------------------------------------------------------------
# Mock
# ----------------------------------------------------------------------------------------------
@dataclass
class MockLLM:
    """Fournisseur de test. `responses` : chaîne fixe, liste consommée dans l'ordre, ou fonction."""

    responses: str | list[str] | Callable[[str, str | None], str] = "{}"
    name: str = "mock"
    model: str = "mock"
    calls: list[dict[str, Any]] = field(default_factory=list)
    _queue: deque = field(default_factory=deque, repr=False)

    def __post_init__(self):
        if isinstance(self.responses, list):
            self._queue = deque(self.responses)

    def complete(self, prompt, *, system=None, max_tokens=1024, json_mode=False) -> LLMResult:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens, "json_mode": json_mode})
        if callable(self.responses):
            text = self.responses(prompt, system)
        elif isinstance(self.responses, list):
            if not self._queue:
                raise LLMError("MockLLM : plus de réponses en file")
            text = self._queue.popleft()
        else:
            text = self.responses
        return LLMResult(text=text, provider="mock", model="mock", stop_reason="end_turn")


# ----------------------------------------------------------------------------------------------
# Ollama (local)
# ----------------------------------------------------------------------------------------------
class OllamaLLM:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 180.0, think: bool = False,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.think = think
        self._client = client or httpx.Client(timeout=timeout_s)

    def complete(self, prompt, *, system=None, max_tokens=1024, json_mode=False) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": self.think,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        try:
            r = self._client.post(f"{self.base_url}/api/generate", json=payload)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama HTTP {e.response.status_code} : {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama injoignable sur {self.base_url} : {e}") from e
        data = r.json()
        text = strip_think(data.get("response", ""))
        if not text:
            raise LLMError("Ollama : réponse vide")
        return LLMResult(
            text=text, provider="ollama", model=self.model,
            input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"),
            stop_reason=data.get("done_reason"),
        )


# ----------------------------------------------------------------------------------------------
# Anthropic (option, qualité)
# ----------------------------------------------------------------------------------------------
class AnthropicLLM:
    """Appelle l'API Claude via le SDK officiel. Modèle par défaut : claude-opus-5-5.

    La réflexion adaptative est active par défaut sur ce modèle ; la profondeur se règle avec
    `effort`. Avec `fallbacks=True`, un refus de sécurité est rejoué côté serveur sur un autre
    modèle (bêta `server-side-fallback-2026-07-01`, forme `fallbacks="default"`).
    """

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low", fallbacks: bool = True,
                 timeout_s: float = 180.0, client: Any | None = None):
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        if client is None:
            try:
                import anthropic  # import paresseux : dépendance optionnelle
            except ImportError as e:  # pragma: no cover
                raise LLMError("installer l'extra : uv pip install 'core[anthropic]'") from e
            client = anthropic.Anthropic(timeout=timeout_s)
        self._client = client

    def complete(self, prompt, *, system=None, max_tokens=1024, json_mode=False) -> LLMResult:
        import anthropic

        sys_prompt = system or ""
        if json_mode:
            sys_prompt = (sys_prompt + "\n\nRéponds uniquement avec un objet JSON valide, sans texte autour.").strip()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort},
        }
        if sys_prompt:
            kwargs["system"] = sys_prompt
        try:
            if self.fallbacks:
                response = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                response = self._client.messages.create(**kwargs)
        except anthropic.NotFoundError as e:
            raise LLMError(f"Anthropic : modèle ou endpoint introuvable ({e.message})") from e
        except anthropic.RateLimitError as e:
            retry_after = e.response.headers.get("retry-after", "?")
            raise LLMError(f"Anthropic : quota atteint, réessayer dans {retry_after}s") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic : erreur HTTP {e.status_code} ({e.message})") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Anthropic : erreur réseau ({e})") from e

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(getattr(details, "category", None), getattr(details, "explanation", None))
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
        if not text:
            raise LLMError("Anthropic : réponse sans texte")
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=text, provider="anthropic", model=getattr(response, "model", self.model),
            input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
            stop_reason=response.stop_reason,
        )


# ----------------------------------------------------------------------------------------------
# Fabrique et utilitaires
# ----------------------------------------------------------------------------------------------
def get_llm(settings: Settings | None = None) -> LLM:
    s = settings or get_settings()
    if s.llm_provider == "mock":
        return MockLLM()
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_base_url, s.ollama_model, s.llm_timeout_s, think=s.ollama_think)
    if s.llm_provider == "anthropic":
        return AnthropicLLM(s.anthropic_model, s.anthropic_effort, s.anthropic_fallbacks, s.llm_timeout_s)
    raise LLMError(f"fournisseur LLM inconnu : {s.llm_provider}")


def complete_json(llm: LLM, prompt: str, *, system: str | None = None, max_tokens: int = 2048,
                  retries: int = 1) -> Any:
    """Demande une réponse JSON et la parse ; relance une fois avec une consigne plus stricte si besoin."""
    last_error: Exception | None = None
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        result = llm.complete(attempt_prompt, system=system, max_tokens=max_tokens, json_mode=True)
        try:
            return extract_json(result.text)
        except ValueError as e:
            last_error = e
            attempt_prompt = (
                prompt + "\n\nTa réponse précédente n'était pas du JSON valide. "
                "Réponds uniquement avec un objet JSON valide, sans commentaire."
            )
    raise LLMError(f"réponse JSON invalide après {retries + 1} tentatives : {last_error}")
