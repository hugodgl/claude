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
