"""`client.ai.generate()` — URL, verb, body shape (prompt first, optional fields omitted), result, errors."""

import json

import httpx
import pytest

from k9o import KError, create_client

OK = {
    "data": {
        "modelId": "llama-3-8b",
        "content": "Hi there, friend!",
        "finishReason": "stop",
        "usage": {"promptTokens": 5, "completionTokens": 4, "totalTokens": 9},
        "usageType": "ai.generate",
    },
    "meta": {},
}


def _client(cap, body=OK, status=200, project_slug="member-portal"):
    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["method"] = request.method
        cap["body"] = request.content.decode() if request.content else None
        return httpx.Response(status, json=body)

    c = create_client(base_url="https://acme.api.k9o.io", project_slug=project_slug)
    c._config.transport = httpx.MockTransport(handler)
    return c


class TestAiGenerate:
    def test_posts_prompt_only_and_parses_result(self):
        cap = {}
        r = _client(cap).ai.generate("Say hi")
        assert cap["method"] == "POST"
        assert cap["url"] == "https://acme.api.k9o.io/@member-portal/ai/generate"
        assert json.loads(cap["body"]) == {"prompt": "Say hi"}
        assert r.data["content"] == "Hi there, friend!"
        assert r.data["modelId"] == "llama-3-8b"
        assert r.data["usage"]["totalTokens"] == 9

    def test_all_fields_use_wire_names(self):
        cap = {}
        _client(cap).ai.generate("p", "llama-3-8b", 20, 0.5, "ai.generate")
        assert json.loads(cap["body"]) == {
            "prompt": "p",
            "model": "llama-3-8b",
            "maxTokens": 20,
            "temperature": 0.5,
            "usageType": "ai.generate",
        }

    def test_zero_temperature_is_sent(self):
        cap = {}
        _client(cap).ai.generate("p", temperature=0)
        assert json.loads(cap["body"]) == {"prompt": "p", "temperature": 0}

    def test_requires_bound_project(self):
        cap = {}
        with pytest.raises(ValueError, match="project_slug"):
            _client(cap, project_slug=None).ai.generate("x")
        assert cap == {}

    def test_no_default_model_is_400_kerror(self):
        cap = {}
        err = {"code": "K9O_INVALID_FIELD_VALUE", "message": "no default LLM", "context": {}, "recommendation": None}
        with pytest.raises(KError) as exc:
            _client(cap, err, 400).ai.generate("x")
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_outside_provider_model_is_501_kerror(self):
        cap = {}
        err = {
            "code": "K9O_NOT_IMPLEMENTED",
            "message": "External LLM provider dispatch is not configured",
            "context": {"modelId": "gpt-4o", "provider": "openai"},
            "recommendation": None,
        }
        with pytest.raises(KError) as exc:
            _client(cap, err, 501).ai.generate("x", model="gpt-4o")
        assert exc.value.code == "K9O_NOT_IMPLEMENTED"
