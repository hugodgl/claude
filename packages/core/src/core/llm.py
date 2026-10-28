"""Fournisseurs de modèles de langage : mock (tests), Ollama (local, défaut), Anthropic (option).

Contrat unique : `llm.complete(prompt, system=..., max_tokens=..., json_mode=...) -> LLMResult`.
Les apps ne doivent jamais appeler un fournisseur directement : toujours `get_llm()`.

Une réponse coupée par `max_tokens` n'est pas une erreur : elle est retournée avec son texte et
`LLMResult.truncated` vaut True (`stop_reason` natif : `max_tokens` chez Anthropic, `length` chez
Ollama). `complete_json` s'en sert pour relancer avec une consigne plus concise et pour nommer la
troncature dans son message d'erreur.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .jsonutil import extract_json, strip_think
from .settings import Settings, get_settings

# Valeurs de `stop_reason` qui signifient « coupé par le budget de sortie », par fournisseur.
_TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "length"})
# Bêta de l'API Claude qui active `fallbacks="default"` (rejeu serveur d'un refus de sécurité).
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Erreur d'appel au modèle : réseau, délai, quota, modèle absent, réponse vide ou JSON invalide."""


class LLMRefusal(LLMError):
    """Le fournisseur a refusé la requête (classifieurs de sécurité, `stop_reason == "refusal"`)."""

    def __init__(self, category: str | None, explanation: str | None):
        super().__init__(f"refus du modèle (catégorie={category}) : {explanation}")
        self.category = category
        self.explanation = explanation


@dataclass
class LLMResult:
    """Réponse d'un fournisseur. `stop_reason` garde la valeur native du fournisseur."""

    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None

    @property
    def truncated(self) -> bool:
        """Vrai si la réponse a été coupée par `max_tokens` (`max_tokens` Anthropic, `length` Ollama)."""
        return self.stop_reason in _TRUNCATED_STOP_REASONS


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
    """Fournisseur de test, sans réseau.

    `responses` : chaîne fixe (toujours la même réponse), liste ou tuple consommé dans l'ordre
    (LLMError « plus de réponses en file » une fois épuisé), ou fonction `(prompt, system) -> str`.
    Chaque appel est enregistré dans `calls` ; `stop_reason` permet de simuler une troncature
    (`"max_tokens"`).
    """

    responses: str | Sequence[str] | Callable[[str, str | None], str] = "{}"
    name: str = "mock"
    model: str = "mock"
    calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    _queue: deque = field(default_factory=deque, repr=False)

    def __post_init__(self):
        if isinstance(self.responses, (list, tuple)):
            self._queue = deque(self.responses)

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024,
                 json_mode: bool = False) -> LLMResult:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens, "json_mode": json_mode})
        if callable(self.responses):
            text = self.responses(prompt, system)
        elif isinstance(self.responses, (list, tuple)):
            if not self._queue:
                raise LLMError(f"MockLLM : plus de réponses en file après {len(self.responses)} appel(s)")
            text = self._queue.popleft()
        else:
            text = self.responses
        return LLMResult(text=text, provider="mock", model="mock", stop_reason=self.stop_reason)


# ----------------------------------------------------------------------------------------------
# Ollama (local)
# ----------------------------------------------------------------------------------------------
class OllamaLLM:
    """Ollama local via `POST /api/generate` (sans flux).

    `max_tokens` devient `options.num_predict` ; `json_mode` active `format=json` ; `think` est
    envoyé explicitement (False désactive la réflexion de Qwen3, qui est active par défaut ; True
    exige un modèle qui la gère). `timeout_s` s'applique à chaque requête, même avec un `client`
    injecté.
    """

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 180.0, think: bool = False,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.think = think
        self._client = client or httpx.Client(timeout=timeout_s)

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024,
                 json_mode: bool = False) -> LLMResult:
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
            r = self._client.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMError(self._describe_http_error(e.response)) from e
        except httpx.TimeoutException as e:
            raise LLMError(
                f"Ollama : pas de réponse de {self.model} en {self.timeout_s:g}s "
                "(augmenter LLM_TIMEOUT_S, réduire max_tokens ou choisir un modèle plus petit)"
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama injoignable sur {self.base_url} ({e}) : lancer `ollama serve`") from e
        try:
            data = r.json()
        except ValueError as e:
            raise LLMError(f"Ollama : réponse non JSON depuis {self.base_url} ({r.text[:120]!r})") from e
        stop_reason = data.get("done_reason")
        text = strip_think(data.get("response") or "")
        if not text:
            if stop_reason == "length":
                raise LLMError(
                    f"Ollama : réponse coupée par max_tokens={max_tokens} avant tout texte "
                    "(avec OLLAMA_THINK=true la réflexion consomme ce budget) : augmenter max_tokens"
                )
            raise LLMError("Ollama : réponse vide")
        return LLMResult(
            text=text, provider="ollama", model=self.model,
            input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"),
            stop_reason=stop_reason,
        )

    def _describe_http_error(self, response: httpx.Response) -> str:
        try:
            detail = str(response.json().get("error") or response.text)
        except (ValueError, AttributeError):
            detail = response.text
        detail = detail.strip()[:200]
        lowered = detail.lower()
        if response.status_code == 404:
            if "model" in lowered and "not found" in lowered:
                return f"Ollama : modèle {self.model!r} absent ({detail}) : exécuter `ollama pull {self.model}`"
            return (f"Ollama HTTP 404 sur {self.base_url}/api/generate ({detail}) : vérifier OLLAMA_BASE_URL "
                    f"ou exécuter `ollama pull {self.model}`")
        if response.status_code == 400 and "think" in lowered:
            return (f"Ollama : le modèle {self.model!r} ne gère pas le mode réflexion ({detail}) : "
                    "mettre OLLAMA_THINK=false")
        return f"Ollama HTTP {response.status_code} : {detail}"


# ----------------------------------------------------------------------------------------------
# Anthropic (option, qualité)
# ----------------------------------------------------------------------------------------------
class AnthropicLLM:
    """Appelle l'API Claude via le SDK officiel (extra `core[anthropic]`). Modèle par défaut : claude-opus-5-5.

    La réflexion adaptative est toujours active sur ce modèle ; sa profondeur se règle avec `effort`
    (`output_config.effort`), aucun paramètre d'échantillonnage n'est envoyé. Les jetons de réflexion
    comptent dans `max_tokens` : un budget trop serré coupe la réponse avant le texte (LLMError explicite).
    Avec `fallbacks=True`, la requête passe par `client.beta.messages.create(..., betas=[...],
    fallbacks="default")` : un refus de sécurité est rejoué côté serveur sur un autre modèle ; sinon
    `client.messages.create`. Un refus final lève LLMRefusal.
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

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024,
                 json_mode: bool = False) -> LLMResult:
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
                    betas=[ANTHROPIC_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                response = self._client.messages.create(**kwargs)
        except Exception as e:
            message = _anthropic_error_message(e, self.model)
            if message is None:  # pas une erreur du SDK : on ne masque rien
                raise
            raise LLMError(message) from e

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(getattr(details, "category", None), getattr(details, "explanation", None))
        text = "".join(
            getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            if stop_reason == "max_tokens":
                raise LLMError(
                    f"Anthropic : réponse coupée par max_tokens={max_tokens} avant tout texte "
                    "(la réflexion adaptative consomme ce budget) : augmenter max_tokens ou baisser ANTHROPIC_EFFORT"
                )
            raise LLMError("Anthropic : réponse sans texte")
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=text, provider="anthropic", model=getattr(response, "model", None) or self.model,
            input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
            stop_reason=stop_reason,
        )


def _anthropic_error_message(error: Exception, model: str) -> str | None:
    """Traduit une exception du SDK Anthropic en message exploitable ; None si ce n'en est pas une."""
    try:
        import anthropic
    except ImportError:
        return None
    if not isinstance(error, anthropic.AnthropicError):
        return None
    if isinstance(error, anthropic.AuthenticationError):
        return "Anthropic : clé API absente ou invalide (ANTHROPIC_API_KEY)"
    if isinstance(error, anthropic.NotFoundError):
        return f"Anthropic : modèle {model!r} introuvable ou non ouvert à ce compte (ANTHROPIC_MODEL) : {error.message}"
    if isinstance(error, anthropic.RateLimitError):
        retry_after = error.response.headers.get("retry-after", "?")
        return f"Anthropic : quota atteint, réessayer dans {retry_after}s"
    if isinstance(error, anthropic.BadRequestError) and "anthropic-beta" in str(error.message):
        return (f"Anthropic : bêta {ANTHROPIC_FALLBACK_BETA} refusée pour ce compte ({error.message}) : "
                "mettre ANTHROPIC_FALLBACKS=false")
    if isinstance(error, anthropic.APIStatusError):
        return f"Anthropic : erreur HTTP {error.status_code} ({error.message})"
    if isinstance(error, anthropic.APITimeoutError):
        return f"Anthropic : délai dépassé ({error}) : augmenter LLM_TIMEOUT_S"
    if isinstance(error, anthropic.APIConnectionError):
        return f"Anthropic : erreur réseau ({error})"
    return f"Anthropic : {error}"


# ----------------------------------------------------------------------------------------------
# Fabrique et utilitaires
# ----------------------------------------------------------------------------------------------
def get_llm(settings: Settings | None = None) -> LLM:
    """Construit le fournisseur désigné par `settings.llm_provider` (réglages lus par défaut)."""
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
    """Demande une réponse JSON (`json_mode=True`) et retourne l'objet ou le tableau parsé.

    Si la réponse n'est pas du JSON exploitable, relance jusqu'à `retries` fois avec une consigne
    plus stricte (plus concise si la réponse précédente a été coupée par `max_tokens`), puis lève
    LLMError en nommant une éventuelle troncature. Les LLMError du fournisseur remontent telles quelles.
    """
    last_error: Exception | None = None
    last_result: LLMResult | None = None
    attempt_prompt = prompt
    for _ in range(retries + 1):
        result = llm.complete(attempt_prompt, system=system, max_tokens=max_tokens, json_mode=True)
        last_result = result
        try:
            return extract_json(result.text)
        except ValueError as e:
            last_error = e
            if result.truncated:
                attempt_prompt = (
                    prompt + "\n\nTa réponse précédente a été coupée avant la fin. "
                    "Réponds uniquement avec un objet JSON valide, plus concis, sans commentaire."
                )
            else:
                attempt_prompt = (
                    prompt + "\n\nTa réponse précédente n'était pas du JSON valide. "
                    "Réponds uniquement avec un objet JSON valide, sans commentaire."
                )
    detail = str(last_error)
    if last_result is not None and last_result.truncated:
        detail = (f"réponse tronquée (stop_reason={last_result.stop_reason}, max_tokens={max_tokens}, "
                  f"augmenter max_tokens) : {detail}")
    raise LLMError(f"réponse JSON invalide après {retries + 1} tentatives : {detail}")
