"""
AI namespace — `client.ai.*` (platform AI primitives).

Wire mapping (project-plane):
  - embed(input, model=None) -> POST /@<slug>/ai/embeddings
        body {model?, input: str | list[str]}
        -> Envelope(data={"embeddings": [[float, ...], ...], "model": str, "dimensions": int})

Bounds (non-empty inputs, count, size, concurrency) are enforced by the
gateway, not here. The SDK sends `input` exactly as given and never puts it
in an error it constructs.
"""

from __future__ import annotations

from typing import Sequence

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("ai operations require project_slug bound on the client")
    return config.project_slug


class AiNamespace:
    """`client.ai.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def embed(self, input: str | Sequence[str], *, model: str | None = None) -> Envelope:
        """POST /@<slug>/ai/embeddings — embed one string or a list of strings.

        `model` is omitted from the body when None (server default). A single
        string stays a string; a sequence is sent as a list, in order.
        """
        slug = _require_project_slug(self._config)
        body: dict = {"input": input if isinstance(input, str) else list(input)}
        if model is not None:
            body["model"] = model
        return request(self._config, method="POST", path=project_path(slug, "ai/embeddings"), body=body)
