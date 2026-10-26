"""
Compute namespace — `client.compute.llms.*` (the LLM registry).

Wire mapping (project-plane):
  - list()                        GET  /@<slug>/compute/llms
  - read(model_id)                GET  /@<slug>/compute/llms/<model-id>
  - invoke(model_id, ...)         POST /@<slug>/compute/llms/<model-id>/invoke
  - invoke_stream(model_id, ...)  POST /@<slug>/compute/llms/<model-id>/invoke-stream   (SSE)

`invoke` returns `data = {modelId, content, finishReason, usage: {promptTokens, completionTokens, totalTokens},
usageType}`. `invoke_stream` is an async generator yielding the model server's OpenAI-style chat-completion
chunks unchanged (read text from `chunk["choices"][0]["delta"]["content"]`; the last chunk may carry `usage`).
External-provider models answer 501 `K9O_NOT_IMPLEMENTED` until the provider client is built.
K9O_LLM_PROVIDER_UNAVAILABLE (503) is the one code coined for LLM calls.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request, stream_sse_async
from .url_grammar import project_path

# Curated model ids.
LLM_MODEL_IDS = (
    "mistral-7b",
    "mistral-8x7b",
    "llama-3-8b",
    "llama-3-70b",
    "claude-3-5-sonnet",
    "gpt-4o",
    "gpt-4o-mini",
    "text-embedding-3-small",
    "text-embedding-3-large",
)

LLM_ERROR_CODES = {"PROVIDER_UNAVAILABLE": "K9O_LLM_PROVIDER_UNAVAILABLE"}


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("compute.llms operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class LlmsNamespace:
    """`client.compute.llms.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """List the models available to the project's tier."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "compute/llms"))

    def read(self, model_id: str) -> Envelope:
        """Read one model's metadata and cost."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET",
                       path=project_path(slug, f"compute/llms/{quote(model_id, safe='')}"))

    @staticmethod
    def _invoke_body(prompt: str, params: dict[str, Any] | None) -> dict[str, Any]:
        # The route reads `prompt` and the inference parameters (`maxTokens`, `temperature`, `usageType`) flat
        # in the body, so `params` is spread, not nested.
        return {"prompt": prompt, **_clean(dict(params or {}))}

    def invoke(self, model_id: str, *, prompt: str, params: dict[str, Any] | None = None) -> Envelope:
        """Synchronous inference (PROJECT_AUTHOR or PROJECT_ADMIN).

        `params` holds the gateway's inference keys, sent flat in the body: `maxTokens` (1 to 32000),
        `temperature` (0 to 2), `usageType` (a free-form label).
        """
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="POST",
            path=project_path(slug, f"compute/llms/{quote(model_id, safe='')}/invoke"),
            body=self._invoke_body(prompt, params),
        )

    async def invoke_stream(self, model_id: str, *, prompt: str, params: dict[str, Any] | None = None) -> AsyncIterator[Any]:
        """Streaming inference (SSE). Yields the parsed chunk dicts; same `params` as `invoke`.

        Consume with `async for chunk in client.compute.llms.invoke_stream(...)`.
        """
        slug = _require_project_slug(self._config)
        async for chunk in stream_sse_async(
            self._config,
            method="POST",
            path=project_path(slug, f"compute/llms/{quote(model_id, safe='')}/invoke-stream"),
            body=self._invoke_body(prompt, params),
        ):
            yield chunk


class ComputeNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.llms = LlmsNamespace(config)
