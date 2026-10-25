"""
Function lifecycle namespace — `client.functions.*`.

Member-plane routes. Python idiomatic.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("functions operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class FunctionsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def deploy(self, *, name: str, runtime: str, code: str, tier: str | None = None,
               config: dict[str, Any] | None = None) -> Envelope:
        """Deploy or redeploy a function. Returns the record with status."""
        slug = _require_project_slug(self._config)
        body = _clean({"name": name, "runtime": runtime, "code": code, "tier": tier, "config": config})
        return request(self._config, method="POST", path=project_path(slug, "functions"), body=body)

    def list(self, *, limit: int | None = None, cursor: str | None = None, status: str | None = None) -> Envelope:
        """List deployed functions (cursor pagination)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "functions"),
                       query=_clean({"limit": limit, "cursor": cursor, "status": status}))

    def get(self, name: str) -> Envelope:
        """Get a function by name."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"functions/{quote(name)}"))

    def delete(self, name: str) -> Envelope:
        """Retire a function (24h name cooldown)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=project_path(slug, f"functions/{quote(name)}"))

    def invoke(self, name: str, payload: Any) -> Envelope:
        """Invoke a function; payload passed to the runtime verbatim."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST",
                       path=project_path(slug, f"functions/{quote(name)}/invoke"), body=payload)
