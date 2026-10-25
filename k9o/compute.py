"""
Compute namespace — `client.compute.llms.*` (Compute
LLMs registry).

Python idiomatic shape +: sync list/read/invoke
return Envelope; invoke_stream is an async generator yielding chunks
(`async for chunk in client.compute.llms.invoke_stream(...)`).

K9O_LLM_PROVIDER_UNAVAILABLE (503) coined; others reused.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request, stream_sse_async
from .url_grammar import project_path

# Curated 9-model closed enum (extensible v2.x).
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

    def list(self, *, modality: str | None = None, provider_class: str | None = None) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="GET",
            path=project_path(slug, "compute/llms"),
            query=_clean({"modality": modality, "providerClass": provider_class}),
        )

    def read(self, model_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"compute/llms/{quote(model_id)}"))

    def invoke(self, model_id: str, *, prompt: str, params: dict[str, Any] | None = None) -> Envelope:
        """Synchronous inference (PROJECT_AUTHOR/ADMIN)."""
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="POST",
            path=project_path(slug, f"compute/llms/{quote(model_id)}/invoke"),
            body={"prompt": prompt, "params": params},
        )

    async def invoke_stream(self, model_id: str, *, prompt: str, params: dict[str, Any] | None = None) -> AsyncIterator[Any]:
        """Streaming inference (SSE per-token).

        Yields parsed chunk dicts ({"delta": ..., "done": ..., ...}).
        Consume with `async for chunk in client.compute.llms.invoke_stream(...)`.
        """
        slug = _require_project_slug(self._config)
        async for chunk in stream_sse_async(
            self._config,
            method="POST",
            path=project_path(slug, f"compute/llms/{quote(model_id)}/invoke-stream"),
            body={"prompt": prompt, "params": params},
        ):
            yield chunk


class ComputeNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.llms = LlmsNamespace(config)
