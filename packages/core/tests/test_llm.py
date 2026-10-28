import pytest

from core.llm import LLMError, MockLLM, OllamaLLM, complete_json, get_llm
from core.settings import get_settings


def test_mock_queue_and_calls():
    llm = MockLLM(["a", "b"])
    assert llm.complete("p1").text == "a"
    assert llm.complete("p2", system="s").text == "b"
    assert llm.calls[1]["system"] == "s"
    with pytest.raises(LLMError):
        llm.complete("p3")


def test_complete_json_retries_once():
    llm = MockLLM(["pas du json", '{"ok": 1}'])
    assert complete_json(llm, "donne du json") == {"ok": 1}
    assert len(llm.calls) == 2
    assert "JSON valide" in llm.calls[1]["prompt"]


def test_complete_json_fails_after_retries():
    llm = MockLLM("toujours du texte")
    with pytest.raises(LLMError):
        complete_json(llm, "x", retries=1)


def test_get_llm_mock_and_ollama_from_settings():
    assert isinstance(get_llm(get_settings(llm_provider="mock")), MockLLM)
    o = get_llm(get_settings(llm_provider="ollama", ollama_model="qwen3:8b", ollama_base_url="http://h:1/"))
    assert isinstance(o, OllamaLLM)
    assert o.model == "qwen3:8b" and o.base_url == "http://h:1"


def test_ollama_parses_response(monkeypatch):
    import httpx

    def handler(request: httpx.Request):
        assert request.url.path == "/api/generate"
        body = request.read().decode()
        assert '"format": "json"' in body or '"format":"json"' in body
        return httpx.Response(200, json={"response": "<think>hm</think>{\"x\": 1}", "prompt_eval_count": 10,
                                         "eval_count": 5, "done_reason": "stop"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = OllamaLLM("http://ollama.test", "qwen3:14b", client=client)
    res = llm.complete("q", json_mode=True)
    assert res.text == '{"x": 1}' and res.input_tokens == 10 and res.stop_reason == "stop"


# ----------------------------------------------------------------------------------------------
# Revue croisée : MockLLM, troncature, Ollama, Anthropic (faux client, sans réseau)
# ----------------------------------------------------------------------------------------------
import httpx

from core.llm import AnthropicLLM, LLMRefusal, LLMResult


def test_mock_tuple_callable_and_stop_reason():
    llm = MockLLM(("a", "b"))
    assert [llm.complete("p").text for _ in range(2)] == ["a", "b"]
    seen = []
    fn = MockLLM(lambda prompt, system: seen.append((prompt, system)) or "ok")
    assert fn.complete("p", system="s").text == "ok" and seen == [("p", "s")]
    cut = MockLLM("x", stop_reason="max_tokens")
    assert cut.complete("p").truncated
    with pytest.raises(LLMError, match="plus de réponses"):
        MockLLM([]).complete("p")


def test_llmresult_truncated_covers_both_vocabularies():
    assert LLMResult("t", "anthropic", "m", stop_reason="max_tokens").truncated
    assert LLMResult("t", "ollama", "m", stop_reason="length").truncated
    assert not LLMResult("t", "ollama", "m", stop_reason="stop").truncated
    assert not LLMResult("t", "mock", "m").truncated


def test_complete_json_reports_truncation_and_asks_for_concision():
    llm = MockLLM(['{"a": "coup', '{"a": "enc'], stop_reason="max_tokens")
    with pytest.raises(LLMError) as exc:
        complete_json(llm, "x", max_tokens=64)
    assert "tronquée" in str(exc.value) and "max_tokens=64" in str(exc.value)
    assert "concis" in llm.calls[1]["prompt"]


def test_complete_json_rejects_scalar_answers():
    llm = MockLLM(["null", "42"])
    with pytest.raises(LLMError, match="2 tentatives"):
        complete_json(llm, "x")


def _ollama(handler, **kwargs):
    return OllamaLLM("http://ollama.test", "qwen3:14b", client=httpx.Client(transport=httpx.MockTransport(handler)),
                     **kwargs)


def test_ollama_payload_shape():
    seen = {}

    def handler(request: httpx.Request):
        import json

        seen.update(json.loads(request.read()))
        return httpx.Response(200, json={"response": "ok", "done_reason": "stop"})

    _ollama(handler, think=False).complete("q", system="sys", max_tokens=321)
    assert seen["options"]["num_predict"] == 321 and seen["think"] is False and seen["system"] == "sys"
    assert "format" not in seen and seen["stream"] is False


def test_ollama_missing_model_hints_pull():
    def handler(request):
        return httpx.Response(404, json={"error": "model 'qwen3:14b' not found, try pulling it first"})

    with pytest.raises(LLMError, match="ollama pull qwen3:14b"):
        _ollama(handler).complete("q")


def test_ollama_think_unsupported_hint():
    def handler(request):
        return httpx.Response(400, json={"error": '"qwen3:14b" does not support thinking'})

    with pytest.raises(LLMError, match="OLLAMA_THINK"):
        _ollama(handler, think=True).complete("q")


def test_ollama_timeout_and_unreachable_messages():
    def slow(request):
        raise httpx.ReadTimeout("lent")

    with pytest.raises(LLMError, match=r"12s"):
        _ollama(slow, timeout_s=12).complete("q")

    def down(request):
        raise httpx.ConnectError("refusé")

    with pytest.raises(LLMError, match="ollama serve"):
        _ollama(down).complete("q")


def test_ollama_truncated_and_empty_responses():
    def cut(request):
        return httpx.Response(200, json={"response": '{"a": "tron', "done_reason": "length", "eval_count": 8})

    res = _ollama(cut).complete("q", max_tokens=8)
    assert res.truncated and res.stop_reason == "length" and res.text.startswith('{"a"')

    def empty_cut(request):
        return httpx.Response(200, json={"response": "", "thinking": "hmm", "done_reason": "length"})

    with pytest.raises(LLMError, match="max_tokens"):
        _ollama(empty_cut).complete("q")

    def not_json(request):
        return httpx.Response(200, text="<html>proxy</html>")

    with pytest.raises(LLMError, match="non JSON"):
        _ollama(not_json).complete("q")


class _Block:
    def __init__(self, type, text=""):
        self.type, self.text = type, text


class _Response:
    def __init__(self, blocks, stop_reason="end_turn", model="claude-opus-5-5", stop_details=None):
        self.content, self.stop_reason, self.model, self.stop_details = blocks, stop_reason, model, stop_details
        self.usage = type("U", (), {"input_tokens": 3, "output_tokens": 4})()


class _FakeClient:
    """Imite `anthropic.Anthropic` : enregistre les kwargs des deux chemins (bêta ou non)."""

    def __init__(self, response):
        self.calls: list[tuple[str, dict]] = []
        outer = self

        class _Messages:
            def __init__(self, path):
                self.path = path

            def create(self, **kwargs):
                outer.calls.append((self.path, kwargs))
                return response

        self.messages = _Messages("messages")
        self.beta = type("B", (), {"messages": _Messages("beta.messages")})()


def test_anthropic_request_shape_with_and_without_fallbacks():
    client = _FakeClient(_Response([_Block("thinking"), _Block("text", '{"ok": 1}')]))
    res = AnthropicLLM(model="claude-opus-5-5", effort="low", fallbacks=True, client=client).complete(
        "p", system="s", max_tokens=555, json_mode=True)
    path, kwargs = client.calls[0]
    assert path == "beta.messages" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default" and kwargs["output_config"] == {"effort": "low"}
    assert kwargs["max_tokens"] == 555 and "temperature" not in kwargs and "JSON" in kwargs["system"]
    assert res.text == '{"ok": 1}' and res.input_tokens == 3 and res.stop_reason == "end_turn"

    AnthropicLLM(fallbacks=False, effort="high", client=client).complete("p")
    path, kwargs = client.calls[1]
    assert path == "messages" and "fallbacks" not in kwargs and "betas" not in kwargs
    assert kwargs["output_config"] == {"effort": "high"} and "system" not in kwargs


def test_anthropic_refusal_and_truncation():
    details = type("D", (), {"category": "cyber", "explanation": "non"})()
    with pytest.raises(LLMRefusal) as exc:
        AnthropicLLM(client=_FakeClient(_Response([], "refusal", stop_details=details))).complete("p")
    assert exc.value.category == "cyber"

    with pytest.raises(LLMError, match="max_tokens=40"):
        AnthropicLLM(client=_FakeClient(_Response([_Block("thinking")], "max_tokens"))).complete("p", max_tokens=40)

    res = AnthropicLLM(client=_FakeClient(_Response([_Block("text", '{"a": "cou')], "max_tokens"))).complete("p")
    assert res.truncated


def test_anthropic_sdk_errors_are_translated():
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")

    def make(status, body, headers=None):
        def handler(request):
            return httpx2.Response(status, json=body, headers=headers or {})

        return anthropic.Anthropic(api_key="sk-test", max_retries=0,
                                   http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))

    err = {"type": "error", "error": {"type": "x", "message": "m"}}
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicLLM(client=make(401, err)).complete("p")
    with pytest.raises(LLMError, match="claude-nope"):
        AnthropicLLM(model="claude-nope", client=make(404, err)).complete("p")
    with pytest.raises(LLMError, match="dans 7s"):
        AnthropicLLM(client=make(429, err, {"retry-after": "7"})).complete("p")
    with pytest.raises(LLMError, match="ANTHROPIC_FALLBACKS"):
        beta = {"type": "error", "error": {"type": "invalid_request_error",
                                           "message": "Unexpected value(s) `server-side-fallback-2026-07-01` for the `anthropic-beta` header"}}
        AnthropicLLM(client=make(400, beta)).complete("p")
