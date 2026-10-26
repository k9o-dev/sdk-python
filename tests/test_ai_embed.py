"""`client.ai.embed()` — URL, verb, body shape, bound-project guard, and that errors never echo the input."""

import json

import httpx
import pytest

from k9o import KError, create_client

OK = {"data": {"embeddings": [[0.1, 0.2]], "model": "nomic-embed-text-v1.5", "dimensions": 2}, "meta": {}}


def _client(cap, body=OK, status=200, project_slug="member-portal"):
    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["method"] = request.method
        cap["body"] = request.content.decode() if request.content else None
        return httpx.Response(status, json=body)

    c = create_client(base_url="https://acme.api.k9o.io", project_slug=project_slug)
    c._config.transport = httpx.MockTransport(handler)
    return c


class TestAiEmbed:
    def test_posts_and_returns_vectors(self):
        cap = {}
        r = _client(cap).ai.embed("hello")
        assert cap["method"] == "POST"
        assert cap["url"] == "https://acme.api.k9o.io/@member-portal/ai/embeddings"
        assert json.loads(cap["body"]) == {"input": "hello"}
        assert r.data["embeddings"] == [[0.1, 0.2]]
        assert r.data["dimensions"] == 2

    def test_array_input_and_model_as_given(self):
        cap = {}
        _client(cap).ai.embed(["search_document: a", "search_document: b"], model="nomic-embed-text-v1.5")
        assert json.loads(cap["body"]) == {
            "model": "nomic-embed-text-v1.5",
            "input": ["search_document: a", "search_document: b"],
        }

    def test_model_omitted_when_not_given(self):
        cap = {}
        _client(cap).ai.embed(["x"])
        assert "model" not in json.loads(cap["body"])

    def test_requires_bound_project(self):
        cap = {}
        c = _client(cap, project_slug=None)
        with pytest.raises(ValueError, match="project_slug"):
            c.ai.embed("x")
        assert cap == {}

    def test_server_refusal_is_kerror_without_input_text(self):
        cap = {}
        err = {
            "code": "K9O_MODEL_NOT_DECLARED",
            "message": "model is not a declared embedding model",
            "context": {"declared": ["nomic-embed-text-v1.5"]},
            "recommendation": None,
        }
        secret = "the-secret-document-body"
        with pytest.raises(KError) as exc:
            _client(cap, err, 400).ai.embed(secret, model="other")
        assert exc.value.code == "K9O_MODEL_NOT_DECLARED"
        assert secret not in str(exc.value)
        assert secret not in repr(exc.value)
